from backend.app.engine.compare import compare_metrics, protocol_check


def protocol():
    return {key: "same" for key in (
        "prompt_set_hash", "entity_version", "competitor_pool_hash", "engine_signature", "repeats",
        "temperature", "system_prompt", "max_tokens", "language", "market", "judge_version", "mode",
        "measurement_target", "valid_sample_definition", "stratum_weights")} | {"reported_model_versions": {"1": "v1"}}


def metric(covered=True, valid_rate=100):
    pairs = {"1:intent": {"canonical_intent_id": "intent", "engine_config_id": 1,
                         "covered": covered, "prompt_text": "question", "dimension": "choice"}}
    rates = {key: {"value": 50 if covered else 0, "hits": 1, "n": 2} for key in (
        "coverage", "hit_rate", "recommendation_coverage", "effective_recommendation_rate", "north_star")}
    return {**rates, "pairs": pairs, "quality": {"valid_sample_rate": {"value": valid_rate}}}


def test_protocol_mismatch_rejects_strict_comparison():
    before, after = protocol(), protocol()
    after["repeats"] = 1
    result = compare_metrics(metric(), metric(), before, after)
    assert not result["comparable"]
    assert "repeats" in result["mismatches"]


def test_model_version_change_is_exploratory_not_causal():
    before, after = protocol(), protocol()
    after["reported_model_versions"] = {"1": "v2"}
    result = compare_metrics(metric(), metric(), before, after)
    assert result["comparable"] and result["exploratory"]
    assert "探索性" in result["message"]


def test_pair_completeness_must_meet_threshold():
    before, after = metric(), metric()
    after["pairs"] = {}
    result = compare_metrics(before, after, protocol(), protocol(), 0.9)
    assert not result["comparable"]
    assert result["pair_completeness"] == 0


def test_valid_sample_completeness_is_checked_even_with_matching_pair_keys():
    result = compare_metrics(metric(), metric(valid_rate=75), protocol(), protocol(), 0.9)
    assert not result["comparable"]
    assert result["sample_completeness"] == 75


def test_zero_baseline_has_no_infinite_relative_lift():
    result = compare_metrics(metric(covered=False), metric(covered=True), protocol(), protocol())
    assert result["delta"]["coverage"]["relative"] is None
    assert result["delta"]["coverage"]["pp"] == 50
    assert result["transition_counts"]["新增提及"] == 1
