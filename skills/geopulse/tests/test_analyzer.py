from backend.app.engine.analyzer import alias_conflicts, alias_pattern, analyze_mentions, evidence_for


def entity(entity_id, name, aliases=None):
    return {"id": entity_id, "name": name, "entity_card": {"aliases": aliases or []}}


def test_alias_boundaries_do_not_match_inside_latin_words():
    entities = [entity(1, "Apple"), entity(2, "Mi")]
    result = analyze_mentions("pineapple 和 xiaomi 都不是这里的 Apple 或 Mi。", entities, demo=True)
    assert result[1]["mentioned"] == 1
    assert result[2]["mentioned"] == 1
    assert result[1]["evidence"] == "pineapple 和 xiaomi 都不是这里的 Apple 或 Mi。"
    assert not alias_pattern("Apple").search("pineapple")
    assert not alias_pattern("Mi").search("xiaomi")


def test_longest_alias_owns_occupied_span():
    entities = [entity(1, "GeoPulse"), entity(2, "Geo", ["GeoPulse Cloud"])]
    result = analyze_mentions("推荐使用 GeoPulse Cloud。", entities, demo=True)
    assert list(result) == [2]
    assert result[2]["matched_alias"] == "GeoPulse Cloud"


def test_negative_and_recommendation_depth():
    entities = [entity(1, "Acme")]
    negative = analyze_mentions("不建议选择 Acme，售后太差。", entities, demo=True)[1]
    positive = analyze_mentions("Acme 支持自托管，值得推荐。", entities, demo=True)[1]
    assert negative["depth"] == "mentioned"
    assert negative["sentiment"] == "negative"
    assert positive["depth"] == "recommended"


def test_short_chinese_alias_requires_review():
    result = analyze_mentions("小米适合智能家居。", [entity(1, "小米")], demo=True)[1]
    assert result["entity_status"] == "unknown"
    assert result["review_status"] == "pending"


def test_alias_conflict_is_explicit():
    conflicts = alias_conflicts([entity(1, "GeoPulse"), entity(2, "Geo", ["GeoPulse Cloud"])])
    assert conflicts
    assert conflicts[0]["brand_a"] == "GeoPulse"
