#!/usr/bin/env python3
"""Real-Chrome acceptance for the versioned intervention evidence chain."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from browser_smoke import PASSWORD, seed_official_run, wait_server
from browser_support import ReportsPage, call

OUTPUT = ROOT / "test-results" / "browser-interventions"


def create_gap(page, baseline_run_id):
    answers = call(page, "get", f"/api/projects/1/runs/{baseline_run_id}/answers")["items"]
    answer = call(page, "get", f"/api/projects/1/answers/{answers[0]['id']}")
    primary = next(item for item in answer["observations"] if item["role"] == "primary")
    competitor = next(item for item in answer["observations"] if item["role"] == "competitor")
    for observation, payload in (
        (primary, {"entity_status": "confirmed", "mentioned": False, "depth": "absent", "sentiment": "unknown", "evidence": ""}),
        (competitor, {"entity_status": "confirmed", "mentioned": True, "depth": "recommended", "sentiment": "positive", "evidence": answer["raw_text"]}),
    ):
        call(page, "post", f"/api/projects/1/answers/{answer['id']}/observations/{observation['id']}/revisions", {
            **payload, "top_choice": observation["role"] == "competitor", "reason": "离线 Intervention 浏览器夹具", "arbitrate": True,
        })
    return answer["id"]


def assert_drawer_layout(page, width, height, filename):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(150)
    dialog = page.get_by_role("dialog", name=re.compile(r"^Intervention #"))
    dialog.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{width}px horizontal overflow"
    bounds = dialog.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1
    dialog.evaluate("node => { node.scrollTop = 0; }")
    page.wait_for_function("() => !document.getElementById('toast').classList.contains('show')")
    page.wait_for_timeout(200)
    page.screenshot(path=OUTPUT / filename)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-intervention-browser-") as temporary:
        temp = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "GEOPULSE_DB": str(temp / "browser.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
               "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
               "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_ADMIN_EMAIL": "admin@browser.local",
               "GEOPULSE_ADMIN_PASSWORD": PASSWORD, "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_PORT": str(port)}
        os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
        baseline_wave, baseline_run = seed_official_run()[0]
        log = (temp / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None, headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, timezone_id="America/New_York")
                errors, external = [], []
                base = f"http://127.0.0.1:{port}"
                page.on("pageerror", lambda error: errors.append(f"pageerror: {error.stack or error}"))
                page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
                page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http://", "https://")) and not request.url.startswith(base) else None)
                page.goto(base, wait_until="networkidle")
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.wait_for_selector(".stage-panel")
                errors.clear()

                baseline_answer_id = create_gap(page, baseline_run)
                waves = call(page, "get", "/api/projects/1/waves")["items"]
                target = next(wave for wave in waves if wave["id"] != baseline_wave and wave["official_run_id"])
                source = call(page, "get", f"/api/projects/1/waves/{target['id']}")
                extra_targets = []
                for suffix in ("D14", "D28"):
                    extra = call(page, "post", "/api/projects/1/waves", {
                        "prompt_set_id": source["protocol"]["prompt_set_id"], "label": f"Intervention {suffix}",
                        "engine_ids": source["protocol"]["engine_ids"], "repeats": source["protocol"]["repeats"],
                        "use_judge": source["protocol"]["use_judge"],
                    })
                    extra_targets.append(extra["id"])

                page.locator("#main-nav a[href='#/opportunities']").click()
                page.get_by_role("button", name="从正式 Run 发现候选", exact=True).click()
                page.get_by_label("正式测量", exact=True).select_option(str(baseline_wave))
                page.get_by_role("button", name="生成候选", exact=True).click()
                page.get_by_text("生成 1 个候选", exact=True).wait_for()
                page.get_by_role("button", name="审核适用性", exact=True).click()
                page.get_by_label("审核说明", exact=True).fill("离线浏览器确认 Intervention 适用性")
                page.get_by_role("button", name="保存管理员决定", exact=True).click()
                page.get_by_role("tab", name="已确认机会 (1)").click()
                page.get_by_role("button", name="创建 Action", exact=True).click()
                page.get_by_label("Action 标题", exact=True).fill("Intervention 离线验收事实页")
                page.get_by_label("负责人", exact=True).fill("交付负责人")
                page.get_by_label("目标 URL / 平台", exact=True).fill("https://example.com/intervention-owned")
                page.get_by_role("button", name="创建 Action 草稿", exact=True).click()
                drawer = page.get_by_role("dialog", name=re.compile(r"^Intervention #"))
                drawer.wait_for()
                assert "action=" in page.url
                action_id = int(page.url.split("action=")[1].split("&")[0])

                drawer.get_by_role("button", name="编辑 Brief", exact=True).click()
                brief_dialog = page.get_by_role("dialog", name=re.compile(r"^Brief v"))
                selected = brief_dialog.get_by_label("基线 Answer 证据（可多选）", exact=True).first.input_value()
                assert selected == str(baseline_answer_id)
                brief_dialog.get_by_role("button", name="添加事实主张", exact=True).click()
                brief_dialog.locator(".claim-editor .inline-panel").last.get_by_label("事实主张", exact=True).fill("这条离线事实尚未核实")
                brief_dialog.get_by_role("button", name="保存 Brief", exact=True).click()
                drawer.get_by_role("button", name="提交审核", exact=True).click()
                drawer.get_by_role("button", name="批准行动", exact=True).click()
                page.get_by_text("Brief 仍有待确认主张，不能审批", exact=True).wait_for()
                errors.clear()  # the pending-claim approval rejection is an expected 409 contract check
                drawer.get_by_role("button", name="编辑 Brief", exact=True).click()
                brief_dialog.locator(".claim-editor .inline-panel").last.get_by_role("button", name="移除主张", exact=True).click()
                brief_dialog.get_by_role("button", name="保存 Brief", exact=True).click()
                drawer.get_by_role("button", name="批准行动", exact=True).click()
                drawer.get_by_role("button", name="登记真实发布", exact=True).wait_for()

                drawer.get_by_role("button", name="新增内容资产", exact=True).click()
                asset_dialog = page.get_by_role("dialog", name="新增内容资产", exact=True)
                asset_dialog.get_by_label("资产标题", exact=True).fill("合作渠道 FAQ")
                asset_dialog.get_by_label("资产类型", exact=True).select_option("faq")
                asset_dialog.get_by_label("内容摘要", exact=True).fill("只保存离线内容摘要，不复制原始回答")
                asset_dialog.get_by_role("button", name="创建 Asset 草稿", exact=True).click()
                faq = drawer.locator(".record-row").filter(has_text="合作渠道 FAQ")
                faq.get_by_role("button", name="审批 Asset", exact=True).click()
                faq.get_by_text("已批准", exact=False).wait_for()

                drawer.get_by_role("button", name="登记真实发布", exact=True).click()
                publication = page.get_by_role("dialog", name="登记真实发布", exact=True)
                published_at = publication.get_by_label("实际发布时间（项目时区）", exact=True)
                default_age = page.evaluate("""async value => {
                  const {fromDateTimeLocal} = await import('/static/datetime.js');
                  return Date.now() - new Date(fromDateTimeLocal(value, 'Asia/Shanghai')).getTime();
                }""", published_at.input_value())
                assert abs(default_age) < 120000, "Publication default does not use the project timezone"
                published_at.fill("2026-11-08T09:05")
                publication.get_by_label("内部备注", exact=True).fill("内部首条发布备注")
                publication.get_by_role("button", name="确认已发布并登记事件", exact=True).click()
                try:
                    publication.wait_for(state="detached", timeout=5000)
                except Exception as error:
                    raise RuntimeError(f"Publication diagnostics: {publication.inner_text()}") from error
                drawer.get_by_role("button", name="登记渠道发布", exact=True).click()
                publication.get_by_label("内容资产", exact=True).select_option(label="合作渠道 FAQ · v1")
                publication.get_by_label("渠道", exact=True).fill("partner")
                publication.get_by_label("媒体 / 站点", exact=True).fill("离线合作媒体")
                publication.get_by_label("实际发布 URL", exact=True).fill("https://example.com/intervention-partner")
                publication.get_by_label("商业关系", exact=True).select_option("paid")
                publication.get_by_label("实际成本", exact=True).fill("12.5")
                publication.get_by_label("币种", exact=True).fill("CNY")
                publication.get_by_label("内部备注", exact=True).fill("内部付费渠道备注")
                publication.get_by_role("button", name="确认已发布并登记事件", exact=True).click()
                drawer.get_by_text("12.5 CNY", exact=False).wait_for()
                published_detail = call(page, "get", f"/api/projects/1/actions/{action_id}")
                assert len(published_detail["publications"]) == 2
                first_publication = next(row for row in published_detail["publications"] if row["notes"] == "内部首条发布备注")
                assert datetime.fromisoformat(first_publication["published_at"].replace("Z", "+00:00")) == datetime(2026, 11, 8, 1, 5, tzinfo=timezone.utc)
                assert published_detail["publications"][1]["notes"] == "内部付费渠道备注"

                drawer.get_by_role("button", name="安排 D7/D14/D28 复测", exact=True).click()
                rounds_dialog = page.get_by_role("dialog", name="安排 cohort 复测", exact=True)
                for days, target_id in zip((7, 14, 28), [target["id"], *extra_targets]):
                    rounds_dialog.get_by_label(f"D{days} 目标 Wave", exact=True).select_option(str(target_id))
                rounds_dialog.get_by_role("button", name="创建 D7/D14/D28 节点", exact=True).click()
                page.get_by_text("D7/D14/D28 复测节点已创建", exact=True).wait_for()
                d7 = drawer.locator(".round-node").filter(has_text="D7")
                d7.get_by_role("button", name="评估本轮", exact=True).click()
                page.get_by_label("评估依据", exact=True).fill("离线浏览器冻结基线与目标正式 Run；小样本不得输出改善")
                page.get_by_role("button", name="冻结本轮评估", exact=True).click()
                page.get_by_text("本轮评估已冻结", exact=True).wait_for()
                detail = call(page, "get", f"/api/projects/1/actions/{action_id}")
                assessed = next(row for row in detail["rounds"] if row["offset_days"] == 7)
                assert assessed["status"] == "insufficient_evidence" and assessed["observed_change"] == "unknown"
                assert assessed["baseline_run_id"] == baseline_run and assessed["comparison_hash"]
                assert assessed["attribution_status"] == "not_attributable"
                assert "per_asset" not in json.dumps(detail) and "asset_delta" not in json.dumps(detail)

                assert_drawer_layout(page, 1440, 1000, "01-intervention-desktop.png")
                assert_drawer_layout(page, 1024, 768, "01b-intervention-small-desktop.png")
                assert_drawer_layout(page, 820, 1180, "01c-intervention-wide-tablet.png")
                assert_drawer_layout(page, 768, 1024, "02-intervention-tablet.png")
                assert_drawer_layout(page, 390, 844, "03-intervention-mobile.png")
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                page.keyboard.press("Escape")
                assert drawer.count() == 0
                page.get_by_role("button", name="Intervention 离线验收事实页", exact=True).click()
                drawer.wait_for()
                deep_link = page.url
                page.reload(wait_until="networkidle")
                drawer.wait_for()
                assert page.url == deep_link
                drawer.locator(".evidence-ref").first.click()
                page.get_by_role("heading", name="证据复核", exact=True).wait_for()
                assert page.get_by_role("dialog", name=re.compile(r"^Intervention #")).count() == 0
                assert not page.locator("#app-shell").evaluate("node => node.inert")
                assert page.evaluate("document.body.style.overflow") != "hidden"
                assert page.url.startswith(f"{base}/#/review?answer=") and "action=" not in page.url
                page.set_viewport_size({"width": 1440, "height": 1000})

                reports = ReportsPage(page)
                reports.open_delivery(wave_id=target["id"])
                report = reports.create_snapshot(target["id"])
                page.get_by_text("客户决策摘要", exact=True).first.wait_for()
                assert page.get_by_text("唯一下一轮建议：", exact=True).count() > 0
                for status in ("data_checked", "strategy_reviewed", "client_approved"):
                    call(page, "post", f"/api/projects/1/reports/{report['id']}/status", {"status": status, "reason": "离线 Intervention 报告验收"})
                client_html = page.request.get(f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=html")
                internal_html = page.request.get(f"{base}/api/projects/1/reports/{report['id']}/export?variant=internal&format=html")
                assert client_html.status == internal_html.status == 200
                assert "客户决策摘要" in client_html.text() and "证据不足" in client_html.text()
                assert "客户官网" in client_html.text() and "合作渠道" in client_html.text()
                assert "owned_site" not in client_html.text()
                assert "12.5" not in client_html.text() and "内部付费渠道备注" not in client_html.text()
                assert "12.5" in internal_html.text() and "内部付费渠道备注" in internal_html.text()
                pdf = page.request.get(f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=pdf")
                assert pdf.status == 200 and pdf.body().startswith(b"%PDF")
                (OUTPUT / "intervention-client.pdf").write_bytes(pdf.body())
                page.wait_for_function("() => !document.getElementById('toast').classList.contains('show')")
                page.wait_for_timeout(200)
                page.screenshot(path=OUTPUT / "04-report-decision.png", full_page=True)

                role_results = []
                for role in ("viewer", "reviewer"):
                    email, password = f"intervention-{role}@browser.local", f"{role}-browser-password"
                    user = call(page, "post", "/api/users", {"email": email, "password": password})
                    call(page, "post", "/api/projects/1/memberships", {"user_id": user["id"], "role": role})
                    role_page = browser.new_page(viewport={"width": 390, "height": 844})
                    role_errors = []
                    role_page.on("pageerror", lambda error, caught=role_errors: caught.append(str(error)))
                    role_page.goto(base, wait_until="networkidle")
                    role_page.get_by_label("邮箱").fill(email)
                    role_page.get_by_label("密码").fill(password)
                    role_page.get_by_role("button", name="登录", exact=True).click()
                    role_page.wait_for_selector(".stage-panel")
                    role_page.evaluate("action => { location.hash = `#/opportunities?tab=remeasure&action=${action}`; }", action_id)
                    role_drawer = role_page.get_by_role("dialog", name=re.compile(r"^Intervention #"))
                    role_drawer.wait_for()
                    assert role_page.get_by_role("button", name="编辑 Brief", exact=True).count() == 0
                    assert role_page.get_by_role("button", name="登记渠道发布", exact=True).count() == 0
                    assert role_page.get_by_role("button", name="评估本轮", exact=True).count() == 0
                    assert "12.5" not in role_drawer.inner_text() and "内部付费渠道备注" not in role_drawer.inner_text()
                    redacted = role_page.request.get(f"{base}/api/projects/1/actions/{action_id}").json()
                    assert "evidence_json" not in redacted["opportunity"] and "score_json" not in redacted["opportunity"]
                    assert all("cost" not in row and "notes" not in row for row in redacted["publications"])
                    assert all("evidence_refs" not in claim for brief in redacted["briefs"] for claim in brief["claims"])
                    assert role_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    role_page.wait_for_timeout(200)
                    role_page.screenshot(path=OUTPUT / f"05-{role}-mobile.png")
                    role_page.close()
                    assert not role_errors, role_errors
                    role_results.append(role)

                browser.close()
                assert not external, external
                assert not errors, errors
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            log.close()
    print(json.dumps({"status": "passed", "screenshots": str(OUTPUT), "roles": role_results,
                      "assets": 2, "publications": 2, "rounds": [7, 14, 28],
                      "assessment": "insufficient_evidence", "pdf": "intervention-client.pdf",
                      "viewports": [1440, 768, 390], "external_requests": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
