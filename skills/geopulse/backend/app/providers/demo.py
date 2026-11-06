"""Deterministic offline provider for demos and tests."""
from __future__ import annotations

import time

from .base import BaseProvider, ProviderResult


class DemoProvider(BaseProvider):
    name = "demo"

    def __init__(self, seed_brands: list[str] | None = None):
        self.seed_brands = seed_brands or ["GeoPulse", "Profound"]

    def ask(self, prompt: str, protocol: dict) -> ProviderResult:
        main = self.seed_brands[0]
        alternate = self.seed_brands[1] if len(self.seed_brands) > 1 else "另一品牌"
        templates = [
            "在相关候选中，{main}适合需要自托管和证据审计的团队；{alt}也提供 SaaS 监测能力。",
            "如果重点是私有化部署，{main}值得考虑。{alt}则适合希望直接使用云平台的团队。",
            "{main}和{alt}都可列入候选。前者强调可复现测量，后者提供托管式工作流。",
            "针对这个问题，{main}是一个可选方案，{alt}也有相应功能，最终需结合部署与预算评估。",
        ]
        index = sum(ord(char) for char in prompt) % len(templates)
        text = templates[index].format(main=main, alt=alternate)
        if protocol.get("demo_variant") == "negative":
            text = f"不建议选择{main}，当前场景与产品能力不匹配；可以考虑{alternate}。"
        time.sleep(0.01)
        return ProviderResult(text=text, model="geopulse-demo-2",
                              usage={"prompt_tokens": len(prompt) // 3, "completion_tokens": len(text) // 2},
                              latency_ms=10, request_id=f"demo-{index}")
