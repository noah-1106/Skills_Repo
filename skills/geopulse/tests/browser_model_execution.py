#!/usr/bin/env python3
"""Chrome verification for model parameters and independent Provider Judge."""
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
from browser_support import call

OUTPUT = ROOT / "test-results" / "browser-model-execution"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-model-browser-") as temporary:
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
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None, headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                external = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: external.append(request.url) if not request.url.startswith(f"http://127.0.0.1:{port}") and not request.url.startswith("data:") else None)
                base = f"http://127.0.0.1:{port}"
                page.goto(base, wait_until="networkidle")
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.wait_for_selector(".stage-panel")

                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("button", name="新增引擎", exact=True).click()
                page.get_by_label("配置名称", exact=True).fill("DeepSeek 离线协议配置")
                page.get_by_label("厂商 / 产品", exact=True).fill("DeepSeek")
                page.get_by_label("目标类型", exact=True).select_option("deepseek_search")
                assert page.get_by_label("测量模式", exact=True).input_value() == "search"
                page.get_by_label("模型 ID", exact=True).fill("offline-model")
                page.get_by_label("Base URL", exact=True).fill("https://api.deepseek.com/v1")
                page.get_by_label("API Key", exact=True).fill("offline-test-not-a-credential")
                page.get_by_text("模型能力声明", exact=True).click()
                capability_panel = page.locator("details").filter(has_text="模型能力声明")
                capability_panel.get_by_label("最大输出 tokens", exact=True).fill("4000")
                capability_panel.get_by_label("JSON response_format", exact=True).select_option("true")
                answer = page.locator("details.execution-fields").filter(has_text="回答默认参数")
                answer.locator("summary").click()
                answer.get_by_label("Temperature", exact=True).select_option("value")
                answer.get_by_label("Temperature 数值", exact=True).fill("0.3")
                answer.get_by_label("最大输出 tokens", exact=True).select_option("value")
                answer.get_by_label("最大输出 tokens 数值", exact=True).fill("650")
                judge = page.locator("details.execution-fields").filter(has_text="Judge 默认参数")
                judge.locator("summary").click()
                judge.get_by_label("最大输出 tokens", exact=True).select_option("value")
                judge.get_by_label("最大输出 tokens 数值", exact=True).fill("1200")
                page.screenshot(path=OUTPUT / "01-engine-parameters.png", full_page=True)
                page.get_by_role("button", name="保存测量目标", exact=True).click()
                page.get_by_text("引擎配置已保存，密钥未回显", exact=True).wait_for()
                engines = call(page, "get", "/api/projects/1/engines")["items"]
                configured = next(item for item in engines if item["name"] == "DeepSeek 离线协议配置")
                assert configured["kind"] == "deepseek_search" and configured["mode"] == "search"
                assert configured["answer_defaults"] == {"temperature": 0.3, "max_tokens": 650}
                assert configured["judge_defaults"] == {"max_tokens": 1200}
                assert configured["capabilities"]["max_output_tokens"] == 4000

                independent = call(page, "post", "/api/projects/1/engines", {
                    "name": "浏览器独立 Demo Judge", "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2", "mode": "memory"})
                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_role("button", name="新建测量方案", exact=True).click()
                page.get_by_label("Wave 名称", exact=True).fill("浏览器独立 Judge Wave")
                page.locator(".check-field label").filter(has_text="demo · demo").first.click()
                page.get_by_label("Judge 方式", exact=True).select_option("independent")
                page.get_by_label("独立 Judge 引擎（不能同时是回答引擎）", exact=True).select_option(str(independent["id"]))
                wizard_answer = page.locator("details.execution-fields").filter(has_text="回答参数（可选")
                wizard_answer.locator("summary").click()
                wizard_answer.get_by_label("Temperature", exact=True).select_option("null")
                wizard_answer.get_by_label("最大输出 tokens", exact=True).select_option("value")
                wizard_answer.get_by_label("最大输出 tokens 数值", exact=True).fill("600")
                wizard_judge = page.locator("details.execution-fields").filter(has_text="Judge 参数（可选")
                wizard_judge.locator("summary").click()
                wizard_judge.get_by_label("最大输出 tokens", exact=True).select_option("value")
                wizard_judge.get_by_label("最大输出 tokens 数值", exact=True).fill("1100")
                page.get_by_role("button", name="创建方案并查看预估", exact=True).click()
                page.get_by_text("调用与费用预估", exact=True).wait_for()
                assert page.get_by_role("cell", name="独立 Judge", exact=True).count() == 1
                page.get_by_role("button", name="仅保存方案", exact=True).click()
                page.get_by_text("浏览器独立 Judge Wave", exact=True).first.wait_for()
                waves = call(page, "get", "/api/projects/1/waves")["items"]
                wave = next(item for item in waves if item["label"] == "浏览器独立 Judge Wave")
                answer_id = wave["protocol"]["engine_ids"][0]
                execution = wave["protocol"]["answer_execution"][str(answer_id)]
                assert execution["temperature"] is None and execution["max_tokens"] == 600
                assert wave["protocol"]["judge_execution"][str(answer_id)]["max_tokens"] == 1100
                assert wave["protocol"]["judge_mode"] == "independent"
                page.locator("summary").filter(has_text="查看冻结执行参数").click()
                page.screenshot(path=OUTPUT / "02-independent-judge-wave.png", full_page=True)

                page.get_by_role("button", name="确认并创建 Run", exact=True).click()
                page.get_by_role("button", name="确认并进入队列", exact=True).click()
                page.get_by_text("Run 已进入持久队列", exact=True).wait_for()
                run_id = call(page, "get", f"/api/projects/1/waves/{wave['id']}")["runs"][0]["id"]
                from backend.app.db import connect, one
                from backend.app.services.measurement import Worker
                worker = Worker(1)
                worker.start()
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        with connect() as conn:
                            status = one(conn, "SELECT status FROM runs WHERE id=?", (run_id,))["status"]
                        if status in ("done", "partial", "failed"):
                            break
                        time.sleep(0.05)
                    assert status == "done", status
                finally:
                    worker.stop()
                with connect() as conn:
                    judge_attempt = one(conn, "SELECT * FROM call_attempts WHERE run_id=? AND kind='judge' LIMIT 1", (run_id,))
                    assert judge_attempt["engine_config_id"] == independent["id"]
                    assert json.loads(judge_attempt["request_params_json"])["max_tokens"] == 1100
                page.reload(wait_until="networkidle")
                page.get_by_text("独立 Judge：浏览器独立 Demo Judge", exact=False).first.wait_for()
                page.set_viewport_size({"width": 768, "height": 1024})
                page.wait_for_timeout(300)
                page.screenshot(path=OUTPUT / "03-independent-judge-tablet.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(300)
                page.screenshot(path=OUTPUT / "04-independent-judge-mobile.png", full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                assert not external, external
                print(json.dumps({"status": "passed", "wave_id": wave["id"], "run_id": run_id,
                                  "judge_engine_id": independent["id"], "deepseek_kind": configured["kind"],
                                  "viewports": [1440, 768, 390], "external_requests": len(external),
                                  "screenshots": str(OUTPUT)}, ensure_ascii=False, indent=2))
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
