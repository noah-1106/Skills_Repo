from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.db import connect, one
from backend.app.main import create_app
from conftest import ADMIN_PASSWORD, api, demo_wave, execute_run


def test_login_me_csrf_and_project_scoped_api(client):
    me = api(client, "GET", "/api/auth/me")
    assert me["user"]["email"] == "admin@test.local"
    project_id = client.project_id
    api(client, "PUT", f"/api/projects/{project_id}/settings", expected=403,
        headers={"X-CSRF-Token": "wrong"}, json={"settings": {"small_sample_n": 20}})
    overview = api(client, "GET", f"/api/projects/{project_id}/overview")
    assert overview["stage"] == "基线测量"
    assert overview["role"] == "admin"
    assert client.get("/").status_code == 200
    assert "default-src 'self'" in client.get("/").headers["Content-Security-Policy"]


def test_non_admin_only_sees_assigned_projects(client):
    other = api(client, "POST", "/api/projects", json={"client_name": "另一客户", "name": "隔离项目"})
    user = api(client, "POST", "/api/users", json={"email": "viewer@test.local", "password": "viewer-password"})
    api(client, "POST", f"/api/projects/{client.project_id}/memberships", json={"user_id": user["id"], "role": "viewer"})
    with TestClient(create_app()) as viewer:
        login = api(viewer, "POST", "/api/auth/login", json={"email": "viewer@test.local", "password": "viewer-password"})
        viewer.headers["X-CSRF-Token"] = login["csrf_token"]
        projects = api(viewer, "GET", "/api/projects")["items"]
        assert [row["id"] for row in projects] == [client.project_id]
        api(viewer, "GET", f"/api/projects/{other['id']}", expected=403)
        api(viewer, "POST", f"/api/projects/{client.project_id}/prompt-sets", expected=403,
            json={"name": "not allowed"})
        assert "budget" not in projects[0]["settings"]


def test_prompt_scaffold_dedup_review_freeze_and_copy(client):
    project_id = client.project_id
    prompt_set = api(client, "POST", f"/api/projects/{project_id}/prompt-sets", json={"name": "新问题集"})
    scaffold = api(client, "POST", f"/api/projects/{project_id}/prompt-sets/scaffold/preview",
                   json={"brand": "Acme", "category": "GEO", "competitors": ["Beta"]})["items"]
    assert len(scaffold) == 16
    assert len({item["canonical_intent_id"] for item in scaffold}) == 8
    result = api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/items",
                 json={"items": [*scaffold, scaffold[0]], "redact": True})
    assert result["count"] == 16
    assert len(result["duplicates"]) == 1
    api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/status", json={"status": "reviewing"})
    for item in result["items"]:
        api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/items/{item['id']}/review",
            json={"status": "reviewed", "eligibility": "eligible"})
    frozen = api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/status", json={"status": "frozen"})
    assert frozen["content_hash"]
    api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/items", expected=409,
        json={"items": scaffold[:1]})
    copied = api(client, "POST", f"/api/projects/{project_id}/prompt-sets/{prompt_set['id']}/copy")
    assert copied["status"] == "draft"
    assert len(copied["items"]) == 16


def test_demo_measurement_evidence_revision_and_report_workflow(client, official_demo):
    wave_id, run_id = official_demo
    project_id = client.project_id
    metrics = api(client, "GET", f"/api/projects/{project_id}/runs/{run_id}/metrics")
    assert metrics["quality"]["valid_samples"] == 8
    assert metrics["is_demo"] is True
    assert metrics["share_of_voice"]["value"] == 50
    answers = api(client, "GET", f"/api/projects/{project_id}/runs/{run_id}/answers")
    assert answers["total"] == 8
    detail = api(client, "GET", f"/api/projects/{project_id}/answers/{answers['items'][0]['id']}")
    observation = detail["observations"][0]
    evidence = next((part for part in detail["raw_text"].split("。") if observation["name"] in part), detail["raw_text"][:20])
    revision = api(client, "POST", f"/api/projects/{project_id}/answers/{detail['id']}/observations/{observation['id']}/revisions",
                   json={"entity_status": "confirmed", "mentioned": True, "depth": "described", "sentiment": "neutral",
                         "evidence": evidence, "reason": "自动化复核", "arbitrate": True})
    with connect() as conn:
        stored = one(conn, "SELECT * FROM observations WHERE id=?", (revision["id"],))
        assert stored["project_id"] == project_id
        assert stored["client_id"] == detail["client_id"]
        assert stored["revision"] == observation["revision"] + 1
        assert one(conn, "SELECT raw_text FROM answers WHERE id=?", (detail["id"],))["raw_text"] == detail["raw_text"]
    report = api(client, "POST", f"/api/projects/{project_id}/reports", json={"wave_ids": [wave_id]})
    for status in ("data_checked", "strategy_reviewed", "client_approved"):
        api(client, "POST", f"/api/projects/{project_id}/reports/{report['id']}/status", json={"status": status})
    client_html = client.get(f"/api/projects/{project_id}/reports/{report['id']}/export?variant=client&format=html").text
    internal_html = client.get(f"/api/projects/{project_id}/reports/{report['id']}/export?variant=internal&format=html").text
    assert "内部成本与质量" not in client_html
    assert "原始回答与判定" not in client_html
    assert "内部成本与质量" in internal_html
    assert "原始回答与判定" in internal_html
    assert "草稿 · 尚未完成客户审批" not in client_html  # approval chrome follows current workflow state
    detail = api(client, "GET", f"/api/projects/{project_id}/reports/{report['id']}")
    assert "覆盖率较低" not in detail["snapshot"]["diagnosis"]
    assert "覆盖率最低" not in detail["snapshot"]["diagnosis"]  # every measured dimension is 100%


def test_empty_report_is_explicitly_blocked_from_approval(client):
    wave = demo_wave(client)
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [wave["id"]]})
    detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")
    assert detail["snapshot"]["waves"][0]["run"] is None
    assert "无有效样本" in detail["snapshot"]["diagnosis"]
    assert detail["gates"]
    api(client, "POST", f"/api/projects/{client.project_id}/reports/{report['id']}/status", expected=409,
        json={"status": "data_checked"})


def test_cancel_run_finalizes_run_and_wave(client):
    wave = demo_wave(client, repeats=2)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/cancel")
    current = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}")
    assert current["status"] == "cancelled"
    assert current["progress"]["by_status"]["cancelled"] == 16
    with connect() as conn:
        assert one(conn, "SELECT status FROM waves WHERE id=?", (wave["id"],))["status"] == "data_ready_with_warnings"
