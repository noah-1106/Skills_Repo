"""Explicit registry of implemented Consumer Web drivers."""
from __future__ import annotations

from .base import BrowserCapture, BrowserDriver, CollectorError
from .deepseek_web import DeepSeekWebDriver
from .kimi_web import KimiWebDriver

DRIVERS: dict[str, type[BrowserDriver]] = {
    DeepSeekWebDriver.key: DeepSeekWebDriver,
    KimiWebDriver.key: KimiWebDriver,
}


def get_driver(key: str) -> type[BrowserDriver]:
    try:
        return DRIVERS[key]
    except KeyError:
        raise CollectorError("driver_incompatible", f"未实现 Consumer Web Driver：{key}") from None


__all__ = ["BrowserCapture", "BrowserDriver", "CollectorError", "DRIVERS", "get_driver"]
