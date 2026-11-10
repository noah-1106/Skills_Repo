#!/usr/bin/env python3
"""Browser verification for budget, scheduler, alert, retention and work-log UI."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from browser_smoke import PASSWORD, seed_official_run, wait_server
from browser_support import call

OUTPUT = ROOT / "test-results" / "browser-governance"


def save_settings(page):
    page.get_by_role("button", name="保存项目设置", exact=True).click()
    page.get_by_text("项目设置已保存，已有 Wave 未改变", exact=True).wait_for()


def open_governance(page):
    page.locator("#main-nav a[href='#/admin']").click()
    page.get_by_role("tab", name="设置与数据治理", exact=True).click()
    page.get_by_text("后续测量与执行默认值", exact=True).wait_for()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geopulse-governance-browser-") as temporary:
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
                page = browser.new_page(viewport={"width": 1280, "height": 900}, timezone_id="America/New_York")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
                page.get_by_label("邮箱").fill("admin@browser.local")
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录", exact=True).click()
                page.wait_for_selector(".stage-panel")
                errors.clear()
                datetime_checks = page.evaluate("""async () => {
                  const {fromDateTimeLocal, toDateTimeLocal, dateInTimezone} = await import('/static/datetime.js');
                  const failure = (value, zone) => {
                    try { fromDateTimeLocal(value, zone); return ''; } catch (error) { return error.message; }
                  };
                  return {
                    shanghai: fromDateTimeLocal('2026-01-15T10:00', 'Asia/Shanghai'),
                    roundTrip: toDateTimeLocal('2026-01-15T02:00:00Z', 'Asia/Shanghai'),
                    date: dateInTimezone('Asia/Shanghai', new Date('2026-11-09T16:30:00Z')),
                    invalid: failure('2026-02-30T10:00', 'Asia/Shanghai'),
                    skipped: failure('2026-03-08T02:30', 'America/New_York'),
                    repeated: failure('2026-11-01T01:30', 'America/New_York'),
                  };
                }""")
                assert datetime_checks["shanghai"] == "2026-01-15T02:00:00.000Z"
                assert datetime_checks["roundTrip"] == "2026-01-15T10:00"
                assert datetime_checks["date"] == "2026-11-10"
                assert "无效" in datetime_checks["invalid"]
                assert "跳时" in datetime_checks["skipped"]
                assert "重复" in datetime_checks["repeated"]
                assert page.evaluate("new Date('2026-01-15T10:00').toISOString()") != datetime_checks["shanghai"]

                page.locator("#main-nav a[href='#/admin']").click()
                page.get_by_role("button", name="新增引擎", exact=True).click()
                page.get_by_label("配置名称", exact=True).fill("预算测试引擎")
                page.get_by_label("厂商 / 产品", exact=True).fill("Offline Test")
                page.get_by_label("模型 ID", exact=True).fill("budget-model")
                page.get_by_label("Base URL", exact=True).fill("https://example.test/v1")
                page.get_by_label("API Key", exact=True).fill("browser-offline-not-a-credential")
                page.get_by_text("价格与调用预估", exact=True).click()
                page.get_by_label("回答输入价 / 百万 tokens", exact=True).fill("10")
                page.get_by_label("回答输出价 / 百万 tokens", exact=True).fill("20")
                page.get_by_role("button", name="保存测量目标", exact=True).click()
                page.get_by_text("引擎配置已保存，密钥未回显", exact=True).wait_for()

                open_governance(page)
                hard_limit = page.get_by_label("启用硬限额", exact=False)
                assert hard_limit.is_disabled()
                assert hard_limit.evaluate("node => node.closest('.check-field').classList.contains('control-disabled')")
                page.get_by_label("启用预算检查", exact=False).check()
                assert not hard_limit.is_disabled()
                page.get_by_label("项目累计额度", exact=True).fill("0.01")
                page.get_by_label("单 Wave 额度", exact=True).fill("100")
                page.get_by_label("每日额度", exact=True).fill("100")
                save_settings(page)

                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_role("button", name="新建测量方案", exact=True).click()
                page.get_by_label("Wave 名称", exact=True).fill("浏览器预算 Wave")
                page.locator(".check-field label").filter(has_text="预算测试引擎").click()
                held_waves = []
                def hold_wave_post(route):
                    if route.request.method == "POST": held_waves.append(route)
                    else: route.continue_()
                page.route("**/api/projects/1/waves", hold_wave_post)
                page.get_by_role("button", name="创建方案并查看预估", exact=True).click()
                for _ in range(100):
                    if held_waves: break
                    time.sleep(0.05)
                assert len(held_waves) == 1
                wave_form = page.locator("form[aria-busy='true']")
                wave_form.wait_for()
                assert wave_form.get_by_role("button", name="创建方案并查看预估", exact=True).is_disabled()
                wave_form.evaluate("node => node.requestSubmit()")
                assert len(held_waves) == 1
                held_waves.pop().continue_()
                page.unroute("**/api/projects/1/waves", hold_wave_post)
                try:
                    page.get_by_text("调用与费用预估", exact=True).wait_for(timeout=5000)
                except Exception as error:
                    raise RuntimeError(f"Wave estimate diagnostics: {page.get_by_role('dialog').inner_text()}") from error
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null"), "Wave estimate loses dialog focus"
                held_runs = []
                def hold_run_post(route):
                    if route.request.method == "POST": held_runs.append(route)
                    else: route.continue_()
                page.route("**/api/projects/1/waves/*/runs", hold_run_post)
                page.get_by_role("button", name="确认调用并创建 Run", exact=True).click()
                for _ in range(100):
                    if held_runs: break
                    time.sleep(0.05)
                assert len(held_runs) == 1
                estimate_form = page.locator("form[aria-busy='true']")
                assert estimate_form.get_by_role("button", name="确认调用并创建 Run", exact=True).is_disabled()
                estimate_form.evaluate("node => node.requestSubmit()")
                assert len(held_runs) == 1
                held_runs.pop().continue_()
                page.unroute("**/api/projects/1/waves/*/runs", hold_run_post)
                page.get_by_role("dialog").filter(has_text="预算超限确认").wait_for()
                page.get_by_label("超限执行理由", exact=True).fill("浏览器验收：管理员确认本次软预算超限")
                page.get_by_role("button", name="确认超限并继续", exact=True).click()
                page.get_by_text("Run 已进入持久队列", exact=True).wait_for()
                page.get_by_text("浏览器预算 Wave", exact=True).first.wait_for()
                runs = call(page, "get", "/api/projects/1/waves")["items"]
                budget_wave = next(item for item in runs if item["label"] == "浏览器预算 Wave")
                queued_run = budget_wave["runs"][0]
                assert queued_run["status"] == "queued"
                from backend.app.db import connect, one
                with connect() as conn:
                    reservation = one(conn, "SELECT * FROM budget_reservations WHERE run_id=? AND status='active'", (queued_run["id"],))
                    assert reservation and "浏览器验收" in reservation["confirmed_reason"]

                open_governance(page)
                page.get_by_label("启用硬限额", exact=False).check()
                save_settings(page)
                page.locator("#main-nav a[href='#/measure']").click()
                page.get_by_role("button", name="创建重试 Run", exact=True).click()
                page.get_by_role("button", name="确认并进入队列", exact=True).click()
                page.get_by_text("硬预算", exact=False).wait_for()
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)
                page.screenshot(path=OUTPUT / "01-hard-budget.png")
                page.get_by_role("button", name="关闭对话框", exact=True).click()
                call(page, "post", f"/api/projects/1/runs/{queued_run['id']}/cancel", {})

                past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
                schedule = call(page, "post", "/api/projects/1/schedules", {"wave_id": budget_wave["id"], "scheduled_at": past, "recurrence_days": 7})
                from backend.app.services.scheduler import run_due_schedules
                run_due_schedules()
                page.locator("#main-nav a[href='#/admin']").click()
                import re
                page.get_by_role("tab", name=re.compile(r"^调度与告警")).click()
                page.get_by_text("已阻塞", exact=True).wait_for()
                page.get_by_text("硬预算", exact=False).first.wait_for()
                page.get_by_role("button", name="确认已知悉", exact=True).first.click()
                page.get_by_text("告警已确认", exact=True).wait_for()
                page.get_by_role("button", name="查看告警历史", exact=True).click()
                page.get_by_role("dialog").get_by_text("已知悉", exact=True).wait_for()
                page.get_by_role("button", name="关闭对话框", exact=True).click()
                page.screenshot(path=OUTPUT / "02-blocked-schedule.png", full_page=True)

                open_governance(page)
                page.get_by_label("项目累计额度", exact=True).fill("1000")
                page.get_by_label("启用硬限额", exact=False).uncheck()
                save_settings(page)
                page.get_by_role("tab", name=re.compile(r"^调度与告警")).click()
                page.get_by_role("button", name="处理后再试", exact=True).click()
                page.get_by_role("button", name="暂停", exact=True).first.click()
                page.get_by_text("已暂停", exact=True).first.wait_for()
                page.get_by_role("button", name="恢复", exact=True).first.click()
                page.get_by_text("待执行", exact=True).first.wait_for()

                with connect() as conn:
                    conn.execute("UPDATE answers SET completed_at='2020-01-01T00:00:00+00:00' WHERE id=(SELECT id FROM answers WHERE run_id=1 AND status='succeeded' LIMIT 1)")
                    conn.commit()
                open_governance(page)
                page.get_by_label("原文保留天数", exact=True).fill("30")
                save_settings(page)
                page.get_by_text("当前有 1 条到期原文", exact=False).wait_for()
                page.get_by_role("button", name="预览并清理到期原文", exact=True).click()
                page.get_by_role("button", name="确认清理原文", exact=True).click()
                page.get_by_text("已清理 1 条原文", exact=True).wait_for()
                page.get_by_text("当前有 0 条到期原文", exact=False).wait_for()
                page.screenshot(path=OUTPUT / "03-retention-governance.png", full_page=True)

                page.get_by_role("tab", name=re.compile(r"^调度与告警")).click()
                page.get_by_role("button", name="安排复测", exact=True).click()
                page.get_by_label("执行频率", exact=True).select_option("14")
                scheduled_control = page.get_by_label("下次执行时间", exact=True)
                help_id = scheduled_control.get_attribute("aria-describedby")
                assert help_id and "Asia/Shanghai" in page.locator(f"#{help_id}").inner_text()
                scheduled_control.fill("2027-01-15T10:00")
                page.get_by_role("button", name="保存调度", exact=True).click()
                page.get_by_text("复测调度已保存", exact=True).wait_for()
                saved_schedules = call(page, "get", "/api/projects/1/schedules")["items"]
                saved_schedule = next(item for item in saved_schedules if item["scheduled_at"].startswith("2027-01-15"))
                assert datetime.fromisoformat(saved_schedule["scheduled_at"].replace("Z", "+00:00")) == datetime(2027, 1, 15, 2, 0, tzinfo=timezone.utc)

                page.get_by_role("tab", name="成本与运营", exact=True).click()
                date_before = page.evaluate("async () => (await import('/static/datetime.js')).dateInTimezone('Asia/Shanghai')")
                page.get_by_role("button", name="记录工时", exact=True).click()
                date_after = page.evaluate("async () => (await import('/static/datetime.js')).dateInTimezone('Asia/Shanghai')")
                assert page.get_by_label("业务日期", exact=True).input_value() in {date_before, date_after}
                page.get_by_label("业务日期", exact=True).fill("2026-11-01")
                page.get_by_label("工时", exact=True).fill("1.5")
                page.get_by_label("说明", exact=True).fill("浏览器手工工时验收")
                page.get_by_role("button", name="保存工时", exact=True).click()
                page.get_by_text("工时已记录", exact=True).wait_for()
                page.get_by_text("2026-11-01", exact=True).wait_for()
                page.get_by_text("1.5", exact=True).wait_for()

                first_tab = page.get_by_role("tab", name="引擎与口径", exact=True)
                first_tab.focus()
                first_tab.press("ArrowRight")
                page.wait_for_function("""() => document.activeElement?.getAttribute('role') === 'tab'
                    && document.activeElement?.getAttribute('aria-selected') === 'true'
                    && document.activeElement?.textContent.includes('调度与告警')""")
                page.locator("[role=tabpanel]").wait_for(state="visible")
                assert page.evaluate("document.activeElement.getAttribute('role')") == "tab"
                assert page.locator("[role=tabpanel]").count() == 1
                first_tab.press("Enter")
                page.wait_for_function("""() => document.activeElement?.getAttribute('role') === 'tab'
                    && document.activeElement?.getAttribute('aria-selected') === 'true'
                    && document.activeElement?.textContent.includes('引擎与口径')""")
                page.get_by_role("tab", name=re.compile(r"^调度与告警")).focus()
                page.keyboard.press("Space")
                page.wait_for_function("""() => document.activeElement?.getAttribute('role') === 'tab'
                    && document.activeElement?.getAttribute('aria-selected') === 'true'
                    && document.activeElement?.textContent.includes('调度与告警')""")
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("() => !document.getElementById('toast').classList.contains('show')")
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=OUTPUT / "04-admin-mobile.png", full_page=True)
                page.get_by_role("button", name="打开导航").click()
                last_nav = page.locator("#main-nav a").last
                last_nav.focus()
                last_nav.press("Tab")
                assert page.locator("#main-nav a").first.evaluate("node => document.activeElement === node")
                page.keyboard.press("Shift+Tab")
                assert last_nav.evaluate("node => document.activeElement === node")
                page.keyboard.press("Escape")
                page.set_viewport_size({"width": 1280, "height": 900})
                page.wait_for_function("() => !document.getElementById('sidebar').inert")
                page.emulate_media(reduced_motion="reduce")
                page.get_by_role("tab", name="成本与运营", exact=True).click()
                page.get_by_role("button", name="记录工时", exact=True).click()
                durations = page.evaluate("""() => ['.drawer', '.toast', '.sidebar'].map(selector => {
                  const style = getComputedStyle(document.querySelector(selector));
                  return {selector, transition: style.transitionDuration, animation: style.animationDuration};
                })""")
                assert all(row["transition"] == "0s" and row["animation"] == "0s" for row in durations)
                page.evaluate("async () => { const {toast} = await import('/static/components.js'); toast('离线错误提示验收', true); }")
                error_toast = page.locator("#toast.show.error")
                error_toast.wait_for()
                assert error_toast.get_attribute("role") == "alert"
                assert error_toast.get_attribute("aria-live") == "assertive"
                layers = page.evaluate("""() => ({
                  toast: Number(getComputedStyle(document.getElementById('toast')).zIndex),
                  drawer: Number(getComputedStyle(document.querySelector('.drawer-backdrop')).zIndex),
                })""")
                assert layers["toast"] < layers["drawer"]
                page.get_by_role("button", name="关闭对话框", exact=True).click()
                page.get_by_role("button", name="关闭提示", exact=True).click()
                assert page.locator("#toast.show").count() == 0
                page.locator("#main-nav a[href='#/measure']").click()
                page.locator(".progress-bar").wait_for()
                assert page.locator(".progress-bar").evaluate("node => getComputedStyle(node).transitionDuration") == "0s"
                browser.close()
                if errors:
                    raise AssertionError("Browser errors:\n" + "\n".join(errors))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            log.close()
    print(json.dumps({"status": "passed", "screenshots": str(OUTPUT), "checks": [
        "structured_engine_prices", "soft_budget_reason", "hard_budget_rejection", "schedule_blocked_resume",
        "alert_ack_history", "retention_preview_execute", "manual_work_log", "tabs_keyboard", "mobile_overflow",
        "navigation_focus_trap", "reduced_motion",
    ]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
