from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.db import connect, one
from backend.app.services.scheduler import run_due_schedules
from conftest import api, demo_wave


def past_time() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")


def test_recurring_schedule_advances_without_catch_up_burst_and_pauses(client):
    wave = demo_wave(client)
    schedule = api(client, "POST", f"/api/projects/{client.project_id}/schedules",
                   json={"wave_id": wave["id"], "recurrence_days": 7})
    assert schedule["anchor_at"] == wave["anchor_at"]
    with connect() as conn:
        conn.execute("UPDATE schedules SET next_run_at=?,scheduled_at=? WHERE id=?", (past_time(), past_time(), schedule["id"]))
        conn.commit()
    assert run_due_schedules() == 1
    with connect() as conn:
        current = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule["id"],))
        assert current["status"] == "pending" and current["next_run_at"] > current["scheduled_at"]
        assert current["next_run_at"] > datetime.now(timezone.utc).isoformat(timespec="seconds")
    assert run_due_schedules() == 0
    paused = api(client, "PUT", f"/api/projects/{client.project_id}/schedules/{schedule['id']}", json={"status": "paused"})
    assert paused["status"] == "paused"
    resumed = api(client, "PUT", f"/api/projects/{client.project_id}/schedules/{schedule['id']}", json={"status": "pending"})
    assert resumed["status"] == "pending"


def test_schedule_budget_block_is_actionable_and_alert_ack_is_audited(client):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "调度预算引擎", "vendor": "Test", "kind": "openai_compat", "model": "test",
        "base_url": "https://example.test/v1", "api_key": "test-only", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 1000, "output_per_million": 1000,
                      "estimated_input_tokens": 1000, "estimated_output_tokens": 1000},
    })
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "调度预算 Wave", "engine_ids": [engine["id"]],
        "repeats": 1, "use_judge": True,
    })
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"budget": {
        "enabled": True, "hard_limit": True, "amount": 0, "currency": "CNY"}}})
    schedule = api(client, "POST", f"/api/projects/{client.project_id}/schedules",
                   json={"wave_id": wave["id"], "scheduled_at": past_time()})
    assert run_due_schedules() == 0
    with connect() as conn:
        blocked = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule["id"],))
        assert blocked["status"] == "blocked" and blocked["last_error"]
    alerts = api(client, "GET", f"/api/projects/{client.project_id}/alerts")["items"]
    budget_alert = next(item for item in alerts if item["kind"] == "budget")
    api(client, "POST", f"/api/projects/{client.project_id}/alerts/{budget_alert['id']}/ack")
    assert all(item["id"] != budget_alert["id"] for item in api(client, "GET", f"/api/projects/{client.project_id}/alerts")["items"])
    history = api(client, "GET", f"/api/projects/{client.project_id}/alerts?history=true")["items"]
    assert next(item for item in history if item["id"] == budget_alert["id"])["status"] == "acknowledged"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_type='alert' AND object_id=? AND action='acknowledge'",
                   (str(budget_alert["id"]),))["count"] == 1


def test_backup_failure_is_recorded_without_exposing_internal_error(client, monkeypatch):
    def fail_backup():
        raise OSError("private disk path unavailable")
    monkeypatch.setattr("backend.app.api.admin.backup", fail_backup)
    error = api(client, "POST", f"/api/projects/{client.project_id}/backup", expected=500)
    assert "private disk path" not in str(error)
    with connect() as conn:
        run = one(conn, "SELECT * FROM backup_runs WHERE project_id=?", (client.project_id,))
        assert run["status"] == "failed"
        assert one(conn, "SELECT * FROM alerts WHERE project_id=? AND kind='backup_failed'", (client.project_id,))["status"] == "open"
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_type='database' AND action='backup'")["count"] == 1


def test_work_log_has_business_date_and_audit(client):
    row = api(client, "POST", f"/api/projects/{client.project_id}/work-logs",
              json={"hours": 1.5, "kind": "证据复核", "note": "复核基线", "work_date": "2026-11-06"})
    assert row["work_date"] == "2026-11-06"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_type='work_log' AND object_id=?",
                   (str(row["id"]),))["count"] == 1
