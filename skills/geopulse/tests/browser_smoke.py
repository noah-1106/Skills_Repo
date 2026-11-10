#!/usr/bin/env python3
"""Real-browser critical-path smoke test with an isolated DB and dynamic port."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from browser_support import ReportsPage, call

OUTPUT = ROOT / "test-results" / "browser"
PASSWORD = "test-browser-password"


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


def seed_official_run() -> None:
    from backend.app.db import connect, one
    from backend.app.migrations import SCHEMA_VERSION, initialize
    from backend.app.services.measurement import Worker, create_run, create_wave

    initialize()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects ORDER BY id LIMIT 1")
        prompt_set = one(conn, "SELECT * FROM prompt_sets WHERE project_id=? AND status='frozen'", (project["id"],))
        engine = one(conn, "SELECT * FROM engine_configs WHERE project_id=? AND kind='demo'", (project["id"],))
    waves = []
    worker = Worker(2)
    worker.start()
    try:
        for label in ("浏览器验收基线", "浏览器验收复测"):
            wave = create_wave(project, 1, {"label": label, "prompt_set_id": prompt_set["id"], "engine_ids": [engine["id"]], "repeats": 1})
            run = create_run(project, wave, 1)
            current = None
            for _ in range(300):
                with connect() as conn:
                    current = one(conn, "SELECT status FROM runs WHERE id=?", (run["id"],))
                if current["status"] in ("done", "partial", "failed"):
                    break
                time.sleep(0.05)
            assert current["status"] == "done", current
            with connect() as conn:
                conn.execute("UPDATE waves SET official_run_id=? WHERE id=?", (run["id"], wave["id"]))
                conn.commit()
            waves.append((wave["id"], run["id"]))
    finally:
        worker.stop()
    return waves


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-browser-") as temporary:
        temp = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "GEOPULSE_DB": str(temp / "browser.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
               "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
               "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_ADMIN_EMAIL": "admin@browser.local",
               "GEOPULSE_ADMIN_PASSWORD": PASSWORD, "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_PORT": str(port)}
        os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
        waves = seed_official_run()
        latest_official_wave, latest_official_run = waves[-1]
        from backend.app.migrations import SCHEMA_VERSION
        log = (temp / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_server(port, process)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = os.environ.get("CHROME_PATH") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                browser = playwright.chromium.launch(executable_path=executable if Path(executable).is_file() else None, headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                errors = []
                cdp = page.context.new_cdp_session(page)
                cdp.send("Runtime.enable")
                cdp.on("Runtime.exceptionThrown", lambda event: errors.append(json.dumps(event, ensure_ascii=False)))
                page.on("pageerror", lambda error: errors.append(f"pageerror: {error.stack or error}"))
                page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
                base = f"http://127.0.0.1:{port}"
                page.goto(base, wait_until="networkidle")
                if not page.locator(".login-form").count():
                    modules = await_modules = page.evaluate("""async () => { const out={}; for (const name of ['components','api','app']) { try { await import(`/static/${name}.js`); out[name]='ok'; } catch(e) { out[name]=e.stack || e.message; } } for (const name of ['overview','prompts','entities','measure','review','opportunities','reports','admin']) { try { await import(`/static/views/${name}.js`); out[name]='ok'; } catch(e) { out[name]=e.stack || e.message; } } return out; }""")
                    raise RuntimeError(f"Browser startup diagnostics: {errors}; modules={modules}; body={page.locator('body').inner_text()}")
                page.screenshot(path=OUTPUT / "00-login-desktop.png", full_page=True)
                for width in (768, 800):
                    page.set_viewport_size({"width": width, "height": 1024})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{width} login overflow"
                    page.screenshot(path=OUTPUT / f"00-login-{width}.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(150)
                page.screenshot(path=OUTPUT / "00-login-mobile.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.get_by_text("项目总览", exact=True).first.wait_for()
                page.wait_for_selector(".stage-panel")
                page.evaluate("""async () => {
                  const {h, drawer, field, input} = await import('/static/components.js');
                  const first = input(''); const second = input(''); const third = input('');
                  const modal = drawer('焦点竞争验收', h('form', {}, field('第一字段', first), field('第二字段', second), field('第三字段', third)));
                  third.focus();
                  window.__focusProbe = {modal, third};
                }""")
                page.wait_for_timeout(50)
                assert page.evaluate("document.activeElement === window.__focusProbe.third"), "Drawer autofocus overwrites a user's earlier focus"
                page.evaluate("() => { window.__focusProbe.modal.close(); delete window.__focusProbe; }")
                page.screenshot(path=OUTPUT / "01-overview-desktop.png", full_page=True)
                page.set_viewport_size({"width": 2560, "height": 1440})
                page.wait_for_timeout(150)
                wide_edges = page.evaluate("""() => {
                  const workspace = document.getElementById('workspace');
                  const head = document.querySelector('.page-head').getBoundingClientRect();
                  const gutter = parseFloat(getComputedStyle(workspace).paddingLeft);
                  const topbarGutter = parseFloat(getComputedStyle(document.querySelector('.topbar')).paddingLeft);
                  return {left: head.left, right: head.right, contentWidth: head.width, gutter, topbarGutter,
                    navWidth: document.getElementById('sidebar').getBoundingClientRect().width,
                    width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth};
                }""")
                assert wide_edges["navWidth"] == 208
                assert abs(wide_edges["left"] - (wide_edges["navWidth"] + wide_edges["gutter"])) < 1
                assert abs(wide_edges["right"] - (wide_edges["width"] - wide_edges["gutter"])) < 1
                assert wide_edges["contentWidth"] <= 1441
                assert wide_edges["topbarGutter"] == wide_edges["gutter"] and not wide_edges["overflow"]
                page.locator("#workspace").focus()
                assert page.locator("#workspace").evaluate("node => getComputedStyle(node).outlineStyle") == "none"
                page.screenshot(path=OUTPUT / "01b-overview-wide.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.wait_for_timeout(100)
                wilson = page.evaluate("""async () => {
                    const { metric } = await import('/static/components.js');
                    const regular = metric('常规样本', { value: 45, ci_low: 35, ci_high: 55, hits: 45, n: 100, limited: false });
                    const limited = metric('小样本', { value: 37.5, ci_low: 13.7, ci_high: 69.4, hits: 3, n: 8, limited: true });
                    const empty = metric('空样本', { value: null, ci_low: null, ci_high: null, hits: 0, n: 0, limited: true });
                    const missing = metric('缺失区间', { value: 20, ci_low: null, ci_high: 50, hits: 20, n: 100, limited: false });
                    return {
                        regularValue: regular.querySelector('.metric-value').textContent,
                        regularTrack: regular.querySelector('.wilson-track')?.getAttribute('style') || '',
                        limitedValue: limited.querySelector('.metric-value').textContent,
                        limitedText: limited.textContent,
                        invalidTracks: [empty, missing].filter((node) => node.querySelector('.wilson-track')).length,
                    };
                }""")
                assert wilson["regularValue"] == "45%"
                assert "35%" in wilson["regularTrack"] and "20%" in wilson["regularTrack"]
                assert wilson["limitedValue"] == "3/8" and "小样本仅看方向" in wilson["limitedText"]
                assert wilson["invalidTracks"] == 0
                errors.clear()  # initial /auth/me 401 is the expected logged-out bootstrap

                page.locator("#main-nav a[href='#/prompts']").click()
                page.get_by_role("button", name="新建草稿", exact=True).click()
                name_input = page.get_by_label("问题集名称")
                page.wait_for_timeout(100)
                page.wait_for_function("node => document.activeElement === node", arg=name_input.element_handle())
                page.wait_for_function("node => getComputedStyle(node).borderColor === 'rgb(0, 116, 123)'", arg=name_input.element_handle())
                input_style = name_input.evaluate("node => { const style = getComputedStyle(node); return {height: node.getBoundingClientRect().height, radius: style.borderRadius, border: style.borderColor, outline: style.outlineColor, fontSize: style.fontSize}; }")
                assert input_style == {"height": 42, "radius": "6px", "border": "rgb(0, 116, 123)", "outline": "rgb(0, 116, 123)", "fontSize": "14px"}, input_style
                name_input.fill("浏览器新问题集")
                page.get_by_role("button", name="创建草稿", exact=True).click()
                page.get_by_role("button", name="生成候选题", exact=True).wait_for()
                page.get_by_role("button", name="生成候选题", exact=True).click()
                page.get_by_role("button", name="预览 16 条候选题", exact=True).click()
                page.get_by_role("button", name="加入当前草稿", exact=True).wait_for()
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null"), "Preview step loses dialog focus"
                assert page.locator("#app-shell").evaluate("node => node.inert")
                page.screenshot(path=OUTPUT / "02-prompt-scaffold.png", full_page=True)
                page.get_by_role("button", name="加入当前草稿", exact=True).click()
                page.get_by_text("已加入 16 条，跳过 0 条重复", exact=True).wait_for()
                page.locator(".table-wrap .table-link").first.click()
                page.get_by_role("dialog").get_by_text("Canonical intent", exact=True).wait_for()
                page.get_by_role("button", name="关闭对话框", exact=True).click()

                version_select = page.get_by_label("选择问题集版本", exact=True)
                assert version_select.evaluate("node => node.tagName") == "SELECT"
                select_style = version_select.evaluate("node => { const style = getComputedStyle(node); return {appearance: style.appearance, arrow: style.backgroundImage, radius: style.borderRadius, height: node.getBoundingClientRect().height}; }")
                assert select_style["appearance"] == "none" and "data:image/svg+xml" in select_style["arrow"]
                assert select_style["radius"] == "6px" and select_style["height"] == 42
                version_select.evaluate("node => { node.disabled = true; }")
                page.wait_for_timeout(150)
                disabled_style = version_select.evaluate("node => { const style = getComputedStyle(node); return {background: style.backgroundColor, cursor: style.cursor, opacity: style.opacity}; }")
                assert disabled_style == {"background": "rgb(237, 243, 244)", "cursor": "not-allowed", "opacity": "1"}
                version_select.evaluate("node => { node.disabled = false; node.setAttribute('aria-invalid', 'true'); }")
                page.wait_for_timeout(150)
                assert version_select.evaluate("node => getComputedStyle(node).borderColor") == "rgb(158, 54, 66)"
                version_select.evaluate("node => node.removeAttribute('aria-invalid')")
                version_select.hover()
                page.wait_for_timeout(150)
                assert version_select.evaluate("node => getComputedStyle(node).borderColor") == "rgb(64, 84, 92)"
                draft_set_id = version_select.input_value()
                frozen_set_id = version_select.locator("option").evaluate_all("nodes => nodes.find(node => node.textContent.includes('已冻结')).value")
                version_select.select_option(frozen_set_id)
                page.get_by_role("heading", name="这是不可变测量版本", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "02b-prompt-frozen.png", full_page=True)
                page.get_by_label("选择问题集版本", exact=True).select_option(draft_set_id)
                page.get_by_role("heading", name="16 条候选题待进入审核", exact=True).wait_for()

                page.locator("#main-nav a[href='#/entities']").click()
                page.get_by_role("button", name="新增实体", exact=True).click()
                page.get_by_label("实体名称").fill("Browser <b>Entity</b>")
                page.get_by_label("别名", exact=True).fill("BrowserEntity")
                page.get_by_label("品类").fill("浏览器测试实体")
                entity_fields = page.locator("[role=dialog] .field").evaluate_all("nodes => nodes.map(node => ({label: node.querySelector('label')?.htmlFor, text: node.querySelector('label')?.textContent, id: node.querySelector('input,textarea,select')?.id, value: node.querySelector('input,textarea,select')?.value}))")
                assert page.get_by_label("实体名称").input_value() == "Browser <b>Entity</b>", entity_fields
                assert page.get_by_label("品类", exact=True).input_value() == "浏览器测试实体", entity_fields
                with page.expect_request(lambda request: request.url.endswith("/api/projects/1/entities") and request.method == "POST") as entity_request:
                    page.get_by_role("button", name="保存为待审核草稿", exact=True).click()
                entity_payload = entity_request.value.post_data_json
                assert entity_payload["name"] == "Browser <b>Entity</b>"
                assert entity_payload["entity_card"]["category"] == "浏览器测试实体"
                page.get_by_text("实体草稿已保存，等待管理员审核", exact=True).wait_for()
                entity_review = page.get_by_role("button", name="审核 Browser <b>Entity</b>", exact=True)
                try:
                    entity_review.wait_for(timeout=5000)
                except Exception as error:
                    dialog_text = page.get_by_role("dialog").inner_text() if page.get_by_role("dialog").count() else "no dialog"
                    raise RuntimeError(f"Entity create diagnostics: {dialog_text}; page={page.locator('#workspace').inner_text()}") from error
                entity_review.click()
                page.get_by_label("消歧依据").fill("浏览器测试：官网、品类和别名已人工核对")
                page.get_by_role("button", name="保存审核决定", exact=True).click()
                page.get_by_text("实体审核已留痕", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "03-entities.png", full_page=True)
                assert page.get_by_text("Browser <b>Entity</b>", exact=True).count() > 0
                assert page.locator("b").filter(has_text="Entity").count() == 0

                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_text("浏览器验收基线", exact=True).first.wait_for()
                page.wait_for_selector(".metric-strip")
                page.locator(".run-history summary").click()
                run_link = page.locator(".run-history .table-link").first
                selected_run_id = run_link.get_attribute("data-run-id")
                page.locator(".measure-browser").evaluate("node => { node.dataset.previousView = 'true'; }")
                run_link.click()
                page.wait_for_function("location.hash.includes('wave=') && location.hash.includes('run=')")
                page.locator(".measure-browser:not([data-previous-view]) .run-focus h2").filter(has_text=f"Run #{selected_run_id}").wait_for()
                page.wait_for_function("() => document.querySelectorAll(\".list-rail .list-item[aria-current='location']\").length === 1")
                assert page.locator(".list-rail .list-item[aria-current='location']").count() == 1
                measure_deep_link = page.url
                page.reload(wait_until="networkidle")
                page.wait_for_selector(".run-focus")
                assert page.url == measure_deep_link
                page.screenshot(path=OUTPUT / "04-measure-desktop.png", full_page=True)

                page.locator("#main-nav a[href='#/review']").click()
                page.get_by_label("复核状态", exact=True).select_option("all")
                page.wait_for_selector(".raw-answer")
                assert page.locator(".raw-answer").get_attribute("tabindex") == "0"
                assert page.locator(".raw-answer").get_attribute("role") == "region"
                assert page.locator(".raw-answer").get_attribute("aria-label") == "原始回答全文"
                assert page.locator(".evidence-browser .list-item[aria-current='location']").count() == 1
                page.screenshot(path=OUTPUT / "05-review-desktop.png", full_page=True)
                raw_answer = page.locator(".raw-answer").inner_text()
                page.get_by_role("button", name="新增人工修订", exact=True).nth(0).click()
                page.get_by_label("目标实体在回答中出现", exact=True).uncheck()
                page.get_by_label("提及深度", exact=True).select_option("absent")
                page.get_by_label("情感", exact=True).select_option("unknown")
                page.get_by_label("原文证据", exact=True).fill("")
                page.get_by_label("修订理由", exact=True).fill("浏览器构造主品牌缺席夹具，保留原始回答")
                page.get_by_label("以管理员仲裁结论提交").check()
                page.get_by_role("button", name="保存新 Revision", exact=True).click()
                page.get_by_text("新 revision 已保存，原始回答未改变", exact=True).wait_for()
                page.wait_for_selector(".raw-answer")
                assert page.locator(".raw-answer").inner_text() == raw_answer
                page.get_by_role("button", name="新增人工修订", exact=True).nth(1).click()
                page.get_by_label("提及深度", exact=True).select_option("recommended")
                page.get_by_label("情感", exact=True).select_option("positive")
                page.get_by_label("这是当前问题下的首选推荐", exact=True).check()
                page.get_by_label("原文证据", exact=True).fill(raw_answer)
                page.get_by_label("修订理由", exact=True).fill("浏览器构造竞品领先机会，证据逐字来自原文")
                page.get_by_label("以管理员仲裁结论提交").check()
                page.get_by_role("button", name="保存新 Revision", exact=True).click()
                page.get_by_text("新 revision 已保存，原始回答未改变", exact=True).wait_for()

                def without_observations(route):
                    response = route.fetch()
                    payload = response.json()
                    payload["observations"] = []
                    route.fulfill(response=response, json=payload)
                page.route("**/api/projects/1/answers/*", without_observations)
                page.reload(wait_until="networkidle")
                page.get_by_role("heading", name="还没有实体判定", exact=True).wait_for()
                assert page.get_by_text("当前回答没有实体判定记录。请检查 Judge 调用状态，不要补造零提及。", exact=True).count() == 1
                page.screenshot(path=OUTPUT / "05c-review-no-observations.png", full_page=True)
                page.unroute("**/api/projects/1/answers/*", without_observations)
                page.evaluate("window.scrollTo(0, 400)")
                assert page.evaluate("window.scrollY") > 0
                page.evaluate("location.hash = '#/prompts'")
                page.get_by_role("heading", name="问题集工作台", exact=True).wait_for()
                assert page.evaluate("window.scrollY") == 0, "Route change preserves the previous page scroll"

                page.locator("#main-nav a[href='#/opportunities']").click()
                page.get_by_role("button", name="从正式 Run 发现候选", exact=True).click()
                page.get_by_role("button", name="生成候选", exact=True).click()
                page.get_by_text("生成 1 个候选", exact=True).wait_for()
                page.get_by_role("button", name="审核适用性", exact=True).click()
                page.get_by_label("审核说明", exact=True).fill("浏览器确认该发现适用于演示客户")
                page.get_by_role("button", name="保存管理员决定", exact=True).click()
                page.get_by_text("适用性审核已保存", exact=True).wait_for()
                page.get_by_role("tab", name="已确认机会 (1)").click()
                page.get_by_role("button", name="创建 Action", exact=True).click()
                page.get_by_label("Action 标题", exact=True).fill("浏览器七步事实页")
                page.get_by_label("负责人", exact=True).fill("浏览器测试负责人")
                page.get_by_label("目标 URL / 平台", exact=True).fill("https://example.com/browser-evidence")
                page.get_by_role("button", name="创建 Action 草稿", exact=True).click()
                action_drawer = page.get_by_role("dialog", name=re.compile(r"^Intervention #"))
                try:
                    action_drawer.get_by_text("浏览器七步事实页", exact=True).wait_for(timeout=5000)
                except Exception as error:
                    dialog_text = page.get_by_role("dialog").all_inner_texts()
                    raise RuntimeError(f"Action create diagnostics: {dialog_text}; page={page.locator('#workspace').inner_text()}; errors={errors}") from error
                action_drawer.get_by_role("button", name="提交审核", exact=True).click()
                action_drawer.get_by_role("button", name="批准行动", exact=True).wait_for()
                action_drawer.get_by_role("button", name="批准行动", exact=True).click()
                action_drawer.get_by_role("button", name="登记真实发布", exact=True).wait_for()
                action_drawer.get_by_role("button", name="登记真实发布", exact=True).click()
                page.get_by_role("button", name="确认已发布并登记事件", exact=True).click()
                source_wave = call(page, "get", f"/api/projects/1/waves/{latest_official_wave}")
                extra_targets = []
                for suffix in ("D14", "D28"):
                    extra = call(page, "post", "/api/projects/1/waves", {
                        "prompt_set_id": source_wave["protocol"]["prompt_set_id"],
                        "label": f"浏览器验收{suffix}",
                        "engine_ids": source_wave["protocol"]["engine_ids"],
                        "repeats": source_wave["protocol"]["repeats"],
                        "use_judge": source_wave["protocol"]["use_judge"],
                    })
                    extra_targets.append(extra["id"])
                page.reload(wait_until="networkidle")
                action_drawer.wait_for()
                page.get_by_role("button", name="安排 D7/D14/D28 复测", exact=True).click()
                for days, target_id in zip((7, 14, 28), [waves[0][0], *extra_targets]):
                    page.get_by_label(f"D{days} 目标 Wave", exact=True).select_option(str(target_id))
                page.get_by_role("button", name="创建 D7/D14/D28 节点", exact=True).click()
                page.get_by_text("D7/D14/D28 复测节点已创建", exact=True).wait_for()
                d7 = page.locator(".round-node").filter(has_text="D7")
                d7.get_by_role("button", name="评估本轮", exact=True).click()
                page.get_by_label("评估依据", exact=True).fill("浏览器固定同口径正式 Run；默认小样本阈值下只能记录证据不足")
                page.get_by_role("button", name="冻结本轮评估", exact=True).click()
                page.get_by_text("本轮评估已冻结", exact=True).wait_for()
                page.get_by_text("证据不足", exact=True).first.wait_for()
                assert page.get_by_role("button", name="重新打开为草稿", exact=True).count() == 0
                page.get_by_text("客户决策摘要", exact=True).first.wait_for()
                page.screenshot(path=OUTPUT / "05b-action-complete.png", full_page=True)
                page.get_by_role("button", name="关闭对话框", exact=True).click()

                page.locator("#main-nav a[href='#/reports']").click()
                page.get_by_role("button", name="检查口径并比较", exact=True).click()
                page.get_by_text("协议与样本完整度通过", exact=True).wait_for()
                page.wait_for_selector(".transition-grid")
                assert page.get_by_text("小样本仅观察方向", exact=True).count() > 0
                assert page.get_by_text("持续提及", exact=True).count() > 0
                assert page.get_by_role("columnheader", name="相对变化", exact=True).count() == 0
                page.screenshot(path=OUTPUT / "06a-comparison-desktop.png", full_page=True)
                page.evaluate("""() => {
                  window.__chartOptions = [];
                  window.__originalEchartsInit = window.echarts.init;
                  window.echarts.init = (...args) => {
                    const chart = window.__originalEchartsInit(...args);
                    const setOption = chart.setOption.bind(chart);
                    chart.setOption = (options, ...rest) => {
                      window.__chartOptions.push(options);
                      return setOption(options, ...rest);
                    };
                    return chart;
                  };
                }""")
                def full_sample_comparison(route):
                    response = route.fetch()
                    payload = response.json()
                    for row in payload["delta"].values():
                        row["baseline"]["limited"] = False
                        row["current"]["limited"] = False
                    route.fulfill(response=response, json=payload)
                page.route("**/api/projects/1/compare?*", full_sample_comparison)
                page.emulate_media(reduced_motion="reduce")
                page.get_by_role("button", name="检查口径并比较", exact=True).click()
                page.locator(".chart canvas").wait_for()
                chart_options = page.evaluate("window.__chartOptions.at(-1)")
                assert chart_options["animation"] is False
                assert chart_options["animationDuration"] == chart_options["animationDurationUpdate"] == 0
                page.unroute("**/api/projects/1/compare?*", full_sample_comparison)
                page.evaluate("() => { window.echarts.init = window.__originalEchartsInit; }")
                page.emulate_media(reduced_motion="no-preference")
                source_wave = call(page, "get", f"/api/projects/1/waves/{latest_official_wave}")
                unexecuted = call(page, "post", "/api/projects/1/waves", {
                    "prompt_set_id": source_wave["protocol"]["prompt_set_id"],
                    "label": source_wave["label"],
                    "engine_ids": source_wave["protocol"]["engine_ids"],
                    "repeats": source_wave["protocol"]["repeats"],
                    "use_judge": source_wave["protocol"]["use_judge"],
                })
                assert unexecuted["id"] > latest_official_wave and not unexecuted["official_run_id"]
                reports_page = ReportsPage(page)
                reports_page.open_delivery(wave_id=latest_official_wave)
                report = reports_page.create_snapshot(latest_official_wave)
                report_id = report["id"]
                page.get_by_text(f"报告 v{report['version']} · 草稿", exact=True).wait_for()
                report_detail = call(page, "get", f"/api/projects/1/reports/{report_id}")
                assert report_detail["snapshot"]["waves"][-1]["wave"]["id"] == latest_official_wave
                assert report_detail["snapshot"]["waves"][-1]["run"]["id"] == latest_official_run
                from backend.app.db import connect, loads, one
                with connect() as conn:
                    stored_report = one(conn, "SELECT wave_ids_json FROM reports WHERE id=?", (report_id,))
                assert loads(stored_report["wave_ids_json"], []) == [latest_official_wave]
                for label in ("推进到数据已核验", "推进到策略已复核", "推进到客户版已批准"):
                    page.get_by_role("button", name=label, exact=True).click()
                    page.get_by_role("button", name="确认推进", exact=True).click()
                    page.wait_for_timeout(300)
                page.get_by_text(f"报告 v{report['version']} · 客户版已批准", exact=True).wait_for()
                pdf = page.request.get(f"{base}/api/projects/1/reports/{report_id}/export?variant=client&format=pdf")
                assert pdf.status == 200, pdf.text()
                assert pdf.body().startswith(b"%PDF")
                (OUTPUT / "client-report.pdf").write_bytes(pdf.body())
                report_html = page.request.get(f"{base}/api/projects/1/reports/{report_id}/export?variant=client&format=html")
                assert report_html.status == 200, report_html.text()
                report_text = report_html.text()
                assert "选购词" in report_text and "客户已确认适用" in report_text and "第 3 步" in report_text
                assert "client_confirmed" not in report_text and "Step 3" not in report_text
                page.wait_for_function("() => { const toast = document.getElementById('toast'); return !toast.classList.contains('show') && getComputedStyle(toast).opacity === '0'; }")
                page.screenshot(path=OUTPUT / "06-reports-desktop.png", full_page=True)

                baseline_report = call(page, "post", "/api/projects/1/reports", {"wave_ids": [waves[0][0]]})
                def distinguish_snapshot_waves(route):
                    response = route.fetch()
                    payload = response.json()
                    for item in payload["items"]:
                        item["protocol"]["repeats"] = 7 if item["id"] == waves[0][0] else 1
                    route.fulfill(response=response, json=payload)
                page.route("**/api/projects/1/waves", distinguish_snapshot_waves)
                page.evaluate("report => { location.hash = `#/reports?tab=delivery&report=${report}`; }", baseline_report["id"])
                page.get_by_text(f"报告 v{baseline_report['version']} · 草稿", exact=True).wait_for()
                page.locator(".protocol-details summary").click()
                repeats = page.locator(".protocol-details dl > div").filter(has=page.locator("dt", has_text="轮次")).locator("dd").inner_text()
                assert repeats == "7 轮", "Historical report uses the newest Wave instead of its snapshot Wave"
                page.unroute("**/api/projects/1/waves", distinguish_snapshot_waves)

                page.locator("#main-nav a[href='#/admin']").click()
                page.wait_for_timeout(700)
                if not page.get_by_text("测量目标配置", exact=True).count():
                    raise RuntimeError(f"Admin diagnostics: {errors}; body={page.locator('body').inner_text()}")
                page.get_by_text("测量目标配置", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "07-admin-desktop.png", full_page=True)
                page.get_by_role("tab", name=re.compile(r"^调度与告警")).click()
                page.get_by_text("Wave 调度", exact=True).wait_for()
                page.get_by_role("button", name="安排复测", exact=True).click()
                page.get_by_label("执行频率", exact=True).select_option("14")
                page.get_by_label("下次执行时间", exact=True).fill("2027-01-15T10:00")
                page.get_by_role("button", name="保存调度", exact=True).click()
                page.get_by_text("复测调度已保存", exact=True).wait_for()
                page.get_by_text("待执行", exact=True).first.wait_for()
                page.get_by_role("tab", name="成本与运营").click()
                page.get_by_text("调用类型与币种", exact=True).wait_for()
                page.get_by_role("tab", name="设置与数据治理").click()
                with page.expect_download() as backup_download:
                    page.get_by_role("button", name="立即备份数据库", exact=True).click()
                backup_manifest = json.loads(Path(backup_download.value.path()).read_text(encoding="utf-8"))
                assert backup_manifest["sha256"] and backup_manifest["schema_version"] == SCHEMA_VERSION
                with page.expect_download() as export_download:
                    page.get_by_role("button", name="导出当前项目", exact=True).click()
                exported = json.loads(Path(export_download.value.path()).read_text(encoding="utf-8"))
                assert exported["sha256"] and exported["project_id"] == 1
                assert all(not row["secret_ref"] for row in exported["tables"]["engine_configs"])

                page.locator("#main-nav a[href='#/concepts']").click()
                page.get_by_role("heading", name="常见概念", exact=True).wait_for()
                assert page.locator(".work-section table").count() == 4
                assert page.get_by_role("cell", name="判定模型", exact=True).count() == 1
                assert page.get_by_role("cell", name="测量轮次", exact=True).count() == 1
                assert page.get_by_text("上下文窗口", exact=True).count() >= 1
                page.locator(".toast.show").wait_for(state="hidden")
                page.screenshot(path=OUTPUT / "07b-concepts-desktop.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(200)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator(".table-wrap:visible").evaluate_all("nodes => nodes.filter(node => node.scrollWidth > node.clientWidth + 1).length") == 0
                page.screenshot(path=OUTPUT / "07c-concepts-mobile.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.wait_for_timeout(100)

                page.locator("#account-menu summary").click()
                page.get_by_role("button", name="新建客户项目", exact=True).click()
                page.get_by_label("客户名称", exact=True).fill("第二测试客户")
                page.get_by_label("项目名称", exact=True).fill("待删除隔离项目")
                page.get_by_label("业务品类", exact=True).fill("隔离测试")
                page.get_by_role("button", name="创建项目", exact=True).click()
                try:
                    page.get_by_role("heading", name="品牌实体工作台", exact=True).wait_for(timeout=5000)
                except Exception as error:
                    dialog_text = page.get_by_role("dialog").inner_text() if page.get_by_role("dialog").count() else "no dialog"
                    raise RuntimeError(f"Project create diagnostics: {dialog_text}; page={page.locator('body').inner_text()}; errors={errors}") from error
                page.get_by_role("heading", name="还没有实体，先建立主品牌与竞品池", exact=True).wait_for()
                assert page.get_by_text("还没有实体。使用上方“新增实体”创建主品牌或竞品草稿。", exact=True).count() == 1
                page.screenshot(path=OUTPUT / "03b-entities-empty.png", full_page=True)
                page.evaluate("location.hash = '#/reports?tab=invalid'")
                page.get_by_role("heading", name="对比与报告", exact=True).wait_for()
                assert page.get_by_role("tab", name="变化对比", exact=True).get_attribute("aria-selected") == "true"
                assert page.locator("[role=tabpanel]").count() == 1
                assert page.get_by_role("link", name="前往测量执行", exact=True).count() == 1
                page.get_by_role("tab", name="报告交付 (0)", exact=True).click()
                assert page.locator("[role=tabpanel] .empty-state").count() == 1
                assert page.get_by_role("button", name="创建报告快照", exact=True).is_disabled()
                assert page.get_by_role("link", name="前往测量执行", exact=True).count() == 1
                page.screenshot(path=OUTPUT / "06b-reports-empty.png", full_page=True)
                page.locator("#main-nav a[href='#/overview']").click()
                page.locator(".baseline-checklist").wait_for()
                assert page.locator("#protocol-band").is_hidden()
                assert page.get_by_role("heading", name="最近 wave", exact=True).count() == 0
                assert page.get_by_text("尚无可解读的正式数据", exact=True).count() == 0
                assert page.get_by_role("link", name="检查品牌实体", exact=True).count() == 1
                assert page.get_by_role("link", name="测量工作台", exact=True).count() == 0
                page.wait_for_function("() => { const toast = document.getElementById('toast'); return !toast.classList.contains('show') && getComputedStyle(toast).opacity === '0'; }")
                empty_style = page.locator(".stage-panel.empty-flow").evaluate("node => { const style = getComputedStyle(node); return {background: style.backgroundColor, border: style.borderTopWidth, padding: style.padding}; }")
                assert empty_style == {"background": "rgba(0, 0, 0, 0)", "border": "0px", "padding": "0px"}
                assert page.locator(".baseline-checklist li[aria-current='step']").count() == 1
                page.screenshot(path=OUTPUT / "01c-overview-empty.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(150)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=OUTPUT / "01d-overview-empty-mobile.png", full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.wait_for_timeout(100)
                page.locator("#main-nav a[href='#/entities']").click()
                page.get_by_role("button", name="新增实体", exact=True).click()
                page.get_by_label("实体名称", exact=True).fill("待删除项目排除实体")
                page.get_by_role("button", name="保存为待审核草稿", exact=True).click()
                page.get_by_role("button", name="审核 待删除项目排除实体", exact=True).click()
                page.get_by_label("审核决定", exact=True).select_option("rejected")
                rejected_role = page.get_by_label("确认后的角色", exact=True)
                assert rejected_role.is_hidden() and rejected_role.is_disabled()
                page.get_by_label("消歧依据", exact=True).fill("空实体池分支验收：明确排除此版本")
                page.get_by_role("button", name="保存审核决定", exact=True).click()
                page.get_by_role("heading", name="实体池尚无已确认主品牌", exact=True).wait_for()
                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("tab", name="设置与数据治理").click()
                page.get_by_text("危险操作：删除当前项目", exact=True).click()
                page.get_by_role("button", name="永久删除当前项目", exact=True).click()
                page.get_by_label("输入完整项目名确认", exact=True).fill("错误确认")
                page.get_by_role("button", name="永久删除项目", exact=True).click()
                page.get_by_text("项目名不完全一致", exact=True).wait_for()
                delete_error = page.locator("[role=dialog] .form-error")
                assert delete_error.get_attribute("role") == "alert"
                page.wait_for_function("node => document.activeElement === node", arg=delete_error.element_handle())
                page.get_by_label("输入完整项目名确认", exact=True).fill("待删除隔离项目")
                held_deletes = []
                def hold_project_delete(route):
                    held_deletes.append(route)
                page.route("**/api/projects/2?confirm=*", hold_project_delete)
                page.get_by_role("button", name="永久删除项目", exact=True).click()
                for _ in range(100):
                    if held_deletes: break
                    time.sleep(0.05)
                assert len(held_deletes) == 1
                delete_form = page.locator("form[aria-busy='true']")
                assert delete_form.get_by_role("button", name="永久删除项目", exact=True).is_disabled()
                delete_form.evaluate("node => node.requestSubmit()")
                assert len(held_deletes) == 1
                with page.expect_navigation(wait_until="networkidle"):
                    held_deletes.pop().continue_()
                page.unroute("**/api/projects/2?confirm=*", hold_project_delete)
                page.get_by_role("heading", name="系统管理", exact=True).wait_for()
                assert page.get_by_label("切换客户项目").input_value() == "1"

                visual_routes = [
                    ("overview", "#/overview", "项目总览"),
                    ("prompts", "#/prompts", "问题集工作台"),
                    ("entities", "#/entities", "品牌实体工作台"),
                    ("measure", "#/measure", "测量执行"),
                    ("opportunities", "#/opportunities?tab=remeasure", "机会与行动"),
                    ("review", "#/review?review=all", "证据复核"),
                    ("reports", f"#/reports?tab=delivery&report={report_id}", "对比与报告"),
                    ("concepts", "#/concepts", "常见概念"),
                    ("admin", "#/admin?tab=engines", "系统管理"),
                ]
                page.set_viewport_size({"width": 1280, "height": 900})
                for name, route, heading in visual_routes:
                    page.evaluate("route => { location.hash = route; }", route)
                    page.get_by_role("heading", name=heading, exact=True).wait_for()
                    page.wait_for_timeout(200)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"1280 overflow: {name}"
                    if name == "prompts":
                        assert page.locator("#protocol-band").is_hidden()
                    page.screenshot(path=OUTPUT / f"11-{name}-1280.png", full_page=True)

                for width, height in ((1440, 1000), (2560, 1440), (1024, 768), (901, 900), (900, 1000), (820, 1180), (768, 1024)):
                    page.set_viewport_size({"width": width, "height": height})
                    for name, route, heading in visual_routes:
                        page.evaluate("route => { location.hash = route; }", route)
                        page.get_by_role("heading", name=heading, exact=True).wait_for()
                        page.wait_for_timeout(200)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{width} overflow: {name}"
                        if width == 2560:
                            chrome_gutter = page.locator(".topbar").evaluate("node => parseFloat(getComputedStyle(node).paddingLeft)")
                            assert chrome_gutter == wide_edges["topbarGutter"], f"Wide chrome moves on {name}"
                        if width <= 1100 and name == "measure":
                            wave_rail = page.locator(".wave-rail")
                            assert not wave_rail.evaluate("node => node.open"), f"{width} Wave rail should start collapsed"
                            rail_bottom = wave_rail.locator("summary").bounding_box()["y"] + wave_rail.locator("summary").bounding_box()["height"]
                            assert rail_bottom <= page.locator(".wave-summary").bounding_box()["y"] + 1
                        if width <= 900:
                            table_overflow = page.locator(".table-wrap:visible").evaluate_all("nodes => nodes.filter(node => node.scrollWidth > node.clientWidth + 1).length")
                            assert table_overflow == 0, f"{width} table overflow: {name}"
                        if 901 <= width <= 1100 and name == "admin":
                            engine_table = page.locator(".engine-table")
                            assert engine_table.evaluate("node => node.scrollWidth <= node.clientWidth + 1"), f"{width} engine table overflow"
                            cell_display = engine_table.locator("tbody td").first.evaluate("node => getComputedStyle(node).display")
                            assert cell_display == ("grid" if width <= 1000 else "table-cell"), f"{width} engine table mode: {cell_display}"
                            table_bounds = engine_table.bounding_box()
                            action_bounds = engine_table.locator("tbody td:last-child button").evaluate_all("nodes => nodes.map(node => { const rect = node.getBoundingClientRect(); return {left: rect.left, right: rect.right}; })")
                            assert all(table_bounds["x"] <= action["left"] and action["right"] <= table_bounds["x"] + table_bounds["width"] + 1 for action in action_bounds), f"{width} clipped engine actions: {action_bounds}"
                        if width == 768 and name == "prompts":
                            assert page.get_by_role("heading", name=heading, exact=True).bounding_box()["width"] >= 200, "Tablet page title is compressed by actions"
                        page.screenshot(path=OUTPUT / f"14-{name}-{width}.png", full_page=True)

                page.set_viewport_size({"width": 847, "height": 900})
                page.evaluate("location.hash = '#/measure'")
                page.get_by_role("heading", name="测量执行", exact=True).wait_for()
                page.locator(".protocol-details summary").click()
                popup = page.locator(".protocol-details dl").bounding_box()
                sidebar = page.locator("#sidebar").bounding_box()
                assert popup["x"] >= sidebar["x"] + sidebar["width"], "Protocol popup is hidden behind the sidebar"
                page.screenshot(path=OUTPUT / "14-protocol-847.png", full_page=True)
                page.locator(".protocol-details summary").click()

                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#main-nav a[href='#/overview']").evaluate("node => node.click()")
                page.wait_for_selector(".stage-panel")
                page.wait_for_function("""() => {
                  const sidebar = document.getElementById('sidebar');
                  const transform = new DOMMatrix(getComputedStyle(sidebar).transform);
                  return !sidebar.classList.contains('open') && Math.abs(transform.m41 + sidebar.offsetWidth) < 1;
                }""")
                assert page.locator("#menu-button").get_attribute("aria-expanded") == "false"
                assert page.locator("#sidebar").evaluate("node => node.inert")
                assert page.locator("#main-nav a").first.evaluate("node => { node.focus(); return document.activeElement !== node; }")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=OUTPUT / "08-overview-mobile.png", full_page=True)
                page.get_by_role("button", name="打开导航").click()
                assert page.locator("#sidebar").evaluate("node => node.classList.contains('open') && !node.inert")
                assert page.locator(".shell-main").evaluate("node => node.inert")
                page.get_by_role("button", name="关闭导航", exact=True).click()
                page.wait_for_function("!document.getElementById('sidebar').classList.contains('open')")
                assert page.locator("#sidebar").evaluate("node => node.inert")
                assert not page.locator(".shell-main").evaluate("node => node.inert")
                page.get_by_role("button", name="打开导航").click()
                page.keyboard.press("Escape")
                assert page.locator("#menu-button").evaluate("node => document.activeElement === node")
                page.get_by_role("button", name="打开导航").click()
                page.locator("#main-nav a[href='#/review']").click()
                page.get_by_label("复核状态", exact=True).select_option("all")
                page.get_by_label("回答状态", exact=True).select_option("succeeded")
                page.locator(".evidence-browser .list-item").first.click()
                page.wait_for_selector(".raw-answer")
                page.get_by_text("调用、模型与 Judge 元数据", exact=True).click()
                metadata_cells = page.locator(".advanced:visible .table-wrap td")
                assert metadata_cells.count() > 0
                assert metadata_cells.evaluate_all("nodes => nodes.every(node => node.dataset.label && node.dataset.label !== 'undefined')")
                for parameter in ("run=", "answer=", "status=", "review=all"):
                    assert parameter in page.url
                small_heights = page.locator(".button.small-button:visible").evaluate_all("nodes => nodes.map(node => node.getBoundingClientRect().height)")
                assert small_heights and all(height >= 44 for height in small_heights)
                assert page.locator("#menu-button").bounding_box()["height"] >= 44
                page.wait_for_function("""() => {
                  const sidebar = document.getElementById('sidebar');
                  const transform = new DOMMatrix(getComputedStyle(sidebar).transform);
                  return !sidebar.classList.contains('open') && Math.abs(transform.m41 + sidebar.offsetWidth) < 1;
                }""")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(150)
                page.screenshot(path=OUTPUT / "09-review-mobile.png", full_page=True)
                page.get_by_role("button", name="返回回答清单", exact=True).click()
                page.locator(".evidence-browser:not(.has-detail) .list-rail").wait_for()
                assert "answer=" not in page.url and "run=" in page.url and "status=succeeded" in page.url and "review=all" in page.url
                assert not page.locator(".evidence-browser .detail-pane").is_visible()
                page.screenshot(path=OUTPUT / "09a-review-list-mobile.png", full_page=True)

                for name, route, heading in visual_routes:
                    if name in ("overview", "review"):
                        continue
                    page.evaluate("route => { location.hash = route; }", route)
                    page.get_by_role("heading", name=heading, exact=True).wait_for()
                    page.wait_for_timeout(200)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"390 overflow: {name}"
                    control_heights = page.locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden]):visible,select:visible,textarea:visible").evaluate_all("nodes => nodes.map(node => node.getBoundingClientRect().height)")
                    assert all(height >= 44 for height in control_heights), f"390 control target: {name}: {control_heights}"
                    link_heights = page.locator(".table-link:visible").evaluate_all("nodes => nodes.map(node => node.getBoundingClientRect().height)")
                    assert all(height >= 44 for height in link_heights), f"390 link target: {name}"
                    if name == "measure":
                        assert not page.locator(".wave-rail").evaluate("node => node.open")
                    page.screenshot(path=OUTPUT / f"12-{name}-mobile.png", full_page=True)
                visible_tabs = page.locator(".tabs button").evaluate_all("nodes => nodes.map(node => { const rect = node.getBoundingClientRect(); return {left: rect.left, right: rect.right}; })")
                assert all(tab["left"] >= 0 and tab["right"] <= 390 for tab in visible_tabs), "Mobile tabs are clipped"
                page.get_by_role("button", name="检查演示引擎", exact=True).click()
                page.get_by_role("button", name="确认并检查", exact=True).click()
                page.locator("#toast.show").wait_for()
                assert "null" not in page.locator("#toast").inner_text()
                assert page.locator("#toast .toast-close").count() == 0
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(150)
                primary = page.get_by_role("button", name="新增引擎", exact=True).bounding_box()
                notice = page.locator("#toast").bounding_box()
                assert primary["y"] >= notice["y"] + notice["height"], "Mobile toast covers the primary action"
                page.screenshot(path=OUTPUT / "13-mobile-toast.png", full_page=True)

                page.set_viewport_size({"width": 1280, "height": 900})
                page.evaluate("location.hash = '#/admin?tab=members'")
                page.get_by_text("项目成员", exact=True).wait_for()
                for role in ("viewer", "reviewer", "analyst"):
                    email = f"{role}@browser.local"
                    password = f"{role}-browser-password"
                    page.get_by_role("button", name="新建用户", exact=True).click()
                    page.get_by_label("邮箱", exact=True).fill(email)
                    page.get_by_label("初始密码", exact=True).fill(password)
                    page.get_by_role("button", name="创建用户", exact=True).click()
                    page.get_by_text("用户已创建，请继续分配项目角色", exact=True).wait_for()
                    page.get_by_role("button", name="分配 / 调整角色", exact=True).click()
                    page.get_by_label("用户", exact=True).select_option(label=email)
                    page.get_by_label("项目角色", exact=True).select_option(role)
                    page.get_by_role("button", name="保存项目角色", exact=True).click()
                    page.get_by_text("成员角色已保存", exact=True).wait_for()
                    role_page = browser.new_page(viewport={"width": 1280, "height": 900})
                    role_errors = []
                    role_page.on("pageerror", lambda error, caught=role_errors: caught.append(f"pageerror: {error.stack or error}"))
                    role_page.on("console", lambda message, caught=role_errors: caught.append(f"console: {message.text}") if message.type == "error" else None)
                    role_page.goto(base, wait_until="networkidle")
                    role_page.get_by_label("邮箱").fill(email)
                    role_page.get_by_label("密码").fill(password)
                    role_page.get_by_role("button", name="登录", exact=True).click()
                    role_page.wait_for_selector(".stage-panel")
                    role_errors.clear()
                    assert role_page.get_by_role("button", name="新建测量方案", exact=True).count() == 0
                    role_page.locator("#main-nav a[href='#/prompts']").click()
                    role_page.get_by_role("heading", name="问题集工作台", exact=True).wait_for()
                    expected_edit_count = 1 if role == "analyst" else 0
                    for action in ("新建草稿", "生成候选题", "导入 JSON / CSV", "进入审核"):
                        expected_count = 0 if action == "进入审核" else expected_edit_count
                        assert role_page.get_by_role("button", name=action, exact=True).count() == expected_count
                    frozen_option = role_page.get_by_label("选择问题集版本", exact=True).locator("option").evaluate_all("nodes => nodes.find(node => node.textContent.includes('已冻结')).value")
                    role_page.get_by_label("选择问题集版本", exact=True).select_option(frozen_option)
                    role_page.get_by_role("heading", name="这是不可变测量版本", exact=True).wait_for()
                    assert role_page.get_by_role("button", name="复制为新版本", exact=True).count() == expected_edit_count
                    role_page.locator("#main-nav a[href='#/review']").click()
                    role_page.get_by_label("复核状态", exact=True).select_option("all")
                    role_page.wait_for_selector(".observation")
                    if role == "analyst":
                        assert role_page.locator(".raw-answer").count() == 1
                        assert role_page.get_by_text("原文不可见", exact=True).count() == 0
                    else:
                        assert role_page.locator(".raw-answer").count() == 0
                        assert role_page.get_by_text("原文不可见", exact=True).count() > 0
                    assert (role_page.get_by_role("button", name="新增人工修订", exact=True).count() > 0) == (role == "analyst")
                    answer = role_page.request.get(f"{base}/api/projects/1/answers/1").json()
                    if role == "analyst":
                        assert answer["raw_text"] is not None
                        assert all("cost" in attempt for attempt in answer["call_attempts"])
                    else:
                        assert answer["raw_text"] is None and answer["error_detail"] is None
                        assert all("cost" not in attempt for attempt in answer["call_attempts"])
                    role_page.locator("#main-nav a[href='#/reports']").click()
                    role_page.get_by_role("tab", name=re.compile(r"^报告交付")).click()
                    role_page.locator(f"button[data-report-id='{report_id}']").click()
                    role_page.get_by_text(f"报告 v{report['version']} · 客户版已批准", exact=True).wait_for()
                    assert (role_page.get_by_role("button", name="预览内部版", exact=True).count() == 1) == (role == "analyst")
                    assert (role_page.get_by_role("link", name="下载内部版 PDF", exact=True).count() == 1) == (role == "analyst")
                    role_page.locator("#main-nav a[href='#/concepts']").click()
                    role_page.get_by_role("heading", name="常见概念", exact=True).wait_for()
                    assert role_page.locator(".work-section table").count() == 4
                    report_data = role_page.request.get(f"{base}/api/projects/1/reports/{report_id}").json()
                    if role == "analyst":
                        assert "internal_samples" in report_data["snapshot"]
                    else:
                        assert "costs" not in report_data["snapshot"] and "internal_samples" not in report_data["snapshot"]
                    role_page.locator("#main-nav a[href='#/admin']").click()
                    role_page.get_by_text("测量目标配置", exact=True).wait_for()
                    assert role_page.get_by_role("tab", name="成员与角色", exact=True).count() == 0
                    assert (role_page.get_by_role("tab", name="成本与运营", exact=True).count() == 1) == (role == "analyst")
                    role_page.screenshot(path=OUTPUT / f"10-{role}-desktop.png", full_page=True)
                    role_page.close()
                    if role_errors:
                        raise AssertionError(f"{role} browser errors:\n" + "\n".join(role_errors))
                browser.close()
                if errors:
                    raise AssertionError("Browser console errors:\n" + "\n".join(errors))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            log.close()
    print(json.dumps({
        "status": "passed", "screenshots": str(OUTPUT), "workflows": 8,
        "comparison": "strict", "roles": ["viewer", "reviewer", "analyst"], "mobile": True,
        "action_workflow": "cohort_remeasurement_insufficient_evidence", "governance": ["schedule", "backup", "export", "project_delete"],
        "pdf": "client-report.pdf",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
