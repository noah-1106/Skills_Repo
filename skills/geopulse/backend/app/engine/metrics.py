"""GEO metric dictionary implemented as pure, testable aggregation."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

DEPTH_RANK = {"absent": 0, "mentioned": 1, "described": 2, "recommended": 3}


def wilson(hits: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    # 0.95 is the product default; other levels use a conservative normal approximation.
    z = 1.959963984540054 if abs(confidence - 0.95) < 0.0001 else (2.575829 if confidence >= 0.99 else 1.644854)
    p = hits / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return (max(0.0, center - margin) * 100, min(1.0, center + margin) * 100)


def ratio(hits: int, total: int, stats: dict, value: float | None = None) -> dict:
    low, high = wilson(hits, total, float(stats.get("confidence_level", 0.95)))
    return {"hits": hits, "n": total, "value": round(((hits / total * 100) if total else 0.0) if value is None else value, 2),
            "ci_low": round(low, 2), "ci_high": round(high, 2),
            "limited": total < int(stats.get("small_sample_n", 30))}


def _valid(sample: dict) -> bool:
    persisted = sample.get("valid_sample")
    if persisted is not None:
        return bool(persisted)
    return sample.get("status") == "succeeded" and bool(sample.get("raw_text"))


def _primary(sample: dict, primary_id: int) -> dict:
    return next((item for item in sample.get("observations", [])
                 if int(item["brand_entity_id"]) == int(primary_id)), {
        "entity_status": "unknown", "mentioned": 0, "depth": "absent", "sentiment": "unknown",
        "top_choice": 0, "citation_urls": [], "judge_status": "missing"})


def _confirmed(observation: dict) -> bool:
    return observation.get("entity_status") == "confirmed" and bool(observation.get("mentioned"))


def _recommended(observation: dict) -> bool:
    return _confirmed(observation) and observation.get("depth") == "recommended" and observation.get("sentiment") != "negative"


def _group_key(sample: dict) -> tuple:
    return (int(sample["engine_config_id"]), sample["canonical_intent_id"])


def _weighted_group_value(groups: dict, field: str) -> float:
    total_weight = sum(max(0.0, float(group.get("weight", 1))) for group in groups.values())
    if not total_weight:
        return 0.0
    return sum(float(group[field]) * max(0.0, float(group.get("weight", 1))) for group in groups.values()) / total_weight * 100


def calculate_metrics(samples: list[dict], primary_id: int, stats: dict | None = None) -> dict:
    stats = stats or {}
    valid = [sample for sample in samples if _valid(sample)]
    groups: dict[tuple, dict] = {}
    for sample in valid:
        key = _group_key(sample)
        group = groups.setdefault(key, {"answers": [], "weight": float(sample.get("weight", 1) or 1),
                                        "engine_config_id": key[0], "canonical_intent_id": key[1],
                                        "dimension": sample.get("dimension") or "other",
                                        "prompt_text": sample.get("prompt_text") or "",
                                        "query_type": sample.get("query_type") or "discovery"})
        group["answers"].append(sample)
    pairs = {}
    for key, group in groups.items():
        primary = [_primary(sample, primary_id) for sample in group["answers"]]
        hits = sum(_confirmed(item) for item in primary)
        recommendations = sum(_recommended(item) for item in primary)
        group["hits"] = hits
        group["rounds"] = len(primary)
        group["covered"] = hits > 0
        group["recommended_covered"] = recommendations > 0
        group["hit_rate"] = hits / len(primary) if primary else 0
        group["recommendation_rate"] = recommendations / len(primary) if primary else 0
        shares = []
        for sample in group["answers"]:
            confirmed = [obs for obs in sample.get("observations", []) if _confirmed(obs)]
            shares.append((1 / len(confirmed)) if _confirmed(_primary(sample, primary_id)) and confirmed else 0.0)
        group["sov"] = sum(shares) / len(shares) if shares else 0.0
        pairs[f"{key[0]}:{key[1]}"] = {
            "engine_config_id": key[0], "canonical_intent_id": key[1], "covered": group["covered"],
            "recommended_covered": group["recommended_covered"], "hits": hits, "rounds": len(primary),
            "prompt_text": group["prompt_text"], "dimension": group["dimension"],
        }
    covered = sum(group["covered"] for group in groups.values())
    recommendation_covered = sum(group["recommended_covered"] for group in groups.values())
    primary_rows = [_primary(sample, primary_id) for sample in valid]
    hit_count = sum(_confirmed(item) for item in primary_rows)
    recommendation_count = sum(_recommended(item) for item in primary_rows)
    top_choice_count = sum(_recommended(item) and bool(item.get("top_choice")) for item in primary_rows)
    negative_count = sum(_confirmed(item) and item.get("sentiment") == "negative" for item in primary_rows)
    cited_count = sum(_confirmed(item) and bool(item.get("citation_urls")) for item in primary_rows)
    coverage_value = _weighted_group_value(groups, "covered")
    recommendation_coverage_value = _weighted_group_value(groups, "recommended_covered")
    sov_value = _weighted_group_value(groups, "sov")

    north_groups = {key: group for key, group in groups.items()
                    if group["query_type"] == "discovery" and any(
                        sample.get("eligibility") in ("eligible", "client_confirmed") and int(sample.get("priority", 0)) >= 4
                        for sample in group["answers"])}
    north_covered = sum(group["recommended_covered"] for group in north_groups.values())

    competitors: dict[int, dict] = {}
    for sample in valid:
        confirmed = [obs for obs in sample.get("observations", []) if _confirmed(obs)]
        for observation in sample.get("observations", []):
            entity_id = int(observation["brand_entity_id"])
            if observation.get("role") == "candidate":
                continue
            item = competitors.setdefault(entity_id, {
                "brand_entity_id": entity_id, "name": observation.get("name") or str(entity_id),
                "role": observation.get("role") or "competitor", "mentions": 0, "negative": 0,
                "depth": defaultdict(int), "group_share_sum": defaultdict(float),
                "group_n": defaultdict(int), "evidence": [],
            })
            key = _group_key(sample)
            item["group_share_sum"][key] += (1 / len(confirmed)) if _confirmed(observation) and confirmed else 0.0
            item["group_n"][key] += 1
            if _confirmed(observation):
                item["mentions"] += 1
                item["depth"][observation.get("depth") or "mentioned"] += 1
                if observation.get("sentiment") == "negative":
                    item["negative"] += 1
                evidence = observation.get("evidence")
                if evidence and evidence not in item["evidence"] and len(item["evidence"]) < 3:
                    item["evidence"].append(evidence)
    competitor_rows = []
    for item in competitors.values():
        item["depth"] = dict(item["depth"])
        weighted_share = 0.0
        total_weight = 0.0
        for key, group in groups.items():
            weight = max(0.0, float(group.get("weight", 1)))
            count = item["group_n"].get(key, 0)
            weighted_share += (item["group_share_sum"].get(key, 0.0) / count if count else 0.0) * weight
            total_weight += weight
        item["sov"] = round(weighted_share / total_weight * 100, 2) if total_weight else 0.0
        item.pop("group_share_sum")
        item.pop("group_n")
        competitor_rows.append(item)
    competitor_rows.sort(key=lambda item: (-item["mentions"], item["name"]))

    dimension_rows = []
    for dimension in sorted({sample.get("dimension") or "other" for sample in valid}):
        subset = [sample for sample in valid if (sample.get("dimension") or "other") == dimension]
        dimension_rows.append({"key": dimension, **_summary_only(subset, primary_id, stats)})
    engine_rows = []
    for engine_id in sorted({int(sample["engine_config_id"]) for sample in valid}):
        subset = [sample for sample in valid if int(sample["engine_config_id"]) == engine_id]
        engine_rows.append({"engine_config_id": engine_id,
                            "engine": subset[0].get("engine_name") or str(engine_id),
                            "mode": subset[0].get("engine_mode") or "memory",
                            **_summary_only(subset, primary_id, stats)})
    modes = sorted({sample.get("engine_mode") or "memory" for sample in valid})
    judge_fallback = sum(any(str(obs.get("judge_status", "")).startswith("rules-fallback")
                             for obs in sample.get("observations", [])) for sample in valid)
    entity_confirmed = sum(item.get("entity_status") == "confirmed" for item in primary_rows)
    pending_review = sum(any(obs.get("review_status") == "pending" for obs in sample.get("observations", []))
                         for sample in valid)
    result = {
        "coverage": ratio(covered, len(groups), stats, coverage_value),
        "hit_rate": ratio(hit_count, len(valid), stats),
        "recommendation_coverage": ratio(recommendation_covered, len(groups), stats, recommendation_coverage_value),
        "effective_recommendation_rate": ratio(recommendation_count, len(valid), stats),
        "top_choice_rate": ratio(top_choice_count, len(valid), stats),
        "negative_risk_rate": ratio(negative_count, hit_count, stats),
        "north_star": ratio(north_covered, len(north_groups), stats,
                            _weighted_group_value(north_groups, "recommended_covered")),
        "share_of_voice": {"value": round(sov_value, 2), "n": len(valid), "definition": "每回答按确认实体归一，空回答计0"},
        "competitors": competitor_rows, "dimensions": dimension_rows, "engines": engine_rows,
        "quality": {
            "expected_samples": len(samples), "valid_samples": len(valid),
            "failed_samples": sum(sample.get("status") == "failed" for sample in samples),
            "cancelled_samples": sum(sample.get("status") == "cancelled" for sample in samples),
            "valid_sample_rate": ratio(len(valid), len(samples), stats),
            "entity_confirmation_rate": ratio(entity_confirmed, len(valid), stats),
            "judge_fallback_rate": ratio(judge_fallback, len(valid), stats),
            "pending_review_answers": pending_review,
        },
        "measurement_modes": modes, "is_demo": bool(valid) and all(sample.get("engine_kind") == "demo" for sample in valid),
        "pairs": pairs,
        "limitations": _limitations(samples, groups, modes, stats),
    }
    if any(sample.get("measurement_target") == "consumer_web" for sample in samples):
        web_samples = [sample for sample in samples if sample.get("measurement_target") == "consumer_web"]
        web_valid = [sample for sample in valid if sample.get("measurement_target") == "consumer_web"]
        result["quality"].update({
            "awaiting_collection": sum(sample.get("status") == "awaiting_collection" for sample in web_samples),
            "collection_status_counts": dict(Counter(sample.get("collection_status") or "missing" for sample in web_samples)),
            "collection_failure_counts": dict(Counter(sample["collection_failure_type"] for sample in web_samples if sample.get("collection_failure_type"))),
            "retrieval_status_counts": dict(Counter(sample.get("retrieval_status") or "unknown" for sample in web_samples)),
            "evidence_coverage": ratio(sum(bool(sample.get("evidence_complete")) for sample in web_valid), len(web_valid), stats),
        })
    result["measurement_targets"] = sorted({sample.get("measurement_target") or "provider_api" for sample in samples})
    if modes == ["search"]:
        result["citation_rate"] = ratio(cited_count, len(valid), stats)
    else:
        result["citation_rate"] = None
    return result


def _summary_only(samples: list[dict], primary_id: int, stats: dict) -> dict:
    valid = [sample for sample in samples if _valid(sample)]
    groups = defaultdict(list)
    for sample in valid:
        groups[_group_key(sample)].append(sample)
    covered = 0
    for answers in groups.values():
        covered += any(_confirmed(_primary(sample, primary_id)) for sample in answers)
    hits = sum(_confirmed(_primary(sample, primary_id)) for sample in valid)
    return {"samples": len(valid), "coverage": ratio(covered, len(groups), stats),
            "hit_rate": ratio(hits, len(valid), stats)}


def _limitations(samples, groups, modes, stats) -> list[str]:
    messages = []
    if not samples:
        messages.append("本周期无回答样本，无法诊断")
    elif not any(_valid(sample) for sample in samples):
        messages.append("没有有效回答；失败或缺失不能解释为零提及")
    if len(groups) < int(stats.get("small_sample_n", 30)):
        messages.append(f"意图×引擎样本不足 {stats.get('small_sample_n', 30)}，仅展示原始计数与方向")
    if len(modes) > 1:
        messages.append("记忆态与检索态不能合并汇总")
    if any(sample.get("engine_kind") == "demo" for sample in samples):
        messages.append("包含演示引擎，结果不代表真实 AI 表现")
    return messages
