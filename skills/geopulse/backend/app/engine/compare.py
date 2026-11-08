"""Strict, paired wave comparison without causal overclaiming."""
from __future__ import annotations

from ..services.execution import canonical_protocol

REQUIRED_PROTOCOL = (
    "prompt_set_hash", "entity_version", "competitor_pool_hash", "engine_signature", "repeats",
    "answer_execution", "judge_execution", "judge_mode", "language", "market", "judge_version",
    "mode", "measurement_target", "valid_sample_definition", "stratum_weights",
    "use_judge", "collection_protocol", "judge_signature",
)


def protocol_check(baseline: dict, current: dict) -> dict:
    baseline = canonical_protocol(baseline)
    current = canonical_protocol(current)
    mismatches = [key for key in REQUIRED_PROTOCOL if baseline.get(key) != current.get(key)]
    exploratory = baseline.get("reported_model_versions") != current.get("reported_model_versions")
    return {"comparable": not mismatches, "mismatches": mismatches,
            "exploratory": bool(exploratory) and not mismatches,
            "message": "模型供应商返回版本变化，仅作探索性比较" if exploratory and not mismatches else ""}


def compare_metrics(baseline: dict, current: dict, baseline_protocol: dict, current_protocol: dict,
                    min_completeness: float = 0.90) -> dict:
    check = protocol_check(baseline_protocol, current_protocol)
    if not check["comparable"]:
        before_collection = baseline_protocol.get("collection_protocol") or {}
        after_collection = current_protocol.get("collection_protocol") or {}
        cross_surface = (baseline_protocol.get("measurement_target") != current_protocol.get("measurement_target") or
                         before_collection.get("surface") != after_collection.get("surface") or
                         before_collection.get("session_mode") != after_collection.get("session_mode") or
                         before_collection.get("product_url") != after_collection.get("product_url") or
                         before_collection.get("platform") != after_collection.get("platform") or
                         before_collection.get("collection_method") != after_collection.get("collection_method") or
                         before_collection.get("browser_driver") != after_collection.get("browser_driver"))
        result = {**check, "reason": "两次测量口径不同，拒绝输出严格前后变化"}
        if cross_surface:
            result.update({"exploratory": True, "comparison_scope": "cross_surface",
                           "reason": "API/Web 或不同页面、会话上下文不能严格比较；以下仅为各自摘要，不生成 pp 或意图迁移。",
                           "baseline": _without_pairs(baseline), "current": _without_pairs(current),
                           "delta": None, "transitions": [], "transition_counts": {}})
        return result
    before_pairs = baseline.get("pairs") or {}
    after_pairs = current.get("pairs") or {}
    keys = set(before_pairs) & set(after_pairs)
    union = set(before_pairs) | set(after_pairs)
    completeness = len(keys) / len(union) if union else 0.0
    sample_completeness = min(
        float((metrics.get("quality", {}).get("valid_sample_rate", {}).get("value", 0))) / 100
        for metrics in (baseline, current)
    )
    effective_completeness = min(completeness, sample_completeness)
    if effective_completeness < min_completeness:
        return {**check, "comparable": False, "pair_completeness": round(completeness * 100, 2),
                "sample_completeness": round(sample_completeness * 100, 2),
                "reason": f"配对/有效样本完整度 {effective_completeness * 100:.1f}% 低于要求的 {min_completeness * 100:.1f}%"}
    transitions = []
    for key in sorted(keys):
        before, after = before_pairs[key], after_pairs[key]
        old, new = bool(before["covered"]), bool(after["covered"])
        state = "持续提及" if old and new else "新增提及" if new else "失去提及" if old else "持续缺席"
        transitions.append({"key": key, "canonical_intent_id": before["canonical_intent_id"],
                            "engine_config_id": before["engine_config_id"], "prompt_text": before["prompt_text"],
                            "dimension": before["dimension"], "before": before, "after": after, "change": state})
    delta = {}
    for metric in ("coverage", "hit_rate", "recommendation_coverage", "effective_recommendation_rate", "north_star"):
        delta[metric] = {"pp": round(current[metric]["value"] - baseline[metric]["value"], 2),
                         "baseline": baseline[metric], "current": current[metric],
                         "relative": None if not baseline[metric]["value"] else round(
                             (current[metric]["value"] - baseline[metric]["value"]) / baseline[metric]["value"] * 100, 2)}
    counts = {state: sum(item["change"] == state for item in transitions)
              for state in ("持续提及", "持续缺席", "新增提及", "失去提及")}
    return {**check, "pair_completeness": round(completeness * 100, 2),
            "sample_completeness": round(sample_completeness * 100, 2), "baseline": _without_pairs(baseline),
            "current": _without_pairs(current), "delta": delta, "transitions": transitions,
            "transition_counts": counts,
            "interpretation": "仅陈述同口径样本变化；模型换版、检索波动、竞品动作和样本噪声不能排除。"}


def _without_pairs(metrics: dict) -> dict:
    return {key: value for key, value in metrics.items() if key != "pairs"}
