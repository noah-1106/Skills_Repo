"""OpenAI-compatible chat provider with usage and explicit error semantics."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .base import BaseProvider, ProviderError, ProviderResult
from ..services.execution import DEFAULT_SYSTEM_PROMPT

NEUTRAL_SYSTEM = DEFAULT_SYSTEM_PROMPT


class OpenAICompatProvider(BaseProvider):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60,
                 capabilities: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.capabilities = capabilities or {}

    def _post(self, path: str, payload: dict) -> tuple[dict, int, str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": "geopulse/2.2"})
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
        execution = dict(protocol)
        if json_mode:
            execution = {"temperature": 0, "max_tokens": 1800, "system_prompt": NEUTRAL_SYSTEM, **execution}
        system_prompt = execution.get("system_prompt", NEUTRAL_SYSTEM)
        messages = [] if system_prompt is None else [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages}
        temperature = execution.get("temperature", 0 if json_mode else 0.2)
        max_tokens = execution.get("max_tokens", 1800 if json_mode else 700)
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        response_format = bool(json_mode and self.capabilities.get("supports_json_mode") is not False)
        if response_format:
            payload["response_format"] = {"type": "json_object"}
        request_params = {key: payload[key] for key in ("temperature", "max_tokens") if key in payload}
        request_params.update({"json_mode": json_mode, "response_format": response_format})
        operation = {"kind": "judge" if json_mode else "answer", "status": "succeeded",
                     "model": self.model, "latency_ms": 0, "usage": {}, "request_id": "",
                     "request_params": request_params, "response_meta": {"reasoning_present": False}}
        try:
            data, latency, request_id = self._post("/chat/completions", payload)
        except ProviderError as error:
            operation.update(status="failed", error_type=error.kind, error_detail=str(error))
            error.operations = [operation]
            raise
        usage = data.get("usage") or {}
        model = data.get("model") or self.model
        operation.update({"model": model, "latency_ms": latency, "usage": usage, "request_id": request_id})
        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = (message.get("content") or "").strip()
            reasoning_field = bool(message.get("reasoning_content"))
            think_block = text.startswith("<think>")
            operation["response_meta"] = {
                "reasoning_present": reasoning_field or think_block,
                "reasoning_format": "think_tag" if think_block else "provider_field" if reasoning_field else "",
            }
            if think_block:
                closing = text.find("</think>", len("<think>"))
                if closing < 0:
                    raise ProviderError("推理块未闭合且没有完整可见回答", "reasoning_incomplete")
                text = text[closing + len("</think>"):].strip()
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
