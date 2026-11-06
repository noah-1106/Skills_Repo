"""Kimi Search Basic + Chat retrieval-augmented measurement.

This is provider_api search, not Kimi App/consumer-web observation.
"""
from __future__ import annotations

from .base import ProviderError, ProviderResult
from .openai_compat import OpenAICompatProvider


class KimiSearchProvider(OpenAICompatProvider):
    name = "kimi_search"
    pipeline_version = "kimi-search-basic-chat-v1"

    def ask(self, prompt: str, protocol: dict) -> ProviderResult:
        try:
            data, search_latency, search_request_id = self._post("/tools/search", {"text_query": prompt})
        except ProviderError as error:
            error.kind = f"search_{error.kind}"
            raise
        results = data.get("search_results")
        if not isinstance(results, list) or not results:
            raise ProviderError("Kimi 检索未返回来源；不会降级为记忆态", "search_no_results",
                                operations=[{"kind": "search", "status": "failed", "latency_ms": search_latency,
                                             "usage": {}, "request_id": search_request_id}])
        citations = []
        seen_urls = set()
        for item in results:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            url = str(item["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            citations.append({"title": str(item.get("title") or ""), "url": url,
                              "text": str(item.get("text") or "")})
        if not citations:
            raise ProviderError("Kimi 检索结果没有可核验 URL", "search_invalid_results",
                                operations=[{"kind": "search", "status": "failed", "latency_ms": search_latency,
                                             "usage": {"search_calls": 1}, "request_id": search_request_id,
                                             "error_type": "search_invalid_results",
                                             "error_detail": "Kimi 检索结果没有可核验 URL"}])
        context = "\n\n".join(f"[{index}] {item['title']}\nURL: {item['url']}\n摘要: {item['text']}"
                              for index, item in enumerate(citations, 1))
        augmented = (f"用户问题：{prompt}\n\n以下来自 Kimi Search Basic。仅把与问题相关的资料作为依据，"
                     f"不要编造来源；使用资料时在对应主张后标注 URL。\n\n{context}")
        search_operation = {"kind": "search", "status": "succeeded", "model": "kimi-search-basic",
                            "latency_ms": search_latency, "usage": {"search_calls": 1},
                            "request_id": search_request_id}
        try:
            answer = super().ask(augmented, {**protocol, "system_prompt":
                "基于用户问题和给定检索资料客观回答。不要刻意添加或回避品牌；不确定时说明。引用主张必须保留对应 URL。"})
        except ProviderError as error:
            error.operations = [search_operation, *error.operations]
            raise
        answer.citations = citations
        answer.operations = [search_operation, *answer.operations]
        answer.usage = {**answer.usage, "search_calls": 1}
        return answer
