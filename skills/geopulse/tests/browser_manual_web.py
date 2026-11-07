#!/usr/bin/env python3
"""Real-Chrome manual Consumer Web flow with isolated data and offline judging."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from browser_support import ReportsPage, call

OUTPUT = ROOT / "test-results" / "browser-manual"
PASSWORD = "test-browser-password"
PRODUCT_URL = "https://consumer.example.test/chat"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def wait_server(port: int, process: subprocess.Popen) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"test server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("test server did not start")


def assert_no_overflow(page, label: str) -> None:
    dimensions = page.evaluate("() => ({width: innerWidth, scroll: document.documentElement.scrollWidth})")
    assert dimensions["scroll"] <= dimensions["width"], f"{label} horizontal overflow: {dimensions}"


def login(page, base: str, email: str, password: str) -> None:
    page.goto(base, wait_until="networkidle")
    page.get_by_label("邮箱").fill(email)
    page.get_by_label("密码").fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    page.get_by_text("项目总览", exact=True).first.wait_for()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-manual-browser-") as temporary:
        temp = Path(temporary)
        evidence_path = temp / "browser-evidence.png"
        evidence_path.write_bytes(PNG)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "GEOPULSE_DB": str(temp / "browser.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
               "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
               "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_ADMIN_EMAIL": "admin@browser.local",
               "GEOPULSE_ADMIN_PASSWORD": PASSWORD, "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_PORT": str(port)}
        os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
        from backend.app.db import connect, one
        from backend.app.migrations import initialize
        from backend.app.services.measurement import Worker
        initialize(seed=True)
        log = (temp / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        errors = []
        external = []
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None, headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(f"pageerror: {error.stack or error}"))
                page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)

                def guard(route):
                    if route.request.url.startswith(base):
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()

                context.route("**/*", guard)
                login(page, base, "admin@browser.local", PASSWORD)
                errors.clear()  # logged-out bootstrap /auth/me 401 is expected

                prompt_set = call(page, "post", "/api/projects/1/prompt-sets", {"name": "人工 Web 浏览器单题"})
                imported = call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/items", {
                    "items": [{"text": "哪些 GEO 工具适合证据审计？", "dimension": "choice", "query_type": "discovery",
                               "priority": 5, "eligibility": "eligible"}]})
                item_id = imported["items"][0]["id"]
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/items/{item_id}/review",
                     {"status": "reviewed", "eligibility": "eligible"})
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/status",
                     {"status": "reviewing", "reason": "浏览器隔离夹具"})
                # Relax only this isolated fixture's seed-data quotas, never a frozen measurement threshold.
                call(page, "put", "/api/projects/1/settings", {"settings": {
                    "prompt_quotas": {"brand": 0, "scene": 0, "compare": 0, "choice": 0}}})
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/status",
                     {"status": "frozen", "reason": "浏览器隔离夹具冻结"})

                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("button", name="新增引擎", exact=True).click()
                dialog = page.get_by_role("dialog", name="新增引擎", exact=True)
                dialog.get_by_label("配置名称").fill("人工消费者网页夹具")
                dialog.get_by_label("厂商 / 产品").fill("Manual Browser Fixture")
                dialog.get_by_label("目标类型").select_option("manual_web")
                dialog.get_by_label("HTTPS 产品入口").fill(PRODUCT_URL)
                assert dialog.get_by_label("API Key").count() == 0 or not dialog.get_by_label("API Key").is_visible()
                assert not dialog.get_by_text("价格与调用预估", exact=True).is_visible()
                with page.expect_response(lambda response: response.url.endswith("/api/projects/1/engines")
                                          and response.request.method == "POST") as pending:
                    dialog.get_by_role("button", name="保存测量目标", exact=True).click()
                target = pending.value.json()
                assert target["kind"] == "manual_web" and target["measurement_target"] == "consumer_web"
                assert not target["has_api_key"]
                page.get_by_text("人工消费者网页夹具", exact=True).wait_for()
                assert_no_overflow(page, "target desktop")
                page.screenshot(path=OUTPUT / "01-manual-target-1440.png", full_page=True)

                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_role("button", name="新建测量方案", exact=True).click()
                wizard = page.get_by_role("dialog", name="新建测量方案", exact=True)
                wizard.get_by_label("Wave 名称").fill("人工 Consumer Web 浏览器验收")
                wizard.get_by_label("冻结问题集").select_option(str(prompt_set["id"]))
                wizard.get_by_label("采样轮次").select_option("1")
                wizard.locator(".check-field").filter(has_text="人工消费者网页夹具").locator("input").check()
                assert wizard.get_by_label("产品入口").input_value() == PRODUCT_URL
                assert wizard.get_by_label("独立 Judge 引擎").is_visible()
                wizard.get_by_label("平台").fill("manual_browser_fixture")
                wizard.get_by_label("地区", exact=True).fill("CN")
                wizard.get_by_label("语言", exact=True).fill("zh-CN")
                with page.expect_response(lambda response: response.url.endswith("/api/projects/1/waves")
                                          and response.request.method == "POST") as pending:
                    wizard.get_by_role("button", name="创建方案并查看预估", exact=True).click()
                wave = pending.value.json()
                assert wave["protocol"]["collection_protocol"]["protocol_version"] == "manual-web-v1"
                assert wave["estimate"]["answer_calls"] == wave["estimate"]["search_calls"] == 0
                assert wave["estimate"]["judge_calls"] == 1
                page.screenshot(path=OUTPUT / "02-manual-estimate-1440.png", full_page=True)
                with page.expect_response(lambda response: response.url.endswith(f"/api/projects/1/waves/{wave['id']}/runs")
                                          and response.request.method == "POST") as pending:
                    wizard.get_by_role("button", name="创建人工采集 Run", exact=True).click()
                run = pending.value.json()["run"]
                page.get_by_text("人工采集与证据复核", exact=True).wait_for()
                answer_row = page.locator(f"[data-answer-id]").first
                answer_id = int(answer_row.get_attribute("data-answer-id"))
                previous_form = page.locator(".collection-form").element_handle()
                answer_row.click()
                page.wait_for_function("node => !node.isConnected", arg=previous_form)
                page.get_by_label("实际回答全文").wait_for()
                assert f"answer={answer_id}" in page.url
                page.get_by_label("实际回答全文").fill("GeoPulse 适合需要自托管和证据审计的团队。")
                page.get_by_label("实际页面 URL").fill(PRODUCT_URL + "/conversation/browser")
                page.get_by_label("观察时间（含 offset）").fill("2026-11-07T10:00:00+00:00")
                page.get_by_label("IANA 时区").fill("UTC")
                page.get_by_label("检索状态").select_option("off")
                page.get_by_label("草稿状态").select_option("review_pending")
                page.get_by_label("采集备注").fill("真实 Chrome 人工验收夹具，不代表消费者平台 live 验收。")
                page.get_by_role("button", name="添加页面引用", exact=True).click()
                page.get_by_label("URL", exact=True).fill("https://docs.example.test/geopulse")
                page.get_by_label("标题", exact=True).fill("人工看到的引用卡片")
                page.get_by_label("卡片文本", exact=True).fill("GeoPulse 证据审计")
                actual_draft_value = page.get_by_label("实际回答全文").input_value()
                assert actual_draft_value == "GeoPulse 适合需要自托管和证据审计的团队。", repr(actual_draft_value)
                with page.expect_response(lambda response: response.url.endswith(f"/answers/{answer_id}/collection/draft")
                                          and response.request.method == "PUT") as pending:
                    page.get_by_role("button", name="保存草稿", exact=True).click()
                saved = pending.value.json()
                assert saved["status"] == "review_pending"
                persisted = call(page, "get", f"/api/projects/1/answers/{answer_id}/collection")
                assert "GeoPulse 适合" in (persisted["draft_text"] or ""), {"saved": saved, "persisted": persisted, "url": page.url}
                page.reload(wait_until="networkidle")
                page.wait_for_function("() => [...document.querySelectorAll('textarea')].some(node => node.value.includes('GeoPulse 适合'))")
                assert "GeoPulse" in page.get_by_label("实际回答全文").input_value()
                page.get_by_label("选择文件").set_input_files(str(evidence_path))
                with page.expect_response(lambda response: f"/answers/{answer_id}/attachments" in response.url
                                          and response.request.method == "POST") as pending:
                    page.get_by_role("button", name="保存草稿并上传证据", exact=True).click()
                assert pending.value.status == 200, pending.value.status
                collection = call(page, "get", f"/api/projects/1/answers/{answer_id}/collection")
                attachment = next(item for item in collection["attachments"] if item["filename"] == "browser-evidence.png")
                assert attachment["sha256"] == hashlib.sha256(PNG).hexdigest()
                page.get_by_text("browser-evidence.png", exact=True).wait_for()
                assert_no_overflow(page, "collection desktop")
                page.screenshot(path=OUTPUT / "03-collection-draft-1440.png", full_page=True)
                for width, height in ((768, 1024), (390, 844)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(300)
                    assert_no_overflow(page, f"collection {width}")
                    page.screenshot(path=OUTPUT / f"03-collection-draft-{width}.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})

                page.get_by_role("button", name="核对并正式提交", exact=True).click()
                confirmation = page.get_by_role("dialog", name="正式提交人工采集", exact=True)
                with page.expect_response(lambda response: response.url.endswith(f"/answers/{answer_id}/collection/submit")
                                          and response.request.method == "POST") as pending:
                    confirmation.get_by_role("button", name="正式提交并进入判定", exact=True).click()
                assert pending.value.status == 200
                submitted = call(page, "get", f"/api/projects/1/answers/{answer_id}/collection")
                assert submitted["answer_status"] == "judging"
                worker = Worker(1)
                worker.start()
                try:
                    for _ in range(300):
                        with connect() as conn:
                            current = one(conn, "SELECT status FROM runs WHERE id=?", (run["id"],))
                        if current["status"] in ("done", "partial", "failed"):
                            break
                        time.sleep(0.05)
                finally:
                    worker.stop()
                assert current["status"] == "done", current
                page.reload(wait_until="networkidle")
                page.get_by_text("人工 Consumer Web 采集事实", exact=True).wait_for()
                page.get_by_role("region", name="原始回答全文", exact=True).wait_for()
                assert page.get_by_role("button", name="核对并正式提交", exact=True).count() == 0
                evidence_response = page.request.get(f"{base}/api/projects/1/attachments/{attachment['id']}")
                assert evidence_response.status == 200 and evidence_response.body() == PNG
                assert evidence_response.headers["x-content-sha256"] == attachment["sha256"]
                with page.expect_download() as pending_download:
                    page.get_by_role("button", name="下载", exact=True).click()
                download = pending_download.value
                downloaded_path = download.path()
                assert Path(downloaded_path).read_bytes() == PNG
                page.screenshot(path=OUTPUT / "04-collection-completed-1440.png", full_page=True)

                detail = call(page, "get", f"/api/projects/1/answers/{answer_id}")
                assert detail["valid_sample"] == 1 and detail["usage"] == {}
                assert [attempt["kind"] for attempt in detail["call_attempts"]] == ["judge"]
                for observation in detail["observations"]:
                    panel = page.locator(".observation").filter(has_text=observation["name"])
                    panel.get_by_role("button", name="新增人工修订", exact=True).click()
                    revision = page.get_by_role("dialog", name="人工修订实体判定", exact=True)
                    revision.get_by_label("修订理由").fill("人工 Web 浏览器验收仲裁")
                    revision.get_by_label("以管理员仲裁结论提交").check()
                    with page.expect_response(lambda response: "/revisions" in response.url
                                              and response.request.method == "POST") as pending:
                        revision.get_by_role("button", name="保存新 Revision", exact=True).click()
                    assert pending.value.status == 200, pending.value.text()
                    page.get_by_text("人工 Consumer Web 采集事实", exact=True).wait_for()

                page.evaluate("ids => { location.hash = `#/measure?wave=${ids.wave}&run=${ids.run}`; }",
                              {"wave": wave["id"], "run": run["id"]})
                page.get_by_role("button", name="指定为正式 Run", exact=True).wait_for()
                page.get_by_role("button", name="指定为正式 Run", exact=True).click()
                with page.expect_response(lambda response: response.url.endswith(f"/waves/{wave['id']}/official")
                                          and response.request.method == "POST") as pending:
                    page.get_by_role("dialog", name="指定正式 Run", exact=True).get_by_role(
                        "button", name="指定为正式 Run", exact=True).click()
                assert pending.value.status == 200

                reports = ReportsPage(page)
                reports.open_delivery(wave["id"])
                report = reports.create_snapshot(wave["id"])
                page.get_by_text("自动发布闸门已通过；仍需管理员逐步审批", exact=True).wait_for()
                client_html = page.request.get(
                    f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=html")
                assert client_html.status == 200
                assert "人工 Consumer Web" in client_html.text() and "人工记录的页面引用" in client_html.text()
                assert "内部成本与质量" not in client_html.text()
                premature_pdf = page.request.get(
                    f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=pdf")
                assert premature_pdf.status == 409
                for status in ("数据已核验", "策略已复核", "客户版已批准"):
                    page.get_by_role("button", name=f"推进到{status}", exact=True).click()
                    with page.expect_response(lambda response: response.url.endswith(f"/reports/{report['id']}/status")
                                              and response.request.method == "POST") as pending:
                        page.get_by_role("dialog").get_by_role("button", name="确认推进", exact=True).click()
                    assert pending.value.status == 200, pending.value.text()
                    page.locator(".report-sheet h2").filter(has_text=status).wait_for()
                pdf = page.request.get(f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=pdf")
                assert pdf.status == 200 and pdf.body().startswith(b"%PDF-")
                assert pdf.headers["x-content-sha256"] == hashlib.sha256(pdf.body()).hexdigest()
                page.screenshot(path=OUTPUT / "05-report-approved-1440.png", full_page=True)

                page.evaluate("wave => { location.hash = `#/measure?wave=${wave}`; }", wave["id"])
                page.get_by_role("button", name="创建人工采集 Run", exact=True).first.click()
                with page.expect_response(lambda response: response.url.endswith(f"/waves/{wave['id']}/runs")
                                          and response.request.method == "POST") as pending:
                    page.get_by_role("dialog", name="确认创建人工采集 Run", exact=True).get_by_role(
                        "button", name="创建并前往人工采集", exact=True).click()
                failed_run = pending.value.json()["run"]
                page.get_by_text("人工采集与证据复核", exact=True).wait_for()
                failed_answer = int(page.locator("[data-answer-id]").first.get_attribute("data-answer-id"))
                page.locator("[data-answer-id]").first.click()
                page.get_by_text("无法完成采集？登记失败", exact=True).click()
                page.get_by_label("失败类型").select_option("captcha")
                page.get_by_label("失败说明").fill("浏览器夹具模拟验证码，未形成有效回答")
                page.get_by_role("button", name="保存草稿并登记失败", exact=True).click()
                with page.expect_response(lambda response: response.url.endswith(f"/answers/{failed_answer}/collection/fail")
                                          and response.request.method == "POST") as pending:
                    page.get_by_role("dialog", name="登记人工采集失败", exact=True).get_by_role(
                        "button", name="登记失败", exact=True).click()
                assert pending.value.status == 200
                page.get_by_role("heading", name="采集失败：captcha", exact=True).wait_for()
                failed_metrics = call(page, "get", f"/api/projects/1/runs/{failed_run['id']}/metrics")
                assert failed_metrics["quality"]["valid_samples"] == 0
                with connect() as conn:
                    failed_row = one(conn, "SELECT valid_sample,raw_text FROM answers WHERE id=?", (failed_answer,))
                    assert failed_row["valid_sample"] == 0 and failed_row["raw_text"] is None
                page.set_viewport_size({"width": 390, "height": 844})
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(300)
                assert_no_overflow(page, "failed collection mobile")
                page.screenshot(path=OUTPUT / "06-collection-failed-390.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})

                role_pages = []
                for role in ("viewer", "reviewer"):
                    email = f"{role}-manual@browser.local"
                    password = f"{role}-browser-password"
                    user = call(page, "post", "/api/users", {"email": email, "password": password})
                    call(page, "post", "/api/projects/1/memberships", {"user_id": user["id"], "role": role})
                    role_context = browser.new_context(viewport={"width": 1440, "height": 1000})
                    role_context.route("**/*", guard)
                    role_page = role_context.new_page()
                    role_page.on("pageerror", lambda error: errors.append(f"role pageerror: {error.stack or error}"))
                    login(role_page, base, email, password)
                    role_page.evaluate("ids => { location.hash = `#/review?run=${ids.run}&answer=${ids.answer}&review=all`; }",
                                       {"run": run["id"], "answer": answer_id})
                    role_page.get_by_text("人工 Consumer Web 采集事实", exact=True).wait_for()
                    assert role_page.get_by_label("实际回答全文").count() == 0
                    assert role_page.get_by_role("button", name="下载", exact=True).count() == 0
                    assert role_page.get_by_role("button", name="新增人工修订", exact=True).count() == 0
                    role_page.get_by_text("原文不可见", exact=True).wait_for()
                    role_page.screenshot(path=OUTPUT / f"07-{role}-readonly-1440.png", full_page=True)
                    role_page.set_viewport_size({"width": 390, "height": 844})
                    role_page.evaluate("window.scrollTo(0, 0)")
                    role_page.wait_for_timeout(300)
                    assert_no_overflow(role_page, f"{role} readonly mobile")
                    role_page.screenshot(path=OUTPUT / f"07-{role}-readonly-390.png", full_page=True)
                    role_pages.append(role)
                    role_context.close()

                assert not errors, "\n".join(errors)
                assert not external, f"unexpected external browser requests: {external}"
                print(json.dumps({"status": "passed", "target_id": target["id"], "wave_id": wave["id"],
                                  "run_id": run["id"], "answer_id": answer_id, "report_id": report["id"],
                                  "failed_run_id": failed_run["id"], "roles": role_pages,
                                  "viewports": [1440, 768, 390], "external_requests": 0,
                                  "pdf_sha256": hashlib.sha256(pdf.body()).hexdigest()}, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    main()
