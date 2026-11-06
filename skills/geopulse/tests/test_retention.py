from __future__ import annotations

from backend.app.db import connect, one
from conftest import api


def test_retention_defaults_to_noop(client, official_demo):
    _, run_id = official_demo
    preview = api(client, "GET", f"/api/projects/{client.project_id}/retention/preview")
    assert not preview["enabled"] and preview["candidate_count"] == 0
    result = api(client, "POST", f"/api/projects/{client.project_id}/retention/execute", json={"confirm": True})
    assert result["status"] == "skipped"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=? AND raw_text IS NOT NULL", (run_id,))["count"] > 0
        assert one(conn, "SELECT COUNT(*) AS count FROM retention_runs")["count"] == 0


def test_retention_purge_preserves_metrics_and_blocks_new_revision(client, official_demo):
    wave_id, run_id = official_demo
    before = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/metrics")
    with connect() as conn:
        conn.execute("UPDATE answers SET completed_at='2020-01-01T00:00:00+00:00' WHERE run_id=?", (run_id,))
        conn.commit()
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"retention_days": 30}})
    preview = api(client, "GET", f"/api/projects/{client.project_id}/retention/preview")
    assert preview["candidate_count"] == before["quality"]["valid_samples"]
    api(client, "POST", f"/api/projects/{client.project_id}/retention/execute", json={}, expected=409)
    result = api(client, "POST", f"/api/projects/{client.project_id}/retention/execute", json={"confirm": True})
    assert result["purged_count"] == preview["candidate_count"]
    after = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/metrics")
    assert after["quality"]["valid_samples"] == before["quality"]["valid_samples"]
    assert after["hit_rate"] == before["hit_rate"]
    answers = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/answers")["items"]
    answer_id = answers[0]["id"]
    detail = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer_id}")
    assert detail["raw_text"] is None and detail["content_retained"] == 0 and detail["content_purged_at"]
    observation = detail["observations"][0]
    error = api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer_id}/observations/{observation['id']}/revisions",
                expected=409, json={"entity_status": "confirmed", "mentioned": True, "depth": "mentioned",
                                    "sentiment": "neutral", "evidence": "x", "reason": "清理后不应允许", "arbitrate": True})
    assert "保留策略" in error["detail"]
    with connect() as conn:
        run = one(conn, "SELECT * FROM retention_runs WHERE project_id=?", (client.project_id,))
        assert run["purged_count"] == result["purged_count"]
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_type='retention' AND action='execute'")["count"] == 1
