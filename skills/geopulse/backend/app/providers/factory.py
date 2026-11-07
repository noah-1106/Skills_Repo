"""Provider factory. Secrets are resolved only inside the worker."""
from __future__ import annotations

from .base import BaseProvider, ProviderError, ProviderResult
from .demo import DemoProvider
from .deepseek_search import DeepSeekSearchProvider
from .kimi_search import KimiSearchProvider
from .openai_compat import OpenAICompatProvider
from ..services.execution import capabilities_for


def build_provider(engine: dict, api_key: str = "", seed_brands: list[str] | None = None) -> BaseProvider:
    kind = engine["kind"]
    if kind == "demo":
        return DemoProvider(seed_brands)
    if kind == "manual_web":
        raise ProviderError("人工 Consumer Web 目标不是 Provider，不能自动发起回答、Search 或健康检查", "manual_target_not_provider")
    if not api_key:
        raise ProviderError(f"引擎 {engine['name']} 缺少 API Key", "missing_api_key")
    if kind in ("kimi_search", "deepseek_search"):
        if engine.get("mode") != "search":
            raise ProviderError(f"{engine['name']} 检索引擎必须声明 search 模式", "mode_mismatch")
        provider_class = KimiSearchProvider if kind == "kimi_search" else DeepSeekSearchProvider
        return provider_class(engine["base_url"], api_key, engine["model"], int(engine.get("timeout") or 60),
                              capabilities_for(engine))
    if kind == "openai_compat":
        if engine.get("mode") != "memory":
            raise ProviderError("普通 OpenAI-compatible 引擎只能声明 memory 模式", "mode_mismatch")
        return OpenAICompatProvider(engine["base_url"], api_key, engine["model"], int(engine.get("timeout") or 60),
                                    capabilities_for(engine))
    raise ProviderError(f"未知引擎类型 {kind}", "unknown_provider")
