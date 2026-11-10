from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.db import connect, one
from conftest import api, demo_wave, execute_run


def make_official(client, label):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    return wave, run


def create_gap(client, run_id):
    answers = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/answers")["items"]
    answer = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answers[0]['id']}")
    primary = next(item for item in answer["observations"] if item["role"] == "primary")
    competitor = next(item for item in answer["observations"] if item["role"] == "competitor")
    for observation, payload in (
        (primary, {"entity_status": "confirmed", "mentioned": False, "depth": "absent", "sentiment": "unknown", "evidence": ""}),
        (competitor, {"entity_status": "confirmed", "mentioned": True, "depth": "recommended", "sentiment": "positive", "evidence": answer["raw_text"]}),
    ):
        api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/observations/{observation['id']}/revisions",
            json={**payload, "top_choice": observation["role"] == "competitor", "reason": "构造可复核的机会基线", "arbitrate": True})


def make_action(client, baseline, target):
    created = api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/opportunities/generate", json={})
    assert created["count"] >= 1
    opportunity = created["items"][0]
    api(client, "POST", f"/api/projects/{client.project_id}/opportunities/{opportunity['id']}/review", json={
        "decision": "confirmed", "eligibility": "client_confirmed", "business_value": 4, "executability": 4, "reason": "测试适用性",
    })
    action = api(client, "POST", f"/api/projects/{client.project_id}/opportunities/{opportunity['id']}/actions", json={
        "title": "复测验证专项", "geo_step": 3, "target_wave_id": target["id"],
    })
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={"status": "review"})
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={"status": "approved"})
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={
        "status": "published", "published_at": published_at, "published_url": "https://example.com/remeasure", "artifact_version": "v1",
    })
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={
        "status": "remeasure_due", "target_wave_id": target["id"], "remeasure_days": 14,
    })
    with connect() as conn:
        schedule = one(conn, "SELECT * FROM schedules WHERE action_id=?", (action["id"],))
        assert schedule and schedule["wave_id"] == target["id"] and schedule["anchor_at"] == published_at
    listed = api(client, "GET", f"/api/projects/{client.project_id}/actions")["items"][0]
    assert listed["opportunity_wave_id"] == baseline["id"]
    return action


def test_action_outcome_rejects_baseline_as_its_own_remeasurement(client):
    baseline, run = make_official(client, "基线")
    create_gap(client, run["id"])
    action = make_action(client, baseline, baseline)
    for status in ("verified", "not_effective"):
        error = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status",
                    json={"status": status, "reason": "错误地把基线当作复测"}, expected=409)
        assert "不能是机会来源的基线" in error["detail"]


@pytest.mark.parametrize("improved", [False, True])
def test_action_outcome_requires_strict_formal_comparison(client, improved):
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"small_sample_n": 1}})
    baseline, baseline_run = make_official(client, "基线")
    create_gap(client, baseline_run["id"])
    target, target_run = make_official(client, "复测")
    if not improved:
        create_gap(client, target_run["id"])
    action = make_action(client, baseline, target)
    response = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status",
                   json={"status": "verified", "reason": "按正式 Run 与同口径比较判断"},
                   expected=200 if improved else 409)
    if not improved:
        assert "未显示对应指标改善" in response["detail"]
        response = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status",
                       json={"status": "not_effective", "reason": "同口径复测未见改善"})
    assert response["status"] == ("verified" if improved else "not_effective")
    with connect() as conn:
        event = one(conn, "SELECT * FROM audit_events WHERE object_type='action' AND object_id=? AND action='remeasurement_verified'", (str(action["id"]),))
        assert event and '"delta"' in event["after_json"]
