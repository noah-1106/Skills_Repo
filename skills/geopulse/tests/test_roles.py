from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from conftest import api


@pytest.mark.parametrize("role", ["admin", "analyst", "reviewer", "viewer"])
def test_project_role_api_contracts(client, official_demo, role):
    _, run_id = official_demo
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "角色脱敏引擎", "vendor": "Test", "kind": "openai_compat", "model": "test",
        "base_url": "https://example.test/v1", "api_key": "role-test-secret", "mode": "memory",
        "cost_rule": {"input_per_million": 123, "output_per_million": 456},
    })
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [api(client, "GET", f"/api/projects/{client.project_id}/waves")["items"][0]["id"]]})
    answer_id = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/answers")["items"][0]["id"]
    user = api(client, "POST", "/api/users", json={"email": f"project-{role}@test.local", "password": "role-test-password"})
    api(client, "POST", f"/api/projects/{client.project_id}/memberships", json={"user_id": user["id"], "role": role})
    with TestClient(create_app()) as scoped:
        login = api(scoped, "POST", "/api/auth/login", json={"email": f"project-{role}@test.local", "password": "role-test-password"})
        scoped.headers["X-CSRF-Token"] = login["csrf_token"]
        assert login["user"]["global_role"] != "admin"
        api(scoped, "GET", "/api/users", expected=403)
        api(scoped, "GET", f"/api/projects/{client.project_id}/memberships", expected=200 if role == "admin" else 403)
        engines = api(scoped, "GET", f"/api/projects/{client.project_id}/engines")["items"]
        configured = next(item for item in engines if item["id"] == engine["id"])
        assert "secret_ref" not in configured
        assert ("cost_rule" in configured) == (role == "admin")
        waves = api(scoped, "GET", f"/api/projects/{client.project_id}/waves")["items"]
        assert ("estimated_cost" in waves[0]["estimate"]) == (role in ("admin", "analyst"))
        assert ("budget" in waves[0]["stats"]) == (role in ("admin", "analyst"))
        assert ("estimated_cost" in waves[0]["readiness"]["estimate"]) == (role in ("admin", "analyst"))
        handoff = api(scoped, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/handoff")
        assert "cost" not in str(handoff).lower() and "secret_ref" not in str(handoff)
        run = api(scoped, "GET", f"/api/projects/{client.project_id}/runs/{run_id}")
        assert "secret_ref" not in str(run) and "cost_rule" not in str(run)
        answer = api(scoped, "GET", f"/api/projects/{client.project_id}/answers/{answer_id}")
        assert bool(answer["raw_text"]) == (role in ("admin", "analyst"))
        assert all(("cost" in attempt) == (role in ("admin", "analyst")) for attempt in answer["call_attempts"])
        report_detail = api(scoped, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")
        assert ("costs" in report_detail["snapshot"]) == (role in ("admin", "analyst"))
        assert ("internal_samples" in report_detail["snapshot"]) == (role in ("admin", "analyst"))
        assert all("budget" not in wave["stats"] for wave in report_detail["snapshot"]["waves"]) == (role in ("reviewer", "viewer"))
        assert all("system_prompt" not in str(wave) for wave in report_detail["snapshot"]["waves"]) == (role in ("reviewer", "viewer"))
        api(scoped, "GET", f"/api/projects/{client.project_id}/operations", expected=200 if role in ("admin", "analyst") else 403)
        api(scoped, "GET", f"/api/projects/{client.project_id}/export", expected=200 if role == "admin" else 403)
        api(scoped, "GET", f"/api/projects/{client.project_id}/retention/preview", expected=200 if role in ("admin", "analyst") else 403)
        api(scoped, "POST", f"/api/projects/{client.project_id}/retention/execute", json={"confirm": True},
            expected=200 if role == "admin" else 403)
