from __future__ import annotations

import pytest

from backend.app.db import connect, loads, one
from backend.app.engine.metrics import calculate_metrics
from backend.app.providers.openai_compat import OpenAICompatProvider
from backend.app.providers.base import ProviderError
from conftest import api, demo_wave, execute_run


def production_engine(client, **cost_rule):
    return api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "预算测试引擎", "vendor": "Test", "kind": "openai_compat", "model": "frozen-v1",
        "base_url": "https://example.test/v1", "api_key": "test-only-secret", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 1000, "output_per_million": 1000,
                      "estimated_input_tokens": 1000, "estimated_output_tokens": 1000, **cost_rule},
    })


def production_wave(client, engine):
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    return api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "预算测试 Wave", "engine_ids": [engine["id"]],
        "repeats": 1, "use_judge": False,
    })


def set_budget(client, **values):
    budget = {"enabled": True, "hard_limit": True, "amount": None, "wave_amount": None,
              "daily_amount": None, "currency": "CNY", **values}
    return api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"budget": budget}})


def test_hard_budget_counts_active_reservation_and_cancel_releases(client):
    engine = production_engine(client)
    wave = production_wave(client, engine)
    estimate = wave["estimate"]
    set_budget(client, amount=estimate["max_estimated_cost"])
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
              json={"confirm_judge_disabled": True})["run"]
    error = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
                json={"confirm_judge_disabled": True}, expected=409)
    assert error["detail"]["code"] == "budget_exceeded"
    with connect() as conn:
        reservation = one(conn, "SELECT * FROM budget_reservations WHERE run_id=?", (run["id"],))
        assert reservation["status"] == "active"
        assert reservation["amount"] == estimate["max_estimated_cost"]
    api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/cancel")
    with connect() as conn:
        assert one(conn, "SELECT status FROM budget_reservations WHERE id=?", (reservation["id"],))["status"] == "released"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
        json={"confirm_judge_disabled": True})


def test_soft_budget_requires_reason_and_writes_audit(client):
    engine = production_engine(client)
    wave = production_wave(client, engine)
    set_budget(client, hard_limit=False, amount=0.01)
    error = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
                json={"confirm_judge_disabled": True}, expected=409)
    assert error["detail"]["code"] == "budget_confirmation_required"
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
              json={"budget_confirmation_reason": "客户已确认本次补充测量费用", "confirm_judge_disabled": True})["run"]
    with connect() as conn:
        reservation = one(conn, "SELECT * FROM budget_reservations WHERE run_id=?", (run["id"],))
        assert reservation["confirmed_reason"] == "客户已确认本次补充测量费用"
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_id=? AND action='budget_override'",
                   (str(run["id"]),))["count"] == 1


def test_hard_budget_rejects_unknown_price_and_reports_daily_wave_scopes(client):
    engine = production_engine(client, input_per_million=None)
    wave = production_wave(client, engine)
    set_budget(client, amount=100, daily_amount=100, wave_amount=100)
    error = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
                json={"confirm_judge_disabled": True}, expected=409)
    assert error["detail"]["code"] == "budget_cost_unknown"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM runs WHERE wave_id=?", (wave["id"],))["count"] == 0

    api(client, "PUT", f"/api/projects/{client.project_id}/engines/{engine['id']}", json={
        "name": engine["name"], "vendor": "Test", "kind": "openai_compat", "model": "changed-v2",
        "base_url": "https://example.test/v1", "api_key": "__KEEP__", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 1000, "output_per_million": 1000,
                      "estimated_input_tokens": 1000, "estimated_output_tokens": 1000},
    })
    # Wave 冻结的缺失价格不会被后续补价静默改写。
    assert api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
               json={"confirm_judge_disabled": True}, expected=409)["detail"]["code"] == "budget_cost_unknown"


def test_run_snapshot_is_frozen_and_public_response_has_no_secret_or_price(client):
    engine = production_engine(client)
    wave = production_wave(client, engine)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
              json={"confirm_judge_disabled": True})["run"]
    assert "secret_ref" not in str(run) and "cost_rule" not in str(run)
    api(client, "PUT", f"/api/projects/{client.project_id}/engines/{engine['id']}", json={
        "name": "修改后的引擎", "vendor": "Test", "kind": "openai_compat", "model": "changed-v2",
        "base_url": "https://example.test/v2", "api_key": "replacement-test-secret", "mode": "memory",
        "cost_rule": {"currency": "USD", "input_per_million": 1, "output_per_million": 1},
    })
    detail = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}")
    assert detail["snapshot"]["engines"][0]["model"] == "frozen-v1"
    assert "replacement-test-secret" not in str(detail) and "secret_ref" not in str(detail)
    with connect() as conn:
        frozen = loads(one(conn, "SELECT snapshot_json FROM runs WHERE id=?", (run["id"],))["snapshot_json"])
        assert frozen["engines"][0]["model"] == "frozen-v1"
        assert frozen["engines"][0]["cost_rule"]["currency"] == "CNY"


def test_health_check_uses_shared_ledger_and_releases_operation(client):
    set_budget(client, amount=0)
    engine = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"][0]
    result = api(client, "POST", f"/api/projects/{client.project_id}/engines/{engine['id']}/health", json={})
    assert result["status"] == "healthy"
    with connect() as conn:
        attempt = one(conn, "SELECT * FROM call_attempts WHERE project_id=? AND kind='health'", (client.project_id,))
        assert attempt["operation"] == "answer" and attempt["cost"] == 0
        assert one(conn, "SELECT status FROM budget_reservations WHERE operation_id LIKE 'health-%'")["status"] == "released"


def test_persisted_valid_sample_survives_raw_content_purge():
    sample = {"status": "succeeded", "raw_text": None, "valid_sample": 1, "engine_config_id": 1,
              "canonical_intent_id": "intent", "engine_kind": "demo", "engine_mode": "memory",
              "observations": [{"brand_entity_id": 7, "entity_status": "confirmed", "mentioned": 1,
                                "depth": "recommended", "sentiment": "positive", "citation_urls": []}]}
    metrics = calculate_metrics([sample], 7, {"small_sample_n": 30})
    assert metrics["quality"]["valid_samples"] == 1
    assert metrics["hit_rate"]["hits"] == 1


def test_provider_validation_failure_preserves_usage():
    provider = OpenAICompatProvider("https://example.test/v1", "secret", "model")
    provider._post = lambda *args: ({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
                                     "model": "response-model", "usage": {"prompt_tokens": 12, "completion_tokens": 3}}, 25, "request-1")
    with pytest.raises(ProviderError) as caught:
        provider.ask("test", {})
    operation = caught.value.operations[0]
    assert caught.value.kind == "empty_answer"
    assert operation["status"] == "failed" and operation["usage"]["prompt_tokens"] == 12
    assert operation["request_id"] == "request-1" and operation["latency_ms"] == 25
