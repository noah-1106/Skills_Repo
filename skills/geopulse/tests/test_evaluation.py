from pathlib import Path

from backend.app.services.evaluation import classification_report, evaluate_dataset


ROOT = Path(__file__).resolve().parent.parent


def test_golden_dataset_reports_all_evaluation_dimensions():
    report = evaluate_dataset(ROOT / "evaluation" / "golden.json")
    assert report["answer_cases"]["count"] == 12
    assert report["answer_cases"]["passed"] == 12
    assert report["entity_detection"]["accuracy"] == 1
    assert report["depth"]["accuracy"] == 1
    assert report["sentiment"]["accuracy"] == 1
    assert report["source_type"]["accuracy"] == 1
    assert report["citation_contract"]["precision"] == 1
    assert report["citation_contract"]["recall"] == 1
    assert report["citation_contract"]["fp"] == 0
    assert report["citation_contract"]["evidence_fallback_checks_passed"] == 2
    for field in ("entity_detection", "depth", "sentiment", "source_type"):
        assert report[field]["confusion_matrix"]
        assert report[field]["micro"]["f1"] == 1


def test_classification_report_has_real_confusion_counts():
    report = classification_report(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert report["per_label"]["a"] == {
        "precision": 1.0, "recall": 0.5, "f1": 0.6667, "support": 2, "tp": 1, "fp": 0, "fn": 1,
    }
    assert report["confusion_matrix"]["a"]["b"] == 1
    assert report["accuracy"] == 0.6667
