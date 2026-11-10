from __future__ import annotations

import json

import pytest

from backend.app.providers.base import ProviderError
from backend.app.providers.deepseek_search import DeepSeekSearchProvider
from backend.app.services.costs import quote


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {"x-request-id": "request-test"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def provider():
    return DeepSeekSearchProvider("https://api.deepseek.test/v1", "test-secret", "deepseek-test")


def test_deepseek_search_chat_contract_long_query_and_citations(monkeypatch):
    requests = []
    responses = [
        Response({"results": [
            {"title": "A", "url": "https://example.com/a", "summary": "alpha", "site_name": "Example"},
            {"title": "duplicate", "url": "https://example.com/a", "snippet": "duplicate"},
            {"title": "No summary", "url": "https://example.org/no-summary"},
            {"title": "Invalid", "url": "file:///tmp/private", "snippet": "invalid"},
            {"title": "B", "url": "https://example.org/b", "snippet": "beta", "date": "2026-11-01"},
        ]}),
        Response({"model": "deepseek-version", "choices": [{"finish_reason": "stop", "message": {
            "content": "基于资料回答 https://example.com/a"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8}}),
    ]

    def fake_urlopen(request, timeout):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    prompt = "检" * 129
    result = provider().ask(prompt, {"temperature": 0.2, "max_tokens": 300})
    assert requests[0].full_url == "https://api.deepseek.test/v1/tools/search"
    assert json.loads(requests[0].data) == {"query": "检" * 128, "count": 10, "need_content": False}
    assert requests[1].full_url == "https://api.deepseek.test/v1/chat/completions"
    chat_payload = json.loads(requests[1].data)
    assert chat_payload["max_tokens"] == 300
    assert "max_completion_tokens" not in chat_payload
    assert prompt in chat_payload["messages"][1]["content"]
    assert [item["url"] for item in result.citations] == ["https://example.com/a", "https://example.org/b"]
    assert result.citations[0]["text"] == "alpha"
    assert [operation["kind"] for operation in result.operations] == ["search", "answer"]
    assert result.operations[0]["response_meta"] == {"search_query": "检" * 128, "query_truncated": True}
    assert result.operations[0]["request_params"] == {"count": 10, "need_content": False}
    assert result.usage["search_calls"] == 1 and result.model == "deepseek-version"


@pytest.mark.parametrize("results,kind,billable,search_calls", [
    ([], "search_no_results", False, 0),
    ([{"title": "invalid", "url": "not-a-url", "snippet": "text"}], "search_invalid_results", True, 1),
])
def test_deepseek_invalid_search_never_calls_chat(monkeypatch, results, kind, billable, search_calls):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: calls.append(request.full_url) or Response({"results": results}))
    with pytest.raises(ProviderError) as caught:
        provider().ask("question", {})
    assert caught.value.kind == kind
    assert calls == ["https://api.deepseek.test/v1/tools/search"]
    operation = caught.value.operations[0]
    assert operation["billable"] is billable and operation["usage"]["search_calls"] == search_calls
    assert "不会降级" in str(caught.value) or kind == "search_invalid_results"


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_deepseek_http_failure_is_not_billable_and_never_calls_chat(status):
    class FailingProvider(DeepSeekSearchProvider):
        def _post(self, path, payload):
            assert path == "/tools/search"
            raise ProviderError(f"HTTP {status}", f"http_{status}", retryable=status in (429, 500))

    with pytest.raises(ProviderError) as caught:
        FailingProvider("https://api.deepseek.test/v1", "secret", "model").ask("question", {})
    assert caught.value.kind == f"search_http_{status}"
    operation = caught.value.operations[0]
    assert operation["billable"] is False and operation["usage"]["search_calls"] == 0
    assert quote({"search_per_call": 1}, "search", operation["usage"]) == (0.0, "CNY", [])


def test_successful_deepseek_search_usage_survives_chat_failure():
    class FailingProvider(DeepSeekSearchProvider):
        def _post(self, path, payload):
            if path == "/tools/search":
                return {"results": [{"title": "A", "url": "https://example.com", "summary": "x"}]}, 12, "search-id"
            raise ProviderError("chat failed", "http_500", retryable=True)

    with pytest.raises(ProviderError) as caught:
        FailingProvider("https://api.deepseek.test/v1", "secret", "model").ask("question", {})
    search, chat = caught.value.operations
    assert search["kind"] == "search" and search["status"] == "succeeded"
    assert search["billable"] is True and search["usage"]["search_calls"] == 1
    assert chat["kind"] == "answer" and chat["status"] == "failed"
