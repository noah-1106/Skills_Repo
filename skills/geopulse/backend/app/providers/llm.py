"""Compatibility imports for the provider layer; no legacy execution semantics."""
from .factory import build_provider
from .base import BaseProvider, ProviderError, ProviderResult
from .demo import DemoProvider
from .deepseek_search import DeepSeekSearchProvider
from .kimi_search import KimiSearchProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["build_provider", "BaseProvider", "ProviderError", "ProviderResult", "DemoProvider",
           "KimiSearchProvider", "DeepSeekSearchProvider", "OpenAICompatProvider"]
