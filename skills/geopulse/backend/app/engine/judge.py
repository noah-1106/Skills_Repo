"""Structured LLM judge with entity disambiguation and auditable fallback."""
from __future__ import annotations

import json
from typing import Any

from ..db import dumps, utc_now
from ..providers.base import BaseProvider, ProviderResult
from .analyzer import absent_observation, analyze_mentions, evidence_for

JUDGE_VERSION = "geo-judge-v2.0"
ENTITY_STATUSES = {"confirmed", "ambiguous", "wrong_entity", "unknown"}
DEPTHS = {"absent", "mentioned", "described", "recommended"}
SENTIMENTS = {"positive", "neutral", "negative", "unknown"}


def _parse_json(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("judge 未返回 JSON")
        value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("judge JSON 顶层必须是对象")
    return value


def fallback_observations(answer_text: str, entities: list[dict], demo: bool = False) -> list[dict]:
    matches = analyze_mentions(answer_text, entities, demo=demo)
    results = []
    for entity in entities:
        observation = matches.get(int(entity["id"])) or absent_observation(
            entity, "confirmed" if demo else "unknown")
        observation["judge_status"] = "demo-rules" if demo else "rules-fallback"
        observation["judge_meta"] = {"prompt_version": JUDGE_VERSION, "fallback": not demo, "created_at": utc_now()}
        observation["discovered"] = []
        results.append(observation)
    return results


def judge_answer(provider: BaseProvider, answer_text: str, entities: list[dict], protocol: dict,
                 citations: list[dict]) -> tuple[list[dict], list[dict], ProviderResult]:
    roster = [{"entity_id": entity["id"], "name": entity["name"], "role": entity["role"],
               **(entity.get("entity_card") or {})} for entity in entities]
    source_urls = {item["url"] for item in citations}
    prompt = (
        "你是 GEO 测量判定器，只输出 JSON。必须依据实体卡消歧，字符串相同不代表同一商业实体。"
        "逐个输出输入中的 entity_id，不得改名。只有 confirmed 才表示目标实体有效出现。"
        "recommended 仅表示当前问题下明确正向建议；负面、劝退、对比败者不得为 recommended。"
        "evidence 必须逐字摘录回答原句；没有提及则为空字符串。citation_urls 只能使用给定来源 URL。"
        "另返回回答中出现但不在实体表里的候选品牌，候选不得直接计入正式竞品。"
        '输出 {"brands":[{"entity_id":0,"entity_status":"confirmed|ambiguous|wrong_entity|unknown",'
        '"mentioned":true,"depth":"absent|mentioned|described|recommended",'
        '"sentiment":"positive|neutral|negative|unknown","top_choice":false,"evidence":"",'
        '"citation_urls":[]}],"discovered_entities":[{"name":"","aliases":[],"category":"","evidence":""}]}。'
        f"\n实体表：{json.dumps(roster, ensure_ascii=False)}\n可用来源：{json.dumps(sorted(source_urls), ensure_ascii=False)}"
        f"\n回答原文：{answer_text}")
    judged = provider.ask_json(prompt, protocol)
    parsed = _parse_json(judged.text)
    by_id = {str(entity["id"]): entity for entity in entities}
    returned = {str(item.get("entity_id")): item for item in parsed.get("brands", []) if isinstance(item, dict)}
    observations = []
    for entity_id, entity in by_id.items():
        item = returned.get(entity_id)
        if item is None:
            observation = absent_observation(entity)
            observation.update(judge_status="llm-judge-incomplete", review_status="pending")
            observations.append(observation)
            continue
        entity_status = item.get("entity_status") if item.get("entity_status") in ENTITY_STATUSES else "unknown"
        mentioned = bool(item.get("mentioned"))
        depth = item.get("depth") if item.get("depth") in DEPTHS else ("mentioned" if mentioned else "absent")
        sentiment = item.get("sentiment") if item.get("sentiment") in SENTIMENTS else "unknown"
        if not mentioned or depth == "absent":
            mentioned, depth, top_choice = False, "absent", False
        if sentiment == "negative" and depth == "recommended":
            depth = "mentioned"
        evidence = str(item.get("evidence") or "")[:1000]
        review_status = "pending" if entity_status in ("ambiguous", "unknown") else "machine"
        judge_status = "llm-judge"
        if mentioned and (not evidence or evidence not in answer_text):
            evidence = evidence_for(answer_text, entity)
            review_status = "pending"
            judge_status = "llm-judge-evidence-fallback"
        citation_urls = [url for url in item.get("citation_urls", []) if url in source_urls]
        if mentioned and entity_status == "confirmed" and not evidence:
            review_status = "pending"
        observations.append({
            "brand_entity_id": int(entity_id), "entity_status": entity_status,
            "mentioned": int(mentioned), "depth": depth, "sentiment": sentiment,
            "top_choice": int(bool(item.get("top_choice")) and depth == "recommended" and sentiment != "negative"),
            "evidence": evidence, "citation_urls": citation_urls, "judge_status": judge_status,
            "review_status": review_status,
        })
    discovered = []
    for item in parsed.get("discovered_entities", []):
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            evidence = str(item.get("evidence") or "")
            discovered.append({"name": str(item["name"]).strip()[:200],
                               "aliases": item.get("aliases") or [], "category": str(item.get("category") or ""),
                               "evidence": evidence if evidence in answer_text else ""})
    meta = {"prompt_version": JUDGE_VERSION, "model": judged.model, "created_at": utc_now(),
            "usage": judged.usage, "request_id": judged.request_id}
    for observation in observations:
        observation["judge_meta"] = meta
        observation["discovered"] = discovered
    return observations, discovered, judged
