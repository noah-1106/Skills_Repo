#!/usr/bin/env python3
"""Offline real-Chrome contracts for both authorized Consumer Web drivers."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from browser_support import ReportsPage, call

OUTPUT = ROOT / "test-results" / "browser-collector"
PASSWORD = "test-browser-password"
URLS = {"deepseek_web": "https://chat.deepseek.com/chat", "kimi_web": "https://www.kimi.com/chat"}
HOSTS = {"deepseek_web": "chat.deepseek.com", "kimi_web": "www.kimi.com"}
PROMPT = "哪些 GEO 工具适合证据审计？"


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


def login(page, base: str, email: str, password: str) -> None:
    page.goto(base, wait_until="networkidle")
    page.get_by_label("邮箱").fill(email)
    page.get_by_label("密码").fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    page.get_by_text("项目总览", exact=True).first.wait_for()


def assert_no_overflow(page, label: str) -> None:
    dimensions = page.evaluate("() => ({width: innerWidth, scroll: document.documentElement.scrollWidth})")
    assert dimensions["scroll"] <= dimensions["width"], f"{label} horizontal overflow: {dimensions}"


def fixture_html(driver_key: str, scenario: str, resumed: bool) -> str:
    deepseek = driver_key == "deepseek_web"
    name = "DeepSeek" if deepseek else "Kimi"
    composer = "" if scenario == "missing_composer" else (
        "<textarea aria-label='对话输入'></textarea>" if deepseek
        else "<textarea data-testid='chat-input' aria-label='对话输入'></textarea>")
    captcha = "<div class='captcha'>请完成安全验证</div>" if scenario == "captcha" else ""
    switches = "" if scenario == "missing_switches" else f"""
      <button aria-label='{'联网搜索' if deepseek else '联网'}' aria-pressed='false'
        onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') !== 'true')">联网</button>
      <button aria-label='{'深度思考' if deepseek else '深入思考'}' aria-pressed='false'
        onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') !== 'true')">思考</button>"""
    answer_class = "ds-markdown" if deepseek else "fixture-markdown"
    answer = "" if scenario == "blank" else f"{name} 离线回答：GeoPulse 适合证据审计。"
    initial_answer = (f"<div data-testid='assistant-message' class='{answer_class}'></div>" if scenario == "blank" else f"""<div data-testid='assistant-message' class='{answer_class}'>
        <p>{answer}</p><a href='https://docs.example.test/{driver_key}'>证据引用</a>
        <a href='javascript:alert(1)'>不采集的链接</a></div>""") if resumed else ""
    script = "" if resumed else f"""
      document.querySelector('[data-testid="send-button"]').addEventListener('click', () => {{
        const text = document.querySelector('textarea').value;
        fetch('/_submission', {{method: 'POST', body: text}});
        history.replaceState({{}}, '', '/conversation/{driver_key}-fixture');
        if ({json.dumps(scenario in ('empty', 'blank'))}) return;
        const stop = document.createElement('button');
        stop.dataset.testid = 'stop-generation'; stop.ariaLabel = '停止'; document.body.append(stop);
        setTimeout(() => {{
          stop.remove();
          const answer = document.createElement('div');
          answer.dataset.testid = 'assistant-message'; answer.className = '{answer_class}';
          answer.innerHTML = `<p>{name} 离线回答：GeoPulse 适合证据审计。</p>
            <a href="https://docs.example.test/{driver_key}">证据引用</a>
            <a href="javascript:alert(1)">不采集的链接</a>`;
          document.querySelector('#answers').append(answer);
        }}, 250);
      }});"""
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{name} 离线夹具</title></head>
      <body><main><h1>{name} 离线夹具</h1>{captcha}
      <button aria-label='{'新对话' if deepseek else '新会话'}'>新建</button>{switches}{composer}
      <button data-testid='send-button' aria-label='发送'>发送</button>
      <div id='answers'>{initial_answer}</div></main><script>{script}</script></body></html>"""


class OfflineCollectorWorker:
    """Route only authorized HTTPS origins to deterministic local HTML."""

    def __init__(self):
        from backend.app.services.browser_worker import BrowserWorker
        self.worker = BrowserWorker()
        self.scenarios = {"deepseek_web": "normal", "kimi_web": "normal"}
        self.submissions = {"deepseek_web": [], "kimi_web": []}
        self.unexpected = []
        self.playwright = None

    def launch(self, session):
        from backend.app.services import browser_sessions
        class SharedPlaywright:
            def stop(self):
                pass
        executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        options = {"headless": True, "viewport": {"width": 1280, "height": 900}, "accept_downloads": False}
        if Path(executable).is_file():
            options["executable_path"] = executable
        context = self.playwright.chromium.launch_persistent_context(
            str(browser_sessions.profile_path(session["profile_ref"])), **options)
        context.set_default_timeout(10000)
        return SharedPlaywright(), context

    def configure_context(self, context, driver_class):
        def serve(route):
            request = route.request
            parsed = urllib.parse.urlparse(request.url)
            driver_key = driver_class.key
            if parsed.scheme != "https" or parsed.hostname != HOSTS[driver_key]:
                self.unexpected.append(request.url)
                route.abort()
                return
            if parsed.path == "/_submission":
                self.submissions[driver_key].append(request.post_data or "")
                route.fulfill(status=200, content_type="application/json", body="{}")
                return
            if request.resource_type == "document":
                route.fulfill(status=200, content_type="text/html", body=fixture_html(
                    driver_key, self.scenarios[driver_key], parsed.path.startswith("/conversation/")))
                return
            route.fulfill(status=204, body="")
        context.route("**/*", serve)

    def install(self):
        from backend.app.services.browser_worker import BrowserWorker
        self.original = BrowserWorker.configure_context
        self.original_launch = BrowserWorker._launch
        BrowserWorker.configure_context = self.configure_context
        BrowserWorker._launch = self.launch

    def restore(self):
        from backend.app.services.browser_worker import BrowserWorker
        BrowserWorker.configure_context = self.original
        BrowserWorker._launch = self.original_launch


def finish_run(run_id: int) -> str:
    from backend.app.db import connect, one
    from backend.app.services.measurement import Worker
    worker = Worker(1)
    worker.start()
    try:
        current = None
        for _ in range(400):
            with connect() as conn:
                current = one(conn, "SELECT status FROM runs WHERE id=?", (run_id,))
            if current["status"] in ("done", "partial", "failed"):
                return current["status"]
            time.sleep(0.05)
        raise AssertionError(f"Run {run_id} did not finish: {current}")
    finally:
        worker.stop()


def run_one(worker, answer_id: int) -> None:
    from backend.app.db import connect, one
    claimed = worker._claim()
    assert claimed and claimed["answer_id"] == answer_id, claimed
    worker._run_job(answer_id, claimed["lease_owner"])
    with connect() as conn:
        collection = one(conn, """SELECT browser_phase,browser_phase_detail,failure_type,failure_detail
                                 FROM web_collections WHERE answer_id=?""", (answer_id,))
    assert collection["browser_phase"] == "completed", collection


def create_target_and_session(page, worker, name: str, vendor: str, driver_key: str) -> int:
    page.locator("#main-nav a[href='#/admin']").click()
    page.get_by_role("button", name="新增引擎", exact=True).click()
    dialog = page.get_by_role("dialog", name="新增引擎", exact=True)
    dialog.get_by_label("配置名称").fill(name)
    dialog.get_by_label("厂商 / 产品").fill(vendor)
    dialog.get_by_label("目标类型").select_option("manual_web")
    dialog.get_by_label("HTTPS 产品入口").fill(URLS[driver_key])
    dialog.get_by_label("测量模式").select_option("search")
    with page.expect_response(lambda response: response.url.endswith("/api/projects/1/engines")
                              and response.request.method == "POST") as pending:
        dialog.get_by_role("button", name="保存测量目标", exact=True).click()
    target = pending.value.json()
    page.get_by_text(name, exact=True).wait_for()
    row = page.locator("tbody tr").filter(has_text=name)
    row.get_by_role("button", name="管理浏览器连接", exact=True).click()
    connection = page.get_by_role("dialog", name=f"本机浏览器连接 · {name}", exact=True)
    connection.get_by_label("平台 Driver").select_option(driver_key)
    with page.expect_response(lambda response: response.url.endswith(f"/engines/{target['id']}/browser-sessions")
                              and response.request.method == "POST") as pending_session:
        connection.get_by_role("button", name="打开浏览器并连接", exact=True).click()
    session = pending_session.value.json()
    assert session["status"] == "pending" and "profile_ref" not in session
    connection.get_by_text("撤销连接", exact=True).wait_for()
    with page.expect_response(lambda response: response.url.endswith(f"/browser-sessions/{session['id']}/verify")
                              and response.request.method == "POST"):
        connection.get_by_role("button", name="我已完成登录，验证并保存", exact=True).click()
    worker._manage_login(session["id"])
    connection.get_by_text("浏览器会话可用", exact=True).wait_for(timeout=10000)
    page.screenshot(path=OUTPUT / f"session-{driver_key}-1440.png", full_page=True)
    connection.get_by_label("关闭对话框").click()
    return target["id"]


def create_browser_wave(page, target_name: str, prompt_set_id: int, driver_key: str):
    page.locator("#main-nav a[href='#/measure']").click()
    page.get_by_role("button", name="新建测量方案", exact=True).click()
    wizard = page.get_by_role("dialog", name="新建测量方案", exact=True)
    wizard.get_by_label("Wave 名称").fill(f"{driver_key} 授权浏览器离线验收")
    wizard.get_by_label("冻结问题集").select_option(str(prompt_set_id))
    wizard.get_by_label("采样轮次").select_option("1")
    wizard.locator(".check-field").filter(has_text=target_name).locator("input").check()
    wizard.get_by_label("采集方法").select_option("browser_assisted")
    assert wizard.get_by_label("浏览器 Driver").input_value() == driver_key
    assert wizard.get_by_label("会话策略").input_value() == "new"
    assert wizard.get_by_label("登录状态").input_value() == "logged_in"
    assert wizard.get_by_label("页面形态").is_disabled()
    assert "已验证" in wizard.locator(".emphasis").inner_text()
    with page.expect_response(lambda response: response.url.endswith("/api/projects/1/waves")
                              and response.request.method == "POST") as pending:
        wizard.get_by_role("button", name="创建方案并查看预估", exact=True).click()
    wave = pending.value.json()
    protocol = wave["protocol"]["collection_protocol"]
    assert protocol["collection_method"] == "browser_assisted" and protocol["browser_driver"] == driver_key
    assert protocol["protocol_version"] == "browser-web-v1"
    page.screenshot(path=OUTPUT / f"estimate-{driver_key}-1440.png", full_page=True)
    with page.expect_response(lambda response: response.url.endswith(f"/waves/{wave['id']}/runs")
                              and response.request.method == "POST") as pending_run:
        wizard.get_by_role("button", name="确认发送并创建 Run", exact=True).click()
    assert pending_run.value.request.post_data_json["confirm_browser"] is True
    run = pending_run.value.json()["run"]
    page.get_by_text("授权浏览器采集与证据", exact=True).wait_for()
    answer_id = int(page.locator("[data-answer-id]").first.get_attribute("data-answer-id"))
    assert page.get_by_label("实际回答全文").count() == 0
    return wave, run, answer_id


def negative_driver_contracts(playwright, offline) -> None:
    from backend.app.collectors import CollectorError, get_driver
    executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None, headless=True)
    try:
        for driver_key in URLS:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            offline.configure_context(context, get_driver(driver_key))
            protocol = {"page_mode": "default", "networking": True, "deep_thinking": True,
                        "deep_research": False, "surface": "desktop_web", "session_mode": "new",
                        "login_state": "logged_in", "context_clearing": "new_session", "follow_up_policy": "none"}
            page = context.new_page()
            driver = get_driver(driver_key)(page, URLS[driver_key], protocol, "UTC", timeout=1)
            for scenario, method, expected in (("captcha", "check", "captcha"),
                                                ("missing_composer", "check", "login_expired"),
                                                ("missing_switches", "mode", "driver_incompatible")):
                offline.scenarios[driver_key] = scenario
                driver.open_product()
                try:
                    if method == "check":
                        driver.check_session()
                    else:
                        driver.prepare_new_chat()
                        driver.apply_frozen_mode()
                    raise AssertionError(f"{driver_key} {scenario} unexpectedly passed")
                except CollectorError as error:
                    assert error.kind == expected, (driver_key, scenario, error.kind)
            offline.scenarios[driver_key] = "empty"
            driver.prepare_new_chat()
            driver.apply_frozen_mode()
            driver.submit_prompt(PROMPT)
            try:
                driver.wait_for_completion()
                raise AssertionError(f"{driver_key} empty stream unexpectedly passed")
            except CollectorError as error:
                assert error.kind == "stream_interrupted"
            offline.scenarios[driver_key] = "blank"
            driver.resume_conversation(f"https://{HOSTS[driver_key]}/conversation/{driver_key}-blank")
            try:
                driver.extract_result()
                raise AssertionError(f"{driver_key} blank answer unexpectedly passed")
            except CollectorError as error:
                assert error.kind == "empty"
            offline.scenarios[driver_key] = "normal"
            context.close()
    finally:
        browser.close()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-collector-browser-") as temporary:
        temp = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "GEOPULSE_DB": str(temp / "browser.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
               "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
               "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_BROWSER_PROFILES": str(temp / "profiles"),
               "GEOPULSE_ADMIN_EMAIL": "admin@browser.local", "GEOPULSE_ADMIN_PASSWORD": PASSWORD,
               "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_DISABLE_BROWSER_WORKER": "1",
               "GEOPULSE_BROWSER_HEADLESS": "1", "GEOPULSE_PORT": str(port)}
        os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
        from backend.app.db import connect, one
        from backend.app.migrations import initialize
        from backend.app.services import browser_sessions
        initialize(seed=True)
        log = (temp / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        errors, external = [], []
        offline = OfflineCollectorWorker()
        offline.install()
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                offline.playwright = playwright
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
                errors.clear()
                prompt_set = call(page, "post", "/api/projects/1/prompt-sets", {"name": "授权浏览器单题"})
                imported = call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/items", {
                    "items": [{"text": PROMPT, "dimension": "choice", "query_type": "discovery",
                               "priority": 5, "eligibility": "eligible"}]})
                item_id = imported["items"][0]["id"]
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/items/{item_id}/review",
                     {"status": "reviewed", "eligibility": "eligible"})
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/status",
                     {"status": "reviewing", "reason": "离线 Collector 夹具"})
                call(page, "put", "/api/projects/1/settings", {"settings": {
                    "prompt_quotas": {"brand": 0, "scene": 0, "compare": 0, "choice": 0}}})
                call(page, "post", f"/api/projects/1/prompt-sets/{prompt_set['id']}/status",
                     {"status": "frozen", "reason": "离线 Collector 夹具冻结"})

                targets = {}
                targets["deepseek_web"] = create_target_and_session(
                    page, offline.worker, "DeepSeek 授权网页夹具", "DeepSeek", "deepseek_web")
                targets["kimi_web"] = create_target_and_session(
                    page, offline.worker, "Kimi 授权网页夹具", "Kimi", "kimi_web")
                completed = {}
                for driver_key, target_name in (("deepseek_web", "DeepSeek 授权网页夹具"), ("kimi_web", "Kimi 授权网页夹具")):
                    wave, run, answer_id = create_browser_wave(page, target_name, prompt_set["id"], driver_key)
                    page.evaluate("ids => { location.hash = `#/measure?wave=${ids.wave}&run=${ids.run}`; }",
                                  {"wave": wave["id"], "run": run["id"]})
                    page.locator("[data-browser-progress]").wait_for()
                    assert PROMPT in page.locator("[data-browser-progress]").inner_text()
                    run_one(offline.worker, answer_id)
                    assert finish_run(run["id"]) == "done"
                    detail = call(page, "get", f"/api/projects/1/answers/{answer_id}")
                    assert "离线回答" in detail["raw_text"] and detail["valid_sample"] == 1
                    assert [item["kind"] for item in detail["call_attempts"]] == ["judge"]
                    assert len(detail["citations"]) == 1 and detail["citations"][0]["origin"] == "browser_page"
                    collection = call(page, "get", f"/api/projects/1/answers/{answer_id}/collection")
                    assert collection["browser_phase"] == "completed"
                    assert {item["kind"] for item in collection["attachments"]} == {"screenshot", "raw_html"}
                    for attachment in collection["attachments"]:
                        response = page.request.get(f"{base}/api/projects/1/attachments/{attachment['id']}")
                        assert response.status == 200
                        assert hashlib.sha256(response.body()).hexdigest() == attachment["sha256"]
                        if attachment["kind"] == "screenshot":
                            assert response.body().startswith(b"\x89PNG")
                        else:
                            assert "离线回答" in response.body().decode("utf-8")
                    page.evaluate("ids => { location.hash = `#/review?run=${ids.run}&answer=${ids.answer}&review=all`; }",
                                  {"run": run["id"], "answer": answer_id})
                    page.get_by_text("授权浏览器 Consumer Web 采集事实", exact=True).wait_for()
                    page.get_by_text("授权浏览器提取的页面引用", exact=True).wait_for()
                    assert page.get_by_label("实际回答全文").count() == 0
                    for width, height in ((1440, 1000), (768, 1024), (390, 844)):
                        page.set_viewport_size({"width": width, "height": height})
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(100)
                        assert_no_overflow(page, f"{driver_key} evidence {width}")
                        page.screenshot(path=OUTPUT / f"evidence-{driver_key}-{width}.png", full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    completed[driver_key] = {"wave": wave, "run": run, "answer": answer_id, "detail": detail}
                    assert offline.submissions[driver_key] == [PROMPT]

                # Resume a sent DeepSeek conversation through the admin UI; it must not submit again.
                first = completed["deepseek_web"]
                page.evaluate("wave => { location.hash = `#/measure?wave=${wave}`; }", first["wave"]["id"])
                page.get_by_role("button", name="创建授权采集 Run", exact=True).click()
                with page.expect_response(lambda response: response.request.method == "POST" and "/runs" in response.url) as pending:
                    page.get_by_role("dialog", name="确认发送问题并创建 Run", exact=True).get_by_role(
                        "button", name="确认发送并开始采集", exact=True).click()
                resumed_run = pending.value.json()["run"]
                page.get_by_text("授权浏览器采集与证据", exact=True).wait_for()
                resumed_answer = int(page.locator("[data-answer-id]").first.get_attribute("data-answer-id"))
                with connect() as conn:
                    conn.execute("""UPDATE web_collections SET browser_phase='paused_unknown',browser_send_started_at=updated_at,
                                    prompt_submitted_at=updated_at,conversation_url=? WHERE answer_id=?""",
                                 (f"https://{HOSTS['deepseek_web']}/conversation/deepseek_web-fixture", resumed_answer))
                    conn.commit()
                page.reload(wait_until="networkidle")
                page.locator("[data-answer-id]").first.click()
                page.get_by_role("button", name="恢复原会话，不重发", exact=True).first.click()
                with page.expect_response(lambda response: response.url.endswith(f"/answers/{resumed_answer}/collection/resume")
                                          and response.request.method == "POST"):
                    page.get_by_role("dialog", name="恢复授权浏览器采集", exact=True).get_by_role(
                        "button", name="恢复原会话，不重发", exact=True).click()
                run_one(offline.worker, resumed_answer)
                assert finish_run(resumed_run["id"]) == "done"
                assert offline.submissions["deepseek_web"] == [PROMPT]

                # An unknown send without a conversation URL can only be failed, never resumed.
                second = completed["kimi_web"]
                page.evaluate("wave => { location.hash = `#/measure?wave=${wave}`; }", second["wave"]["id"])
                page.get_by_role("button", name="创建授权采集 Run", exact=True).click()
                with page.expect_response(lambda response: response.request.method == "POST" and "/runs" in response.url) as pending:
                    page.get_by_role("dialog", name="确认发送问题并创建 Run", exact=True).get_by_role(
                        "button", name="确认发送并开始采集", exact=True).click()
                failed_run = pending.value.json()["run"]
                page.get_by_text("授权浏览器采集与证据", exact=True).wait_for()
                failed_answer = int(page.locator("[data-answer-id]").first.get_attribute("data-answer-id"))
                with connect() as conn:
                    conn.execute("""UPDATE web_collections SET browser_phase='paused_unknown',browser_send_started_at=updated_at,
                                    conversation_url='' WHERE answer_id=?""", (failed_answer,))
                    conn.commit()
                page.reload(wait_until="networkidle")
                page.locator("[data-answer-id]").first.click()
                assert page.get_by_role("button", name="恢复原会话，不重发", exact=True).count() == 0
                page.get_by_role("button", name="登记无法恢复", exact=True).click()
                with page.expect_response(lambda response: response.url.endswith(f"/answers/{failed_answer}/collection/resume")
                                          and response.request.method == "POST"):
                    page.get_by_role("dialog", name="登记网页采集无法恢复", exact=True).get_by_role(
                        "button", name="登记失败", exact=True).click()
                page.get_by_role("heading", name="采集失败：other", exact=True).wait_for()
                metrics = call(page, "get", f"/api/projects/1/runs/{failed_run['id']}/metrics")
                assert metrics["quality"]["valid_samples"] == 0

                # Official run, immutable report and Consumer Web provenance.
                page.evaluate("ids => { location.hash = `#/measure?wave=${ids.wave}&run=${ids.run}`; }",
                              {"wave": first["wave"]["id"], "run": first["run"]["id"]})
                page.get_by_role("button", name="指定为正式 Run", exact=True).click()
                with page.expect_response(lambda response: response.url.endswith(f"/waves/{first['wave']['id']}/official")
                                          and response.request.method == "POST"):
                    page.get_by_role("dialog", name="指定正式 Run", exact=True).get_by_role(
                        "button", name="指定为正式 Run", exact=True).click()
                reports = ReportsPage(page)
                reports.open_delivery(first["wave"]["id"])
                report = reports.create_snapshot(first["wave"]["id"])
                client_html = page.request.get(f"{base}/api/projects/1/reports/{report['id']}/export?variant=client&format=html")
                assert client_html.status == 200
                assert "授权浏览器 Consumer Web" in client_html.text()
                assert "Consumer Web 页面引用" in client_html.text()
                assert "内部成本与质量" not in client_html.text()

                # Analyst can dispatch with an existing session but cannot manage browser connections.
                role_pages = []
                for role in ("analyst", "reviewer", "viewer"):
                    email = f"{role}-collector@browser.local"
                    password = f"{role}-browser-password"
                    user = call(page, "post", "/api/users", {"email": email, "password": password})
                    call(page, "post", "/api/projects/1/memberships", {"user_id": user["id"], "role": role})
                    role_context = browser.new_context(viewport={"width": 1440, "height": 1000})
                    role_context.route("**/*", guard)
                    role_page = role_context.new_page()
                    role_page.on("pageerror", lambda error: errors.append(f"role pageerror: {error.stack or error}"))
                    login(role_page, base, email, password)
                    role_pages.append(role_page)
                    if role == "analyst":
                        denied = role_page.request.get(f"{base}/api/projects/1/engines/{targets['deepseek_web']}/browser-sessions")
                        assert denied.status == 403
                        dispatched = call(role_page, "post", f"/api/projects/1/waves/{first['wave']['id']}/runs",
                                          {"confirm_browser": True})["run"]
                        call(role_page, "post", f"/api/projects/1/runs/{dispatched['id']}/cancel", {})
                    role_page.evaluate("ids => { location.hash = `#/review?run=${ids.run}&answer=${ids.answer}&review=all`; }",
                                       {"run": first["run"]["id"], "answer": first["answer"]})
                    role_page.get_by_text("授权浏览器 Consumer Web 采集事实", exact=True).wait_for()
                    assert role_page.get_by_label("实际回答全文").count() == 0
                    assert role_page.get_by_role("button", name="恢复原会话，不重发", exact=True).count() == 0
                    if role in ("reviewer", "viewer"):
                        assert role_page.get_by_role("button", name="下载", exact=True).count() == 0
                        role_page.get_by_text("原文不可见", exact=True).wait_for()
                    role_page.set_viewport_size({"width": 390, "height": 844})
                    assert_no_overflow(role_page, f"{role} collector mobile")
                    role_page.screenshot(path=OUTPUT / f"role-{role}-390.png", full_page=True)

                # Revoke both sessions and prove profile cleanup does not remove historical evidence.
                with connect() as conn:
                    rows = conn.execute("SELECT id,profile_ref FROM browser_sessions WHERE status!='revoked'").fetchall()
                    profiles = {row["id"]: browser_sessions.profile_path(row["profile_ref"]) for row in rows}
                for session_id, profile in profiles.items():
                    call(page, "post", f"/api/projects/1/browser-sessions/{session_id}/revoke", {})
                    assert profile.exists()
                offline.worker._cleanup_revoked()
                assert all(not profile.exists() for profile in profiles.values())
                retained = call(page, "get", f"/api/projects/1/answers/{first['answer']}")
                assert retained["raw_text"] == first["detail"]["raw_text"]

                negative_driver_contracts(playwright, offline)
                for role_page in role_pages:
                    role_page.context.close()
                browser.close()
            assert not external, f"unexpected UI external requests: {external}"
            assert not offline.unexpected, f"unexpected Collector requests: {offline.unexpected}"
            assert not errors, "browser errors:\n" + "\n".join(errors)
            print(json.dumps({"status": "passed", "drivers": list(URLS), "viewports": [1440, 768, 390],
                              "roles": ["admin", "analyst", "reviewer", "viewer"],
                              "deepseek_submissions": len(offline.submissions["deepseek_web"]),
                              "kimi_submissions": len(offline.submissions["kimi_web"]),
                              "external_requests": 0, "report_id": report["id"]}, ensure_ascii=False, indent=2))
        except Exception:
            if process.poll() is not None:
                print(log.name)
            raise
        finally:
            offline.restore()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    main()
