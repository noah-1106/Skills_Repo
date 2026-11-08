"""Shared browser-collector contracts; platform selectors live in separate drivers."""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


ACTUAL_CONTEXT_KEYS = {
    "surface", "page_mode", "networking", "deep_thinking", "deep_research", "session_mode",
    "login_state", "account_type", "region", "language", "context_clearing", "follow_up_policy",
}


class CollectorError(RuntimeError):
    def __init__(self, kind: str, detail: str, *, user_action: bool = False):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.user_action = user_action


@dataclass
class BrowserCapture:
    payload: dict
    screenshot: bytes
    html: bytes


class BrowserDriver:
    key = ""
    version = "1"
    origins: frozenset[str] = frozenset()

    def __init__(self, page, product_url: str, protocol: dict, timezone: str, timeout: int = 180):
        self.page = page
        self.product_url = product_url.rstrip("/")
        self.protocol = protocol
        self.timezone = timezone
        self.timeout = timeout
        self.heartbeat = lambda: None

    def ensure_origin(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.hostname.lower() not in self.origins):
            raise CollectorError("driver_incompatible", "页面跳转到未授权的产品 origin，已停止采集")

    def open_product(self):
        self.ensure_origin(self.product_url)
        self.page.goto(self.product_url, wait_until="domcontentloaded")
        self.ensure_origin(self.page.url)

    def conversation_url(self) -> str:
        self.ensure_origin(self.page.url)
        parsed = urllib.parse.urlparse(self.page.url)
        return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))

    def resume_conversation(self, url: str) -> None:
        self.ensure_origin(url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.ensure_origin(self.page.url)
        self._answer_count = 0

    def payload(self, text: str, citations: list[dict]) -> dict:
        context = {key: self.protocol[key] for key in ACTUAL_CONTEXT_KEYS if key in self.protocol}
        observed_at = datetime.now(ZoneInfo(self.timezone)).isoformat(timespec="seconds")
        return {
            "draft_text": text,
            "actual_url": self.conversation_url(),
            "observed_mode": str(self.protocol.get("page_mode") or "default"),
            "observed_at": observed_at,
            "timezone": self.timezone,
            "session_context": context,
            "retrieval_status": "on" if self.protocol.get("networking") else "off",
            "notes": "授权浏览器自动采集；页面引用未做正文支持关系核验",
            "citations": citations,
            "status": "review_pending",
        }

    def capture(self, locator, text: str, citations: list[dict]) -> BrowserCapture:
        if not text.strip():
            raise CollectorError("empty", "页面回答正文为空，未形成有效样本")
        clean_citations = []
        for item in citations:
            parsed = urllib.parse.urlparse(item.get("url") or "")
            if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password:
                clean_citations.append({"url": item["url"], "title": item.get("title") or "",
                                        "text": item.get("text") or ""})
        try:
            screenshot = locator.screenshot(type="png")
            html = locator.evaluate("element => element.outerHTML").encode("utf-8")
        except Exception as error:
            raise CollectorError("driver_incompatible", "无法截取当前回答区域证据") from error
        return BrowserCapture(self.payload(text, clean_citations), screenshot, html)

    def wait_stable(self, locator, streaming, previous_count: int) -> None:
        deadline = time.monotonic() + self.timeout
        stable = 0
        last_text = None
        while time.monotonic() < deadline:
            self.heartbeat()
            count = locator.count()
            if count > previous_count and streaming.count() == 0:
                text = locator.nth(count - 1).inner_text()
                if text.strip() and text == last_text:
                    stable += 1
                    if stable >= 3:
                        return
                else:
                    stable = 0
                last_text = text
            else:
                stable = 0
            self.page.wait_for_timeout(500)
        raise CollectorError("stream_interrupted", "等待网页回答完成超时；请核对原会话后再恢复，不会自动重发")

    def check_session(self) -> None:
        raise NotImplementedError

    def prepare_new_chat(self) -> None:
        raise NotImplementedError

    def apply_frozen_mode(self) -> None:
        raise NotImplementedError

    def submit_prompt(self, prompt: str) -> None:
        raise NotImplementedError

    def wait_for_completion(self) -> None:
        raise NotImplementedError

    def extract_result(self) -> BrowserCapture:
        raise NotImplementedError
