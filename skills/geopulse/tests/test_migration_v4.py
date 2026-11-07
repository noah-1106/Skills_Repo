from __future__ import annotations

from backend.app import migrations
from backend.app.db import connect, dumps, one


def test_populated_v3_migration_preserves_measurement_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "v3.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 3)
    migrations.initialize()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects LIMIT 1")
        engine = one(conn, "SELECT * FROM engine_configs LIMIT 1")
        prompt_set = one(conn, "SELECT * FROM prompt_sets LIMIT 1")
        prompt = one(conn, "SELECT * FROM prompt_items LIMIT 1")
        entity = one(conn, "SELECT * FROM brand_entities WHERE role='primary' LIMIT 1")
        now = "2026-01-01T00:00:00+00:00"
        protocol = {"prompt_set_id": prompt_set["id"], "prompt_item_ids": [prompt["id"]],
                    "entity_ids": [entity["id"]], "engine_ids": [engine["id"]], "repeats": 1}
        wave_id = conn.execute("INSERT INTO waves(client_id,project_id,prompt_set_id,entity_version,label,protocol_json,stats_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                               (project["client_id"], project["id"], prompt_set["id"], "entities", "v3 数据",
                                dumps(protocol), "{}", now)).lastrowid
        run_id = conn.execute("INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json) VALUES(?,?,?,1,'done',?)",
                              (project["client_id"], project["id"], wave_id, dumps({"protocol": protocol}))).lastrowid
        answer_id = conn.execute("INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,raw_text,status,created_at) VALUES(?,?,?,?,?,1,'旧原文','succeeded',?)",
                                 (project["client_id"], project["id"], run_id, prompt["id"], engine["id"], now)).lastrowid
        attempt_id = conn.execute("INSERT INTO call_attempts(answer_id,client_id,project_id,run_id,engine_config_id,kind,operation,attempt_no,status,usage_json,cost,currency,cost_rule_json,created_at) VALUES(?,?,?,?,?,'answer','answer',1,'succeeded','{}',0,'CNY','{}',?)",
                                  (answer_id, project["client_id"], project["id"], run_id, engine["id"], now)).lastrowid
        attachment_id = conn.execute("INSERT INTO answer_attachments(client_id,project_id,answer_id,kind,filename,media_type,byte_size,sha256,content,created_at) VALUES(?,?,?,'raw_text','old.txt','text/plain',4,'abc',?,?)",
                                     (project["client_id"], project["id"], answer_id, b"old\x00", now)).lastrowid
        report_id = conn.execute("INSERT INTO reports(client_id,project_id,wave_ids_json,data_snapshot_json,data_snapshot_hash,version,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)",
                                 (project["client_id"], project["id"], dumps([wave_id]), dumps({"old": True}), "hash", now, now)).lastrowid
        conn.commit()
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 4)
    result = migrations.migrate()
    assert result["from"] == 3 and result["to"] == 4 and result["backup"]
    with connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        migrated = one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,))
        assert migrated["engine_config_id"] == engine["id"] and migrated["raw_text"] == "旧原文"
        attempt = one(conn, "SELECT * FROM call_attempts WHERE id=?", (attempt_id,))
        assert attempt["request_params_json"] == "{}" and attempt["response_meta_json"] == "{}"
        attachment = one(conn, "SELECT * FROM answer_attachments WHERE id=?", (attachment_id,))
        assert attachment["content"] == b"old\x00"
        assert one(conn, "SELECT data_snapshot_json FROM reports WHERE id=?", (report_id,))["data_snapshot_json"] == '{"old":true}'
        migrated_engine = one(conn, "SELECT * FROM engine_configs WHERE id=?", (engine["id"],))
        assert migrated_engine["capabilities_json"] == "{}"
        assert one(conn, "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_engines_project'")
