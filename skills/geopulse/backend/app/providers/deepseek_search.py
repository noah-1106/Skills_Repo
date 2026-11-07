"""DeepSeek Search API + Chat retrieval-augmented measurement.

Official contract: POST /v1/tools/search with query/count/need_content.
This is provider_api search, not a consumer DeepSeek Web/App observation.
"""
from __future__ import annotations

import urllib.parse

from .base import ProviderError, ProviderResult
from .openai_compat import OpenAICompatProvider


class DeepSeekSearchProvider(OpenAICompatProvider):
    name = "deepseek_search"
    pipeline_version = "deepseek-search-chat-v1"

    def ask(self, prompt: str, protocol: dict) -> ProviderResult:
        query = prompt.strip()
        truncated = len(query) > 128
        query = query[:128].rstrip()
        search_params = {"count": 10, "need_content": False}
        search_meta = {"search_query": query, "query_truncated": truncated}
        operation = {"kind": "search", "operation": "search", "status": "failed",
                     "model": "deepseek-search", "usage": {"search_calls": 0},
                     "request_params": search_params, "response_meta": search_meta}
        if not query:
            error = ProviderError("DeepSeek 检索查询不能为空", "search_empty_query")
            operation.update(error_type=error.kind, error_detail=str(error), billable=False)
            error.operations = [operation]
            raise error
        try:
            data, latency, request_id = self._post("/tools/search", {
                "query": query, **search_params,
            })
            operation.update(latency_ms=latency, request_id=request_id)
        except ProviderError as error:
            error.kind = f"search_{error.kind}"
            operation.update(error_type=error.kind, error_detail=str(error), billable=False)
            error.operations = [operation]
            raise
        results = data.get("results")
        if not isinstance(results, list) or not results:
            error = ProviderError("DeepSeek 检索未返回来源；不会降级为记忆态", "search_no_results")
            operation.update(error_type=error.kind, error_detail=str(error), billable=False)
            error.operations = [operation]
            raise error
        citations = []
        seen_urls = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            parsed = urllib.parse.urlparse(url)
            text = str(item.get("summary") or item.get("snippet") or item.get("content") or "").strip()
            if parsed.scheme not in ("http", "https") or not parsed.hostname or not text or url in seen_urls:
                continue
            seen_urls.add(url)
            citations.append({
                "title": str(item.get("title") or item.get("site_name") or ""), "url": url,
                "text": text, "snippet": str(item.get("snippet") or ""),
                "site_name": str(item.get("site_name") or ""), "returned_at": item.get("date") or "",
            })
        operation["usage"] = {"search_calls": 1}
        operation["billable"] = True
        if not citations:
            error = ProviderError("DeepSeek 检索结果没有可核验 URL 和摘要", "search_invalid_results")
            operation.update(error_type=error.kind, error_detail=str(error))
            error.operations = [operation]
            raise error
        operation["status"] = "succeeded"
        context = "\n\n".join(
            f"[{index}] {item['title']}\nURL: {item['url']}\n摘要: {item['text']}"
            for index, item in enumerate(citations, 1)
        )
        augmented = (
            f"用户问题：{prompt}\n\n以下来自 DeepSeek Search。仅把与问题相关的资料作为依据，"
            f"不要编造来源；使用资料时在对应主张后标注 URL。\n\n{context}"
        )
        try:
            answer = super().ask(augmented, protocol)
        except ProviderError as error:
            error.operations = [operation, *error.operations]
            raise
        answer.citations = citations
        answer.operations = [operation, *answer.operations]
        answer.usage = {**answer.usage, "search_calls": 1}
        return answer
