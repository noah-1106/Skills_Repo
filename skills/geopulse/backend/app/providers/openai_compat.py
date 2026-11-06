"""OpenAI-compatible chat provider with usage and explicit error semantics."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .base import BaseProvider, ProviderError, ProviderResult

NEUTRAL_SYSTEM = "客观、准确地回答用户问题。不要为了迎合监测而刻意添加或回避品牌；不确定时明确说明。"


class OpenAICompatProvider(BaseProvider):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> tuple[dict, int, str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": "geopulse/2.0"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                request_id = response.headers.get("x-request-id", "")
        except urllib.error.HTTPError as error:
            try:
                body = error.read().decode("utf-8", "replace")[:500]
            except Exception:
                body = ""
            raise ProviderError(f"HTTP {error.code}: {body}", f"http_{error.code}",
                                retryable=error.code == 429 or error.code >= 500) from error
        except TimeoutError as error:
            raise ProviderError("请求超时，厂商是否已计费未知；请人工确认后重试", "timeout",
                                outcome_unknown=True) from error
        except urllib.error.URLError as error:
            reason = str(error.reason)
            unknown = "timed out" in reason.lower()
            raise ProviderError(f"网络错误：{reason}", "timeout" if unknown else "network",
                                retryable=not unknown, outcome_unknown=unknown) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderError("厂商返回了无法解析的响应", "malformed_response") from error
        return data, int((time.monotonic() - started) * 1000), request_id

    def _chat(self, prompt: str, protocol: dict, json_mode: bool = False) -> ProviderResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": protocol.get("system_prompt") or NEUTRAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0 if json_mode else protocol.get("temperature", 0.2),
            "max_tokens": 1800 if json_mode else protocol.get("max_tokens", 700),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data, latency, request_id = self._post("/chat/completions", payload)
        usage = data.get("usage") or {}
        model = data.get("model") or self.model
        operation = {"kind": "judge" if json_mode else "answer", "status": "succeeded",
                     "model": model, "latency_ms": latency, "usage": usage, "request_id": request_id}
        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = (message.get("content") or "").strip()
            if choice.get("finish_reason") == "length":
                raise ProviderError("输出被 max_tokens 截断，不作为有效回答", "truncated_answer")
            if not text:
                raise ProviderError(f"空回答（finish={choice.get('finish_reason')}）", "empty_answer")
        except ProviderError as error:
            operation.update(status="failed", error_type=error.kind, error_detail=str(error))
            error.operations = [operation]
            raise
        except (KeyError, IndexError, TypeError) as error:
            failure = ProviderError(f"响应缺少必要字段：{error}", "malformed_response")
            operation.update(status="failed", error_type=failure.kind, error_detail=str(failure))
            failure.operations = [operation]
            raise failure from error
        return ProviderResult(text=text, model=model, usage=usage, latency_ms=latency,
                              request_id=request_id, operations=[operation])

    def ask(self, prompt: str, protocol: dict) -> ProviderResult:
        return self._chat(prompt, protocol)

    def ask_json(self, prompt: str, protocol: dict) -> ProviderResult:
        return self._chat(prompt, protocol, json_mode=True)
