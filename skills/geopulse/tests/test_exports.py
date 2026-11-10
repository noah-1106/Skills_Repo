from __future__ import annotations

import hashlib
import json

import pytest

from backend.app.db import connect, dumps, one
from backend.app.migrations import SCHEMA_VERSION, backup, restore
from backend.app.services.exports import TABLES, build_project_export
from conftest import api


def test_api_and_cli_export_service_share_contract_and_recursive_secret_scrub(client):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "导出引擎", "vendor": "Test", "kind": "openai_compat", "model": "test",
        "base_url": "https://example.test/v1", "api_key": "never-export-this-key", "mode": "memory",
        "cost_rule": {"input_per_million": 1, "output_per_million": 2},
    })
    wave_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": wave_id, "label": "导出快照", "engine_ids": [engine["id"]], "use_judge": False})
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
        json={"confirm_judge_disabled": True})
    via_api = api(client, "GET", f"/api/projects/{client.project_id}/export")
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects WHERE id=?", (client.project_id,))
        via_cli = build_project_export(conn, project)
    assert tuple(via_api["tables"]) == tuple(via_cli["tables"]) == TABLES
    assert via_api["schema_version"] == via_cli["schema_version"] == SCHEMA_VERSION
    for table in TABLES:
        if table != "audit_events":
            assert via_api["tables"][table] == via_cli["tables"][table]
    assert "never-export-this-key" not in str(via_api)
    references = []
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "secret_ref":
                    references.append(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(via_api["tables"])
    assert references and set(references) == {""}
    assert all(not row["secret_ref"] for row in via_api["tables"]["engine_configs"])
    for run in via_api["tables"]["runs"]:
        assert "sec_" not in run["snapshot_json"]
    checksum = via_api["sha256"]
    unsigned = {key: value for key, value in via_api.items() if key != "sha256"}
    assert hashlib.sha256(dumps(unsigned).encode()).hexdigest() == checksum
    via_api["tables"]["projects"][0]["name"] = "tampered"
    assert hashlib.sha256(dumps({key: value for key, value in via_api.items() if key != "sha256"}).encode()).hexdigest() != checksum


def test_restore_rejects_tampering_without_touching_destination(client, tmp_path):
    backup_path = tmp_path / "backup.db"
    manifest = backup(backup_path)
    destination = tmp_path / "destination.db"
    destination.write_bytes(b"existing-database-must-survive")
    backup_path.write_bytes(b"not a sqlite database")
    manifest_path = backup_path.with_suffix(".manifest.json")
    manifest["sha256"] = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Exception):
        restore(backup_path, destination)
    assert destination.read_bytes() == b"existing-database-must-survive"
