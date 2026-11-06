from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app.db import connect, one
from backend.app.main import create_app
from backend.app.migrations import initialize
from backend.app.services.measurement import Worker

ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "no-legacy-config.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("GEOPULSE_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("GEOPULSE_DISABLE_WORKER", "1")
    monkeypatch.setenv("GEOPULSE_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("GEOPULSE_ADMIN_EMAIL", "admin@test.local")
    initialize()
    with TestClient(create_app()) as test_client:
        response = test_client.post("/api/auth/login", json={"email": "admin@test.local", "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        test_client.project_id = test_client.get("/api/projects").json()["items"][0]["id"]
        yield test_client


def api(client, method: str, path: str, expected: int = 200, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def demo_wave(client, repeats: int = 1):
    project_id = client.project_id
    prompt_set_id = client.get(f"/api/projects/{project_id}/prompt-sets").json()["items"][0]["id"]
    engine_id = client.get(f"/api/projects/{project_id}/engines").json()["items"][0]["id"]
    return api(client, "POST", f"/api/projects/{project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "自动化测试 Wave", "engine_ids": [engine_id],
        "repeats": repeats, "use_judge": True,
    })


def execute_run(client, run_id: int, timeout: float = 20):
    worker = Worker(2)
    worker.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with connect() as conn:
                status = one(conn, "SELECT status FROM runs WHERE id=?", (run_id,))["status"]
            if status in ("done", "partial", "failed", "cancelled"):
                return status
            time.sleep(0.05)
        raise AssertionError(f"run {run_id} did not finish")
    finally:
        worker.stop()


@pytest.fixture
def official_demo(client):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    return wave["id"], run["id"]
