import pytest

from backend.app.engine.metrics import calculate_metrics, wilson


def sample(answer_id, intent, observations, *, weight=1, status="succeeded", raw="answer", query="discovery", priority=5, eligibility="eligible", engine=1, dimension="choice"):
    return {
        "id": answer_id, "canonical_intent_id": intent, "engine_config_id": engine,
        "dimension": dimension, "prompt_text": intent, "query_type": query,
        "priority": priority, "eligibility": eligibility, "weight": weight,
        "status": status, "raw_text": raw, "engine_name": "test", "engine_mode": "memory", "engine_kind": "real",
        "observations": list(observations.values()),
    }


def observation(brand, *, status="confirmed", mentioned=1, depth="recommended", sentiment="positive", top=0, citations=None, review="machine", judge="judge-v2"):
    return {"brand_entity_id": brand, "name": str(brand), "role": "primary" if brand == 1 else "competitor",
            "entity_status": status, "mentioned": mentioned, "depth": depth, "sentiment": sentiment,
            "top_choice": top, "citation_urls": citations or [], "evidence": "evidence", "review_status": review,
            "judge_status": judge}


def absent(brand=1):
    return observation(brand, mentioned=0, depth="absent", sentiment="unknown")


def test_wilson_interval_has_expected_small_sample_bounds():
    low, high = wilson(8, 8)
    assert low == pytest.approx(67.56, abs=0.01)
    assert high == 100
    assert wilson(0, 0) == (0, 0)


def test_failed_empty_and_cancelled_samples_are_not_zero_mentions():
    samples = [
        sample(1, "intent-a", {1: absent()}, raw=None, status="failed"),
        sample(2, "intent-b", {1: absent()}, raw="", status="succeeded"),
        sample(3, "intent-c", {1: absent()}, status="cancelled"),
    ]
    result = calculate_metrics(samples, 1)
    assert result["hit_rate"]["n"] == 0
    assert result["coverage"]["n"] == 0
    assert result["quality"]["failed_samples"] == 1
    assert result["quality"]["cancelled_samples"] == 1
    assert "没有有效回答" in result["limitations"][0]


def test_sov_uses_same_weighted_groups_for_primary_and_competitor():
    samples = [
        sample(1, "high", {1: observation(1), 2: observation(2)}, weight=3),
        sample(2, "low", {2: observation(2)}, weight=1),
    ]
    result = calculate_metrics(samples, 1)
    primary = next(row for row in result["competitors"] if row["brand_entity_id"] == 1)
    competitor = next(row for row in result["competitors"] if row["brand_entity_id"] == 2)
    assert primary["sov"] == result["share_of_voice"]["value"] == 37.5
    assert competitor["sov"] == 62.5


def test_north_star_excludes_navigation_and_unconfirmed_eligibility():
    samples = [
        sample(1, "eligible", {1: observation(1)}),
        sample(2, "navigation", {1: observation(1)}, query="navigation"),
        sample(3, "unknown", {1: observation(1)}, eligibility="unknown"),
        sample(4, "low-priority", {1: observation(1)}, priority=2),
    ]
    result = calculate_metrics(samples, 1)
    assert result["north_star"]["hits"] == 1
    assert result["north_star"]["n"] == 1
    assert result["hit_rate"]["n"] == 4


def test_negative_recommendation_and_unknown_entity_do_not_count():
    samples = [sample(1, "a", {
        1: observation(1, depth="recommended", sentiment="negative"),
        2: observation(2, status="unknown"),
    })]
    result = calculate_metrics(samples, 1)
    assert result["effective_recommendation_rate"]["hits"] == 0
    assert result["negative_risk_rate"]["hits"] == 1
    assert result["share_of_voice"]["value"] == 100


def test_citation_rate_only_exists_for_search():
    search = sample(1, "a", {1: observation(1, citations=["https://example.com/a"])})
    search["engine_mode"] = "search"
    assert calculate_metrics([search], 1)["citation_rate"]["value"] == 100
    assert calculate_metrics([sample(2, "a", {1: observation(1)})], 1)["citation_rate"] is None
