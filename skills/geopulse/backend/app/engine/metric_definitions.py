"""Versioned metric formulas shared by Run APIs and immutable report appendices."""
from __future__ import annotations

METRICS_VERSION = "geo-metrics-v2.1"

DEFINITIONS = {
    "coverage": {
        "label": "意图覆盖率", "formula": "Σ(weight(g) × covered(g)) / Σweight(g) × 100%",
        "aggregation": "g=canonical_intent_id×engine_config_id；组内至少一轮主品牌确认提及即 covered=1",
        "weighting": "Wave 冻结 stratum_weights；hits/n 始终为未加权原始组计数",
    },
    "hit_rate": {
        "label": "稳定命中率", "formula": "主品牌确认提及的有效回答数 / 有效回答数 × 100%",
        "aggregation": "按有效回答轮次；失败、取消、空、截断不进入分母", "weighting": "未加权",
    },
    "recommendation_coverage": {
        "label": "推荐覆盖率", "formula": "Σ(weight(g) × recommended_covered(g)) / Σweight(g) × 100%",
        "aggregation": "组内至少一轮主品牌为有效推荐", "weighting": "Wave 冻结权重；hits/n 为原始组计数",
    },
    "effective_recommendation_rate": {
        "label": "有效推荐率", "formula": "有效推荐回答数 / 全部有效回答数 × 100%",
        "aggregation": "确认提及、推荐深度且非负面；待复核项仍计入原始公式但必须标 provisional",
        "weighting": "未加权",
    },
    "north_star": {
        "label": "北极星推荐覆盖", "formula": "Σ(weight(g) × recommended_covered(g)) / Σweight(g) × 100%",
        "aggregation": "仅发现型、优先级≥4、适用性为内部确认或客户确认的组",
        "weighting": "Wave 冻结权重；hits/n 为原始组计数",
    },
    "top_choice_rate": {
        "label": "Top Choice Rate", "formula": "有效推荐且标记 Top Choice 的回答数 / 全部有效回答数 × 100%",
        "aggregation": "按有效回答", "weighting": "未加权",
    },
    "negative_risk_rate": {
        "label": "负面风险率", "formula": "主品牌确认提及且负面的回答数 / 主品牌确认提及的有效回答数 × 100%",
        "aggregation": "分母不是全部回答；无有效提及时不能解释为无负面风险", "weighting": "未加权",
    },
    "share_of_voice": {
        "label": "声量份额 SoV", "formula": "每回答 share(e,a)=1/C(a)，组内平均后按冻结权重跨组加权",
        "aggregation": "C(a) 为该回答确认提及的正式实体数；候选不进入正式竞品池",
        "weighting": "主品牌与竞品使用同一组集合、有效样本和权重",
    },
    "citation_rate": {
        "label": "来源引用率", "formula": "主品牌确认提及且关联至少一个白名单 URL 的回答数 / 全部有效回答数 × 100%",
        "aggregation": "仅全 Wave 为 search 时计算；memory 返回 null", "weighting": "未加权",
    },
}


def metric_appendix(metrics: dict) -> dict:
    items = []
    for key, definition in DEFINITIONS.items():
        value = metrics.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and "hits" in value:
            observed = {"hits": value["hits"], "n": value["n"], "value": value["value"],
                        "ci_low": value["ci_low"], "ci_high": value["ci_high"], "limited": value["limited"]}
        else:
            observed = value
        items.append({"key": key, **definition, "observed": observed})
    return {
        "version": METRICS_VERSION,
        "confidence": "比率区间使用 Wilson score，默认 z=1.959963984540054；n=0 的 0 为占位，不是业务零结论。",
        "limitations": metrics.get("limitations") or [],
        "items": items,
    }
