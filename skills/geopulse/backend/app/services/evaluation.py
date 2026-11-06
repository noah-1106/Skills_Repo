"""Offline golden-set regression reports; no provider network calls."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ..db import utc_now
from ..engine.judge import judge_answer
from ..engine.judge import fallback_observations
from ..providers.base import ProviderResult
from .measurement import _classify_source


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def classification_report(gold: list[str], predicted: list[str], labels: list[str]) -> dict:
    pairs = Counter(zip(gold, predicted))
    per_label = {}
    for label in labels:
        tp = pairs[(label, label)]
        fp = sum(count for (actual, guess), count in pairs.items() if actual != label and guess == label)
        fn = sum(count for (actual, guess), count in pairs.items() if actual == label and guess != label)
        support = sum(count for (actual, _), count in pairs.items() if actual == label)
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        per_label[label] = {"precision": precision, "recall": recall,
                            "f1": _ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0,
                            "support": support, "tp": tp, "fp": fp, "fn": fn}
    tp = sum(pairs[(label, label)] for label in labels)
    fp = sum(count for (actual, guess), count in pairs.items() if actual != guess)
    fn = fp
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {
        "labels": labels, "support": len(gold), "accuracy": _ratio(tp, len(gold)),
        "micro": {"precision": precision, "recall": recall,
                  "f1": _ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0},
        "macro": {key: round(sum(row[key] for row in per_label.values()) / len(labels), 4)
                  for key in ("precision", "recall", "f1")},
        "per_label": per_label,
        "confusion_matrix": {actual: {guess: pairs[(actual, guess)] for guess in labels} for actual in labels},
    }


class _JudgeFixture:
    def __init__(self, item: dict):
        self.item = item

    def ask_json(self, prompt: str, protocol: dict) -> ProviderResult:
        return ProviderResult(text=json.dumps({"brands": [self.item], "discovered_entities": []}, ensure_ascii=False),
                              model="offline-fixture", request_id="golden-fixture")


def evaluate_dataset(path: Path) -> dict:
    raw = path.read_bytes()
    data = json.loads(raw)
    entities = {int(entity["id"]): entity for entity in data["entities"]}
    observed = {"mentioned": [], "depth": [], "sentiment": []}
    expected = {"mentioned": [], "depth": [], "sentiment": []}
    evidence_checks = []
    case_results = []
    for case in data["answer_cases"]:
        roster = [entities[int(entity_id)] for entity_id in case["expected"]]
        predictions = {item["brand_entity_id"]: item for item in fallback_observations(case["answer"], roster)}
        for entity_id_text, gold in case["expected"].items():
            prediction = predictions[int(entity_id_text)]
            for field in observed:
                if field == "mentioned":
                    expected[field].append("mentioned" if gold[field] else "absent")
                    observed[field].append("mentioned" if prediction[field] else "absent")
                else:
                    expected[field].append(gold[field])
                    observed[field].append(prediction[field])
            evidence_checks.append(prediction["evidence"] == gold["evidence"])
        case_results.append({"id": case["id"], "passed": all(
            (bool(predictions[int(entity_id)]["mentioned"]) == bool(gold["mentioned"])
             and predictions[int(entity_id)]["depth"] == gold["depth"]
             and predictions[int(entity_id)]["sentiment"] == gold["sentiment"]
             and predictions[int(entity_id)]["evidence"] == gold["evidence"])
            for entity_id, gold in case["expected"].items())})

    settings = {"source_domains": {
        "baike.baidu.com": "百科", "zh.wikipedia.org": "百科",
        "zhihu.com": "UGC", "xiaohongshu.com": "UGC",
    }}
    source_gold = [case["expected"] for case in data["source_cases"]]
    source_predicted = [_classify_source(case["url"], entities[1], settings) for case in data["source_cases"]]

    citation_tp = citation_fp = citation_fn = 0
    citation_cases = 0
    contract_checks = []
    for case in data["citation_cases"]:
        entity = entities[case["entity_id"]]
        observations, _, _ = judge_answer(_JudgeFixture(case["judge_item"]), case["answer"], [entity], {}, case["citations"])
        actual_urls = set(observations[0]["citation_urls"])
        expected_urls = set(case["expected_urls"])
        citation_tp += len(actual_urls & expected_urls)
        citation_fp += len(actual_urls - expected_urls)
        citation_fn += len(expected_urls - actual_urls)
        citation_cases += int(actual_urls == expected_urls)
        contract_checks.append(observations[0]["evidence"] == case["answer"])
    citation_precision = _ratio(citation_tp, citation_tp + citation_fp)
    citation_recall = _ratio(citation_tp, citation_tp + citation_fn)
    return {
        "evaluator": "offline-deterministic-v1", "generated_at": utc_now(),
        "dataset": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "version": data["version"]},
        "scope": "规则回退、Judge 后处理与来源分类回归；不是外部 LLM 的生产准确率评估。",
        "answer_cases": {"count": len(data["answer_cases"]), "passed": sum(case["passed"] for case in case_results),
                         "results": case_results, "evidence_exact_rate": _ratio(sum(evidence_checks), len(evidence_checks))},
        "entity_detection": classification_report(expected["mentioned"], observed["mentioned"], ["mentioned", "absent"]),
        "depth": classification_report(expected["depth"], observed["depth"], ["absent", "mentioned", "described", "recommended"]),
        "sentiment": classification_report(expected["sentiment"], observed["sentiment"], ["unknown", "neutral", "positive", "negative"]),
        "source_type": classification_report(source_gold, source_predicted, ["官网", "百科", "UGC", "其他"]),
        "citation_contract": {"tp": citation_tp, "fp": citation_fp, "fn": citation_fn,
                              "precision": citation_precision, "recall": citation_recall,
                              "f1": _ratio(2 * citation_precision * citation_recall, citation_precision + citation_recall)
                              if citation_precision + citation_recall else 0.0,
                              "exact_case_rate": _ratio(citation_cases, len(data["citation_cases"])),
                              "evidence_fallback_checks_passed": sum(contract_checks),
                              "evidence_fallback_checks": len(contract_checks)},
    }
