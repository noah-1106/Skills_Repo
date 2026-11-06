from __future__ import annotations

import hashlib

from backend.app.db import connect, one
from conftest import api, demo_wave, execute_run


def make_official(client, label="正式 Wave"):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    return wave, run


def test_every_wave_must_pass_release_gate_not_only_latest(client):
    baseline, baseline_run = make_official(client)
    current, _ = make_official(client)
    with connect() as conn:
        answer = one(conn, "SELECT id FROM answers WHERE run_id=? LIMIT 1", (baseline_run["id"],))
        conn.execute("UPDATE answers SET status='failed',valid_sample=0 WHERE id=?", (answer["id"],))
        conn.commit()
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports",
                 json={"wave_ids": [baseline["id"], current["id"]]})
    detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")
    assert any("有效样本完整度" in error for error in detail["gates"])
    error = api(client, "POST", f"/api/projects/{client.project_id}/reports/{report['id']}/status",
                json={"status": "data_checked"}, expected=409)
    assert error["detail"]["message"] == "报告发布闸门未通过"


def test_purged_raw_evidence_blocks_new_report_but_old_snapshot_is_unchanged(client):
    wave, run = make_official(client)
    old_report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [wave["id"]]})
    old_detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{old_report['id']}")
    with connect() as conn:
        conn.execute("UPDATE answers SET completed_at='2020-01-01T00:00:00+00:00' WHERE run_id=?", (run["id"],))
        conn.commit()
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"retention_days": 30}})
    api(client, "POST", f"/api/projects/{client.project_id}/retention/execute", json={"confirm": True})
    new_report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [wave["id"]]})
    detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{new_report['id']}")
    assert any("原文已按保留策略清理" in error for error in detail["gates"])
    unchanged = api(client, "GET", f"/api/projects/{client.project_id}/reports/{old_report['id']}")
    assert unchanged["data_snapshot_hash"] == old_detail["data_snapshot_hash"]
    assert unchanged["snapshot"] == old_detail["snapshot"]


def test_report_export_uses_saved_html_and_records_checksum(client, monkeypatch):
    wave, _ = make_official(client)
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [wave["id"]]})
    monkeypatch.setattr("backend.app.services.reporting.render_reports", lambda snapshot: (_ for _ in ()).throw(AssertionError("不应重排旧报告")))
    response = client.get(f"/api/projects/{client.project_id}/reports/{report['id']}/export?variant=client&format=html")
    assert response.status_code == 200
    assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert response.headers["x-data-snapshot-sha256"] == report["data_snapshot_hash"]
    assert "样本量较小，仅用于观察方向" in response.text
    with connect() as conn:
        event = one(conn, "SELECT * FROM audit_events WHERE object_type='report' AND object_id=? AND action='export'", (str(report["id"]),))
        assert event and response.headers["x-content-sha256"] in event["after_json"]
