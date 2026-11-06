import json

import pytest

from backend.app.providers.base import ProviderError
from backend.app.providers.kimi_search import KimiSearchProvider
from backend.app.providers.openai_compat import OpenAICompatProvider


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
    return KimiSearchProvider("https://api.kimi.test/v1", "test-secret", "kimi-test")


def test_kimi_search_chat_contract_and_source_dedup(monkeypatch):
    requests = []
    responses = [
        Response({"search_results": [
            {"title": "A", "url": "https://example.com/a", "text": "alpha"},
            {"title": "duplicate", "url": "https://example.com/a", "text": "duplicate"},
            {"title": "B", "url": "https://example.org/b", "text": "beta"},
        ]}),
        Response({"model": "kimi-test-version", "choices": [{"finish_reason": "stop", "message": {
            "content": "基于资料回答 https://example.com/a"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 8}}),
    ]

    def fake_urlopen(request, timeout):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = provider().ask("有哪些 GEO 工具？", {"temperature": 0.2, "max_tokens": 300})
    assert requests[0].full_url == "https://api.kimi.test/v1/tools/search"
    assert json.loads(requests[0].data) == {"text_query": "有哪些 GEO 工具？"}
    assert requests[1].full_url == "https://api.kimi.test/v1/chat/completions"
    chat_payload = json.loads(requests[1].data)
    assert "Kimi Search Basic" in chat_payload["messages"][1]["content"]
    assert chat_payload["model"] == "kimi-test"
    assert [item["url"] for item in result.citations] == ["https://example.com/a", "https://example.org/b"]
    assert [operation["kind"] for operation in result.operations] == ["search", "answer"]
    assert result.usage["search_calls"] == 1
    assert result.model == "kimi-test-version"


def test_kimi_never_falls_back_when_search_has_no_results(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response({"search_results": []}))
    with pytest.raises(ProviderError) as caught:
        provider().ask("question", {})
    assert caught.value.kind == "search_no_results"
    assert "不会降级" in str(caught.value)


def test_successful_search_usage_survives_chat_failure():
    class FailingProvider(KimiSearchProvider):
        def _post(self, path, payload):
            if path == "/tools/search":
                return {"search_results": [{"title": "A", "url": "https://example.com", "text": "x"}]}, 12, "search-id"
            raise ProviderError("chat failed", "http_500", retryable=True)

    with pytest.raises(ProviderError) as caught:
        FailingProvider("https://api.kimi.test/v1", "secret", "model").ask("question", {})
    assert caught.value.operations[0]["kind"] == "search"
    assert caught.value.operations[0]["status"] == "succeeded"


def test_truncated_or_reasoning_only_chat_is_not_a_valid_answer():
    class TruncatedProvider(OpenAICompatProvider):
        def _post(self, path, payload):
            return {"choices": [{"finish_reason": "length", "message": {
                "content": "partial", "reasoning_content": "private reasoning"}}]}, 1, "id"

    with pytest.raises(ProviderError) as caught:
        TruncatedProvider("https://example.test/v1", "secret", "model").ask("question", {})
    assert caught.value.kind == "truncated_answer"
