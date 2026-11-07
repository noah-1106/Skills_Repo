"""Small shared browser contracts; business IDs are preferred over display text."""
from __future__ import annotations

import re


def call(page, method, path, body=None):
    return page.evaluate("""async ({method, path, body}) => {
      const {api} = await import('/static/api.js');
      return api[method](path, ...(body === null ? [] : [body]));
    }""", {"method": method, "path": path, "body": body})


class ReportsPage:
    def __init__(self, page, project_id=1):
        self.page = page
        self.project_id = project_id

    def open_delivery(self, wave_id=None):
        if wave_id is not None:
            self.page.evaluate("wave => { location.hash = `#/reports?wave=${wave}`; }", wave_id)
            try:
                self.page.locator("[role='tab'][aria-selected='true']", has_text="报告交付").wait_for()
            except Exception as error:
                raise AssertionError(f"报告深链未进入交付 tab：{self.page.url}\n{self.page.locator('body').inner_text()}") from error
            assert f"wave={wave_id}" in self.page.url
            return
        self.page.locator("#main-nav a[href='#/reports']").click()
        tab = self.page.get_by_role("tab", name=re.compile(r"^报告交付"))
        tab.wait_for()
        if tab.get_attribute("aria-selected") != "true":
            tab.click()
        assert tab.get_attribute("aria-selected") == "true"

    def create_snapshot(self, expected_wave_id):
        self.page.get_by_test_id("create-report").click()
        dialog = self.page.get_by_role("dialog", name="创建报告快照", exact=True)
        current = dialog.get_by_test_id("report-current-wave")
        assert current.input_value() == str(expected_wave_id), (
            f"默认报告 Wave 应为正式 Wave #{expected_wave_id}，实际为 #{current.input_value()}"
        )
        with self.page.expect_response(
            lambda response: response.url.endswith(f"/api/projects/{self.project_id}/reports")
            and response.request.method == "POST"
        ) as pending:
            dialog.get_by_role("button", name="创建不可变快照", exact=True).click()
        response = pending.value
        assert response.status == 200, response.text()
        report = response.json()
        assert report["wave_ids"] == [expected_wave_id]
        return report
