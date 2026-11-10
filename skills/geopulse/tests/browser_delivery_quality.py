#!/usr/bin/env python3
"""Offline Chrome path from a disabled-Judge Run to an approved business handoff."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from browser_smoke import PASSWORD, wait_server
from browser_support import ReportsPage, call

OUTPUT = ROOT / "test-results" / "browser-delivery-quality"


def wait_for_status(table: str, row_id: int, terminal: tuple[str, ...]) -> str:
    from backend.app.db import connect, one
    from backend.app.services.measurement import Worker

    worker = Worker(2)
    worker.start()
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with connect() as conn:
                status = one(conn, f"SELECT status FROM {table} WHERE id=?", (row_id,))["status"]
            if status in terminal:
                return status
            time.sleep(0.05)
        raise AssertionError(f"{table}#{row_id} did not finish: {status}")
    finally:
        worker.stop()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-delivery-browser-") as temporary:
        temp = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "GEOPULSE_DB": str(temp / "browser.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
               "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
               "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_ADMIN_EMAIL": "admin@browser.local",
               "GEOPULSE_ADMIN_PASSWORD": PASSWORD, "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_PORT": str(port)}
        os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
        from backend.app.migrations import initialize
        initialize()
        log = (temp / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None,
                                                      headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors, external = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: external.append(request.url)
                        if not request.url.startswith(f"http://127.0.0.1:{port}") and not request.url.startswith("data:") else None)
                base = f"http://127.0.0.1:{port}"
                page.goto(base, wait_until="networkidle")
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.wait_for_selector(".stage-panel")

                # A Demo Run deliberately omits Judge. No Provider request leaves this host.
                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_role("button", name="新建测量方案", exact=True).click()
                page.get_by_label("Wave 名称", exact=True).fill("离线补判交付 Wave")
                engine_check = page.get_by_label("demo · demo", exact=False)
                if not engine_check.is_checked():
                    engine_check.check()
                assert engine_check.is_checked()
                page.get_by_label("生产回答使用全量结构化 judge", exact=False).uncheck()
                page.get_by_role("button", name="创建方案并查看预估", exact=True).click()
                try:
                    page.get_by_role("heading", name="测量准备单", exact=True).wait_for(timeout=5000)
                except Exception as error:
                    raise AssertionError(f"准备单未打开：{page.get_by_role('dialog').inner_text()}") from error
                page.get_by_text("调用与费用预估", exact=True).wait_for()
                page.get_by_role("button", name="仅保存方案", exact=True).click()
                wave = call(page, "get", "/api/projects/1/waves")["items"][0]
                assert wave["protocol"]["judge_mode"] == "disabled"
                page.get_by_role("button", name="确认并创建 Run", exact=True).click()
                page.get_by_role("button", name="确认并进入队列", exact=True).click()
                page.get_by_text("Run 已进入持久队列", exact=True).wait_for()
                run_id = call(page, "get", f"/api/projects/1/waves/{wave['id']}")["runs"][0]["id"]
                assert wait_for_status("runs", run_id, ("done", "partial", "failed")) == "done"

                page.reload(wait_until="networkidle")
                page.get_by_text("唯一下一步：创建补判批次", exact=True).wait_for()
                page.get_by_role("button", name="创建补判批次", exact=True).click()
                dialog = page.get_by_role("dialog", name=f"Judge-only 补判 · Run #{run_id}", exact=True)
                dialog.wait_for()
                page.wait_for_timeout(150)
                assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")
                page.keyboard.press("Escape")
                dialog.wait_for(state="hidden")
                page.get_by_role("button", name="创建补判批次", exact=True).click()
                dialog = page.get_by_role("dialog", name=f"Judge-only 补判 · Run #{run_id}", exact=True)
                dialog.get_by_label("补判范围", exact=True).select_option("selected")
                dialog.locator("input[type=checkbox]").first.check()
                dialog.get_by_label("补判范围", exact=True).select_option("all")
                page.screenshot(path=OUTPUT / "01-judge-batch-dialog.png", full_page=True)
                dialog.get_by_role("button", name="检查预估并创建补判批次", exact=True).click()
                page.get_by_text("已进入队列；不会重采回答", exact=False).wait_for()
                batch = call(page, "get", f"/api/projects/1/runs/{run_id}/judge-batches")["items"][0]
                assert batch["estimate"]["answer_calls"] == batch["estimate"]["search_calls"] == 0
                assert batch["estimate"]["judge_calls"] == len(wave["protocol"]["prompt_item_ids"]) * wave["protocol"]["repeats"]
                assert wait_for_status("judge_batches", batch["id"], ("done", "partial", "failed")) == "done"

                # Add one explicit human arbitration revision; the raw answer remains immutable.
                answer = call(page, "get", f"/api/projects/1/runs/{run_id}/answers")["items"][0]
                detail = call(page, "get", f"/api/projects/1/answers/{answer['id']}")
                observation = next(item for item in detail["observations"]
                                   if item["mentioned"] and item["evidence"] and item["evidence"] in detail["raw_text"])
                call(page, "post", f"/api/projects/1/answers/{answer['id']}/observations/{observation['id']}/revisions", {
                    "entity_status": "confirmed", "mentioned": True, "depth": "described", "sentiment": "neutral",
                    "top_choice": False, "evidence": observation["evidence"], "reason": "离线 Chrome 人工复核",
                    "arbitrate": True})
                page.reload(wait_until="networkidle")
                page.get_by_text("唯一下一步：指定正式 Run", exact=True).wait_for()
                page.locator("summary").filter(has_text="判定质量、实际模型与补判记录").click()
                page.get_by_text("人工 revision 1", exact=False).wait_for()
                page.get_by_text("补判完成：demo", exact=False).wait_for()
                page.screenshot(path=OUTPUT / "02-quality-ready-desktop.png", full_page=True)
                page.get_by_role("button", name="指定正式 Run", exact=True).first.click()
                page.get_by_role("dialog", name="指定正式 Run", exact=True).get_by_role("button", name="指定为正式 Run", exact=True).click()
                page.get_by_text("正式 Run 已指定", exact=True).wait_for()

                handoff = call(page, "get", f"/api/projects/1/runs/{run_id}/handoff")
                assert handoff["next_action"]["kind"] == "generate_opportunities"
                page.get_by_role("link", name="发现候选机会", exact=True).click()
                page.wait_for_url(f"**/#/opportunities?wave={wave['id']}")
                page.get_by_role("heading", name="机会与行动", exact=True).wait_for()
                generated = call(page, "post", f"/api/projects/1/waves/{wave['id']}/opportunities/generate")
                for opportunity in generated["items"]:
                    call(page, "post", f"/api/projects/1/opportunities/{opportunity['id']}/review", {
                        "decision": "rejected", "reason": "离线交接路径：本轮不投入"})
                handoff = call(page, "get", f"/api/projects/1/runs/{run_id}/handoff")
                assert handoff["next_action"]["kind"] == "create_report"
                reports = ReportsPage(page)
                reports.open_delivery(wave_id=wave["id"])
                report = reports.create_snapshot(wave["id"])
                for label in ("推进到数据已核验", "推进到策略已复核", "推进到客户版已批准"):
                    page.get_by_role("button", name=label, exact=True).click()
                    page.get_by_role("button", name="确认推进", exact=True).click()
                    page.wait_for_timeout(250)
                page.get_by_text(f"报告 v{report['version']} · 客户版已批准", exact=True).wait_for()
                handoff = call(page, "get", f"/api/projects/1/runs/{run_id}/handoff")
                assert handoff["next_action"]["kind"] == "record_work_log_reminder"
                assert handoff["work_log"]["mode"] == "manual_reminder_only"
                client_html = page.request.get(
                    f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=html").text()
                assert "配置模型与实际返回模型" in client_html and "指标公式与分母附录" in client_html
                assert "client_confirmed" not in client_html and "system_prompt" not in client_html
                assert "内部成本与质量" not in client_html and "原始回答与判定" not in client_html

                call(page, "post", "/api/projects/1/work-logs", {
                    "hours": 0.5, "kind": "交付复核", "note": "人工登记，非自动计时", "work_date": "2026-11-10"})
                assert call(page, "get", f"/api/projects/1/runs/{run_id}/handoff")["next_action"]["kind"] == "close_or_analyze_wave"
                page.evaluate("wave => { location.hash = `#/measure?wave=${wave}`; }", wave["id"])
                page.get_by_role("button", name="标记 Wave 已分析", exact=True).click()
                page.get_by_role("dialog", name="标记 Wave 已分析", exact=True).get_by_role("button", name="确认标记", exact=True).click()
                page.get_by_text("本轮交接已完成", exact=False).wait_for()
                completed = call(page, "get", f"/api/projects/1/runs/{run_id}/handoff")
                assert completed["next_action"]["kind"] == "complete"
                assert completed["external_sync"]["automatic"] is False

                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("tab", name="设置与数据治理", exact=True).click()
                page.get_by_role("button", name="添加来源域名", exact=True).click()
                source_row = page.locator(".source-domain-row").last
                source_row.get_by_label("来源域名", exact=True).fill("Example.COM.")
                source_row.get_by_label("来源类别", exact=True).select_option("新闻")
                page.get_by_role("button", name="保存来源分类", exact=True).click()
                page.get_by_text("来源分类已保存；历史 Citation 未改写", exact=True).wait_for()
                project = call(page, "get", "/api/projects/1")
                assert project["settings"]["source_domains"]["example.com"] == "新闻"

                page.evaluate("wave => { location.hash = `#/measure?wave=${wave}`; }", wave["id"])
                page.get_by_text("本轮交接已完成", exact=False).wait_for()
                page.evaluate("() => { const toast = document.getElementById('toast'); toast.className = 'toast'; toast.replaceChildren(); }")
                for width, height, name in ((768, 1024, "tablet"), (390, 844, "mobile")):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(250)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=OUTPUT / f"03-handoff-{name}.png", full_page=True)
                assert not errors, errors
                assert not external, external
                print(json.dumps({"status": "passed", "wave_id": wave["id"], "run_id": run_id,
                                  "judge_batch_id": batch["id"], "report_id": report["id"],
                                  "next_action": completed["next_action"]["kind"], "viewports": [1440, 768, 390],
                                  "external_requests": len(external), "screenshots": str(OUTPUT)}, ensure_ascii=False, indent=2))
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    main()
