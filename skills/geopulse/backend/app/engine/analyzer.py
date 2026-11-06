"""Deterministic alias matching and evidence extraction.

Rules are an explainable fallback, not a substitute for entity confirmation.
"""
from __future__ import annotations

import re
from typing import Iterable

NEGATIVE_WORDS = ("不建议", "不推荐", "避开", "别选", "不如", "慎选", "踩坑", "售后太差", "性价比低")
REC_WORDS = ("首选", "值得推荐", "推荐使用", "推荐", "建议选用", "值得考虑", "优选", "优先选择", "不妨")
DESC_WORDS = ("提供", "支持", "拥有", "适合", "主打", "特点", "优势", "定位", "核心功能", "产品线", "成立于", "专注")


def alias_pattern(alias: str):
    escaped = re.escape(alias.lower().strip())
    if re.search(r"[a-z0-9]", alias.lower()):
        return re.compile(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])")
    return re.compile(escaped)


def aliases_for(entity: dict) -> list[str]:
    card = entity.get("entity_card") or entity.get("card") or {}
    return [entity["name"], *(card.get("aliases") or entity.get("aliases") or [])]


def alias_conflicts(entities: Iterable[dict]) -> list[dict]:
    entries = [(entity["name"], alias.strip()) for entity in entities for alias in aliases_for(entity) if alias.strip()]
    conflicts = []
    for index, (brand_a, alias_a) in enumerate(entries):
        for brand_b, alias_b in entries[index + 1:]:
            if brand_a == brand_b:
                continue
            a, b = alias_a.casefold(), alias_b.casefold()
            if a in b or b in a:
                conflicts.append({"brand_a": brand_a, "alias_a": alias_a, "brand_b": brand_b, "alias_b": alias_b})
    return conflicts


def evidence_for(text: str, entity: dict) -> str:
    for sentence in re.split(r"(?<=[。！？!?；;])|\n", text):
        if any(alias.strip() and alias_pattern(alias).search(sentence.lower()) for alias in aliases_for(entity)):
            return sentence.strip()[:1000]
    return ""


def _depth(text_lower: str, alias: str) -> tuple[str, str]:
    positions = [match.start() for match in alias_pattern(alias).finditer(text_lower)]
    for position in positions:
        window = text_lower[max(0, position - 35):position + 70]
        if any(word in window for word in NEGATIVE_WORDS):
            return "mentioned", "negative"
    for position in positions:
        window = text_lower[max(0, position - 30):position + 70]
        if any(word in window for word in REC_WORDS):
            return "recommended", "positive"
    for position in positions:
        window = text_lower[max(0, position - 20):position + 70]
        if any(word in window for word in DESC_WORDS):
            return "described", "neutral"
    return "mentioned", "neutral"


def analyze_mentions(answer_text: str, entities: list[dict], demo: bool = False) -> dict[int, dict]:
    text = answer_text.lower()
    candidates = []
    for entity in entities:
        for alias in aliases_for(entity):
            if alias.strip():
                candidates.append((entity, alias.strip()))
    candidates.sort(key=lambda item: -len(item[1]))
    occupied: list[tuple[int, int]] = []
    result: dict[int, dict] = {}
    for entity, alias in candidates:
        entity_id = int(entity["id"])
        if entity_id in result:
            continue
        for match in alias_pattern(alias).finditer(text):
            start, end = match.span()
            if any(start < occupied_end and occupied_start < end for occupied_start, occupied_end in occupied):
                continue
            depth, sentiment = _depth(text, alias)
            short_chinese = len(alias) <= 2 and not re.search(r"[a-z0-9]", alias, re.I)
            result[entity_id] = {
                "brand_entity_id": entity_id,
                "entity_status": "confirmed" if demo and not short_chinese else "unknown",
                "mentioned": 1, "depth": depth, "sentiment": sentiment,
                "top_choice": int(depth == "recommended" and "首选" in text),
                "evidence": evidence_for(answer_text, entity), "citation_urls": [],
                "judge_status": "demo-rules" if demo else "rules-fallback",
                "review_status": "machine" if demo and not short_chinese else "pending",
                "matched_alias": alias,
            }
            occupied.append((start, end))
            break
    return result


def absent_observation(entity: dict, status: str = "unknown") -> dict:
    return {"brand_entity_id": int(entity["id"]), "entity_status": status, "mentioned": 0,
            "depth": "absent", "sentiment": "unknown", "top_choice": 0, "evidence": "",
            "citation_urls": [], "judge_status": "rules-fallback", "review_status": "machine"}
