"""Provider contracts and normalized failures."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    citations: list[dict] = field(default_factory=list)
    request_id: str = ""
    operations: list[dict] = field(default_factory=list)


class ProviderError(RuntimeError):
    def __init__(self, message: str, kind: str = "provider", retryable: bool = False,
                 outcome_unknown: bool = False, operations: list[dict] | None = None):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        self.operations = operations or []


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def ask(self, prompt: str, protocol: dict) -> ProviderResult:
        raise NotImplementedError

    def ask_json(self, prompt: str, protocol: dict) -> ProviderResult:
        raise ProviderError(f"{self.name} 不支持结构化 judge", "judge_unsupported")
