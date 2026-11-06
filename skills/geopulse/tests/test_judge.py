import json

from backend.app.engine.judge import judge_answer
from backend.app.providers.base import ProviderResult


class JudgeProvider:
    def __init__(self, payload):
        self.payload = payload

    def ask_json(self, prompt, protocol):
        return ProviderResult(text=json.dumps(self.payload, ensure_ascii=False), model="judge-test", usage={"prompt_tokens": 10},
                              request_id="judge-request", operations=[{"kind": "judge", "usage": {"prompt_tokens": 10}}])


def entities():
    return [{"id": 1, "name": "GeoPulse", "role": "primary", "entity_card": {"aliases": ["Geo Pulse"]}},
            {"id": 2, "name": "Profound", "role": "competitor", "entity_card": {}}]


def test_judge_validates_entities_evidence_citations_and_negative_recommendation():
    raw = "不建议选择 GeoPulse。Profound 值得推荐。"
    result, discovered, judged = judge_answer(JudgeProvider({"brands": [
        {"entity_id": 1, "entity_status": "confirmed", "mentioned": True, "depth": "recommended",
         "sentiment": "negative", "evidence": "不建议选择 GeoPulse。", "citation_urls": ["https://example.com/a"]},
        {"entity_id": 2, "entity_status": "confirmed", "mentioned": True, "depth": "recommended",
         "sentiment": "positive", "evidence": "hallucinated evidence", "citation_urls": ["https://not-returned.test"]},
    ], "discovered_entities": [{"name": "NewBrand", "evidence": "not in raw"}]}), raw, entities(), {},
        [{"url": "https://example.com/a"}])
    assert result[0]["depth"] == "mentioned"
    assert result[0]["top_choice"] == 0
    assert result[0]["citation_urls"] == ["https://example.com/a"]
    assert result[1]["judge_status"] == "llm-judge-evidence-fallback"
    assert result[1]["review_status"] == "pending"
    assert result[1]["evidence"] == "Profound 值得推荐。"
    assert result[1]["citation_urls"] == []
    assert discovered[0]["name"] == "NewBrand" and discovered[0]["evidence"] == ""
    assert judged.model == "judge-test"


def test_missing_judge_entity_is_pending_not_a_confirmed_absence():
    result, _, _ = judge_answer(JudgeProvider({"brands": [], "discovered_entities": []}),
                                "GeoPulse", entities(), {}, [])
    assert len(result) == 2
    assert all(item["entity_status"] == "unknown" for item in result)
    assert all(item["review_status"] == "pending" for item in result)
