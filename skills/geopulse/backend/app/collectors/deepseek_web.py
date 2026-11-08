"""DeepSeek Consumer Web selectors and interaction contract."""
from __future__ import annotations

import re

from .base import BrowserCapture, BrowserDriver, CollectorError


class DeepSeekWebDriver(BrowserDriver):
    key = "deepseek_web"
    version = "2026-11-08.1"
    origins = frozenset({"chat.deepseek.com", "account.deepseek.com", "auth.deepseek.com"})

    COMPOSERS = ("textarea", "[contenteditable='true'][data-testid='chat-input']")
    ANSWERS = "[data-testid='assistant-message'], .ds-markdown"
    STREAMING = "[data-testid='stop-generation'], button[aria-label*='停止'], button[aria-label*='Stop']"
    SEND = "[data-testid='send-button'], button[aria-label*='发送'], button[aria-label*='Send']"

    def _composer(self):
        for selector in self.COMPOSERS:
            locator = self.page.locator(selector)
            if locator.count() and locator.first.is_visible():
                return locator.first
        raise CollectorError("login_expired", "未找到可用的 DeepSeek 对话输入区，请在浏览器中重新登录", user_action=True)

    def _answers(self):
        return self.page.locator(self.ANSWERS)

    def check_session(self) -> None:
        self.ensure_origin(self.page.url)
        if self.page.locator("iframe[src*='captcha'], [class*='captcha']").count():
            raise CollectorError("captcha", "DeepSeek 页面需要安全验证，请由用户在可见浏览器中完成", user_action=True)
        self._composer()

    def prepare_new_chat(self) -> None:
        self.open_product()
        self.check_session()
        new_chat = self.page.get_by_role("button", name=re.compile("新对话|New chat"))
        if new_chat.count() and new_chat.first.is_visible():
            new_chat.first.click()
        self._composer().wait_for(state="visible")
        self._answer_count = self._answers().count()

    def _switch(self, name: str, desired: bool) -> None:
        control = self.page.get_by_role("button", name=re.compile(name)).first
        if not control.count():
            raise CollectorError("driver_incompatible", f"无法确认 DeepSeek 的{name}开关")
        state = control.get_attribute("aria-pressed")
        if state is None:
            state = control.get_attribute("data-active")
        if state is None:
            classes = (control.get_attribute("class") or "").lower()
            if "active" in classes or "selected" in classes:
                state = "true"
            elif classes:
                state = "false"
        if state is None:
            raise CollectorError("driver_incompatible", f"DeepSeek 的{name}状态不可核验")
        current = state.lower() in ("true", "1", "active")
        if current != desired:
            control.click()
            updated = control.get_attribute("aria-pressed") or control.get_attribute("data-active")
            if updated is not None and (updated.lower() in ("true", "1", "active")) != desired:
                raise CollectorError("driver_incompatible", f"DeepSeek 的{name}未能切换到冻结状态")

    def apply_frozen_mode(self) -> None:
        if self.protocol.get("deep_research"):
            raise CollectorError("driver_incompatible", "DeepSeek Web Driver 尚未支持冻结 deep_research 模式")
        self._switch("联网搜索", bool(self.protocol.get("networking")))
        self._switch("深度思考", bool(self.protocol.get("deep_thinking")))
        mode = str(self.protocol.get("page_mode") or "default")
        if mode != "default" and not self.page.get_by_text(mode, exact=False).count():
            raise CollectorError("driver_incompatible", "页面未显示冻结的 DeepSeek 模型/模式")

    def submit_prompt(self, prompt: str) -> None:
        composer = self._composer()
        composer.fill(prompt)
        send = self.page.locator(self.SEND)
        if send.count() and send.first.is_enabled():
            send.first.click()
        else:
            composer.press("Enter")

    def wait_for_completion(self) -> None:
        self.wait_stable(self._answers(), self.page.locator(self.STREAMING), self._answer_count)

    def extract_result(self) -> BrowserCapture:
        answers = self._answers()
        if answers.count() <= self._answer_count:
            raise CollectorError("empty", "DeepSeek 页面没有出现新的回答")
        answer = answers.nth(answers.count() - 1)
        text = answer.inner_text()
        citations = []
        for link in answer.locator("a[href]").all():
            citations.append({"url": link.get_attribute("href") or "", "title": link.inner_text(),
                              "text": link.inner_text()})
        return self.capture(answer, text, citations)
