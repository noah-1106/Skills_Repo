#!/usr/bin/env python3
"""Real-browser critical-path smoke test with an isolated DB and dynamic port."""
from __future__ import annotations

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
    from backend.app.migrations import initialize
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
        seed_official_run()
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
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.get_by_text("项目总览", exact=True).first.wait_for()
                page.wait_for_selector(".stage-panel")
                page.screenshot(path=OUTPUT / "01-overview-desktop.png", full_page=True)
                errors.clear()  # initial /auth/me 401 is the expected logged-out bootstrap

                page.locator("#main-nav a[href='#/prompts']").click()
                page.get_by_role("button", name="新建草稿", exact=True).click()
                page.get_by_label("问题集名称").fill("浏览器新问题集")
                page.get_by_role("button", name="创建草稿", exact=True).click()
                page.get_by_role("button", name="生成候选题", exact=True).wait_for()
                page.get_by_role("button", name="生成候选题", exact=True).click()
                page.get_by_role("button", name="预览 16 条候选题", exact=True).click()
                page.get_by_role("button", name="加入当前草稿", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "02-prompt-scaffold.png", full_page=True)
                page.get_by_role("button", name="加入当前草稿", exact=True).click()
                page.get_by_text("已加入 16 条，跳过 0 条重复", exact=True).wait_for()

                page.locator("#main-nav a[href='#/entities']").click()
                page.get_by_role("button", name="新增实体", exact=True).click()
                page.get_by_label("实体名称").fill("Browser <b>Entity</b>")
                page.get_by_label("别名", exact=True).fill("BrowserEntity")
                page.get_by_label("品类").fill("浏览器测试实体")
                page.get_by_role("button", name="保存为待审核草稿", exact=True).click()
                page.get_by_role("button", name="审核 Browser <b>Entity</b>", exact=True).click()
                page.get_by_label("消歧依据").fill("浏览器测试：官网、品类和别名已人工核对")
                page.get_by_role("button", name="保存审核决定", exact=True).click()
                page.get_by_text("实体审核已留痕", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "03-entities.png", full_page=True)
                assert page.get_by_text("Browser <b>Entity</b>", exact=True).count() > 0
                assert page.locator("b").filter(has_text="Entity").count() == 0

                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_text("浏览器验收基线", exact=True).first.wait_for()
                page.wait_for_selector(".metric-strip")
                page.screenshot(path=OUTPUT / "04-measure-desktop.png", full_page=True)

                page.locator("#main-nav a[href='#/review']").click()
                page.wait_for_selector(".raw-answer")
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
                page.get_by_text("浏览器七步事实页", exact=True).wait_for()
                page.get_by_role("button", name="待审核", exact=True).click()
                page.get_by_role("button", name="已批准", exact=True).wait_for()
                page.get_by_role("button", name="已批准", exact=True).click()
                page.get_by_role("button", name="登记真实发布", exact=True).wait_for()
                page.get_by_role("button", name="登记真实发布", exact=True).click()
                page.get_by_role("button", name="确认已发布并登记事件", exact=True).click()
                page.get_by_role("button", name="安排复测", exact=True).wait_for()
                page.get_by_role("button", name="安排复测", exact=True).click()
                page.get_by_role("button", name="进入待复测", exact=True).click()
                page.get_by_role("button", name="确认改善", exact=True).wait_for()
                page.get_by_role("button", name="确认改善", exact=True).click()
                page.get_by_label("复测结论依据", exact=True).fill("浏览器模拟复测证据，只记录共时变化，不作因果断言")
                page.get_by_role("dialog").get_by_role("button", name="已验证", exact=True).click()
                page.get_by_text("流程完成", exact=True).wait_for()
                page.wait_for_function("() => { const toast = document.getElementById('toast'); return !toast.classList.contains('show') && getComputedStyle(toast).opacity === '0'; }")
                page.screenshot(path=OUTPUT / "05b-action-complete.png", full_page=True)

                page.locator("#main-nav a[href='#/reports']").click()
                page.get_by_role("button", name="检查口径并比较", exact=True).click()
                page.get_by_text("协议与样本完整度通过", exact=True).wait_for()
                page.wait_for_selector(".chart canvas")
                assert page.get_by_text("持续提及", exact=True).count() > 0
                page.screenshot(path=OUTPUT / "06a-comparison-desktop.png", full_page=True)
                page.get_by_role("button", name="创建报告快照", exact=True).click()
                page.get_by_role("button", name="创建不可变快照", exact=True).click()
                page.get_by_text("报告 v1 · 草稿", exact=True).wait_for()
                for label in ("推进到数据已核验", "推进到策略已复核", "推进到客户版已批准"):
                    page.get_by_role("button", name=label, exact=True).click()
                    page.get_by_role("button", name="确认推进", exact=True).click()
                    page.wait_for_timeout(300)
                page.get_by_text("报告 v1 · 客户版已批准", exact=True).wait_for()
                pdf = page.request.get(f"{base}/api/projects/1/reports/1/export?variant=client&format=pdf")
                assert pdf.status == 200, pdf.text()
                assert pdf.body().startswith(b"%PDF")
                (OUTPUT / "client-report.pdf").write_bytes(pdf.body())
                page.wait_for_function("() => { const toast = document.getElementById('toast'); return !toast.classList.contains('show') && getComputedStyle(toast).opacity === '0'; }")
                page.screenshot(path=OUTPUT / "06-reports-desktop.png", full_page=True)

                page.locator("#main-nav a[href='#/admin']").click()
                page.wait_for_timeout(700)
                if not page.get_by_text("引擎配置", exact=True).count():
                    raise RuntimeError(f"Admin diagnostics: {errors}; body={page.locator('body').inner_text()}")
                page.get_by_text("引擎配置", exact=True).wait_for()
                page.screenshot(path=OUTPUT / "07-admin-desktop.png", full_page=True)
                page.get_by_role("tab", name="调度与告警").click()
                page.get_by_text("Wave 调度", exact=True).wait_for()
                page.get_by_role("button", name="安排复测", exact=True).click()
                page.get_by_label("复测锚点", exact=True).select_option("14")
                page.get_by_role("button", name="保存调度", exact=True).click()
                page.get_by_text("复测调度已保存", exact=True).wait_for()
                page.get_by_text("待执行", exact=True).wait_for()
                page.get_by_role("tab", name="成本与运营").click()
                page.get_by_text("分调用类型成本", exact=True).wait_for()
                page.get_by_role("tab", name="设置与数据治理").click()
                with page.expect_download() as backup_download:
                    page.get_by_role("button", name="立即备份数据库", exact=True).click()
                backup_manifest = json.loads(Path(backup_download.value.path()).read_text(encoding="utf-8"))
                assert backup_manifest["sha256"] and backup_manifest["schema_version"] == 1
                with page.expect_download() as export_download:
                    page.get_by_role("button", name="导出当前项目", exact=True).click()
                exported = json.loads(Path(export_download.value.path()).read_text(encoding="utf-8"))
                assert exported["sha256"] and exported["project_id"] == 1
                assert all(not row["secret_ref"] for row in exported["tables"]["engine_configs"])

                page.get_by_role("button", name="新建项目", exact=True).click()
                page.get_by_label("客户名称", exact=True).fill("第二测试客户")
                page.get_by_label("项目名称", exact=True).fill("待删除隔离项目")
                page.get_by_label("业务品类", exact=True).fill("隔离测试")
                page.get_by_role("button", name="创建项目", exact=True).click()
                page.get_by_text("品牌实体工作台", exact=True).wait_for()
                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("tab", name="设置与数据治理").click()
                page.get_by_role("button", name="删除当前项目", exact=True).click()
                page.get_by_label("输入完整项目名确认", exact=True).fill("错误确认")
                page.get_by_role("button", name="永久删除项目", exact=True).click()
                page.get_by_text("项目名不完全一致", exact=True).wait_for()
                page.get_by_label("输入完整项目名确认", exact=True).fill("待删除隔离项目")
                with page.expect_navigation(wait_until="networkidle"):
                    page.get_by_role("button", name="永久删除项目", exact=True).click()
                page.get_by_role("heading", name="系统管理", exact=True).wait_for()
                assert page.get_by_label("切换客户项目").input_value() == "1"

                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#main-nav a[href='#/overview']").evaluate("node => node.click()")
                page.wait_for_selector(".stage-panel")
                page.wait_for_function("""() => {
                  const sidebar = document.getElementById('sidebar');
                  const transform = new DOMMatrix(getComputedStyle(sidebar).transform);
                  return !sidebar.classList.contains('open') && Math.abs(transform.m41 + sidebar.offsetWidth) < 1;
                }""")
                assert page.locator("#menu-button").get_attribute("aria-expanded") == "false"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=OUTPUT / "08-overview-mobile.png", full_page=True)
                page.get_by_role("button", name="打开导航").click()
                assert page.locator("#sidebar").evaluate("node => node.classList.contains('open')")
                assert page.locator(".shell-main").evaluate("node => node.inert")
                page.get_by_role("button", name="关闭导航", exact=True).click()
                page.wait_for_function("!document.getElementById('sidebar').classList.contains('open')")
                assert not page.locator(".shell-main").evaluate("node => node.inert")
                page.get_by_role("button", name="打开导航").click()
                page.locator("#main-nav a[href='#/review']").click()
                page.wait_for_selector(".raw-answer")
                page.wait_for_function("""() => {
                  const sidebar = document.getElementById('sidebar');
                  const transform = new DOMMatrix(getComputedStyle(sidebar).transform);
                  return !sidebar.classList.contains('open') && Math.abs(transform.m41 + sidebar.offsetWidth) < 1;
                }""")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=OUTPUT / "09-review-mobile.png", full_page=True)

                page.set_viewport_size({"width": 1280, "height": 900})
                page.evaluate("location.hash = '#/admin?tab=members'")
                page.get_by_text("项目成员", exact=True).wait_for()
                for role in ("viewer", "reviewer"):
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
                    role_page.locator("#main-nav a[href='#/review']").click()
                    role_page.wait_for_selector(".observation")
                    assert role_page.locator(".raw-answer").count() == 0
                    assert role_page.get_by_text("原文不可见", exact=True).count() > 0
                    assert role_page.get_by_role("button", name="新增人工修订", exact=True).count() == 0
                    answer = role_page.request.get(f"{base}/api/projects/1/answers/1").json()
                    assert answer["raw_text"] is None and answer["error_detail"] is None
                    assert all("cost" not in attempt for attempt in answer["call_attempts"])
                    role_page.locator("#main-nav a[href='#/reports']").click()
                    role_page.get_by_role("button", name="打开报告", exact=True).click()
                    role_page.get_by_text("报告 v1 · 客户版已批准", exact=True).wait_for()
                    assert role_page.get_by_role("button", name="预览内部版", exact=True).count() == 0
                    assert role_page.get_by_role("link", name="下载内部版 PDF", exact=True).count() == 0
                    report = role_page.request.get(f"{base}/api/projects/1/reports/1").json()
                    assert "costs" not in report["snapshot"] and "internal_samples" not in report["snapshot"]
                    role_page.locator("#main-nav a[href='#/admin']").click()
                    role_page.get_by_text("引擎配置", exact=True).wait_for()
                    assert role_page.get_by_role("tab", name="成员与角色", exact=True).count() == 0
                    assert role_page.get_by_role("tab", name="成本与运营", exact=True).count() == 0
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
        "comparison": "strict", "roles": ["viewer", "reviewer"], "mobile": True,
        "action_workflow": "verified", "governance": ["schedule", "backup", "export", "project_delete"],
        "pdf": "client-report.pdf",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
