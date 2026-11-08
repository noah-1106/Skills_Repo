from __future__ import annotations

from backend.app import migrations
from backend.app.db import connect, dumps, one


def test_populated_v4_migration_preserves_evidence_and_citation_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "v4.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("GEOPULSE_BROWSER_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 4)
    migrations.initialize()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects LIMIT 1")
        engine = one(conn, "SELECT * FROM engine_configs LIMIT 1")
        prompt_set = one(conn, "SELECT * FROM prompt_sets LIMIT 1")
        prompt = one(conn, "SELECT * FROM prompt_items LIMIT 1")
        entity = one(conn, "SELECT * FROM brand_entities WHERE role='primary' LIMIT 1")
        now = "2026-01-01T00:00:00+00:00"
        protocol = {"prompt_set_id": prompt_set["id"], "prompt_item_ids": [prompt["id"]],
                    "entity_ids": [entity["id"]], "engine_ids": [engine["id"]], "repeats": 1,
                    "measurement_target": "consumer_web", "collection_protocol": {"protocol_version": "manual-web-v1"}}
        wave_id = conn.execute("INSERT INTO waves(client_id,project_id,prompt_set_id,entity_version,label,protocol_json,stats_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                               (project["client_id"], project["id"], prompt_set["id"], "entities", "v4 数据",
                                dumps(protocol), "{}", now)).lastrowid
        run_id = conn.execute("INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json) VALUES(?,?,?,1,'done',?)",
                              (project["client_id"], project["id"], wave_id, dumps({"protocol": protocol}))).lastrowid
        answer_id = conn.execute("""INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,
                                    raw_text,raw_text_sha256,status,created_at) VALUES(?,?,?,?,?,1,'旧原文','hash','succeeded',?)""",
                                 (project["client_id"], project["id"], run_id, prompt["id"], engine["id"], now)).lastrowid
        collection_id = conn.execute("""INSERT INTO web_collections(client_id,project_id,answer_id,status,draft_text,created_at,updated_at)
                                        VALUES(?,?,?,'completed','旧原文',?,?)""",
                                     (project["client_id"], project["id"], answer_id, now, now)).lastrowid
        citation_id = conn.execute("""INSERT INTO citations(client_id,project_id,answer_id,raw_url,final_url,title,domain,
                                      source_type,content_hash,returned_at,origin)
                                      VALUES(?,?,?,'https://example.test/a','','旧引用','example.test','其他','hash',?,'manual_page')""",
                                   (project["client_id"], project["id"], answer_id, now)).lastrowid
        attachment_id = conn.execute("""INSERT INTO answer_attachments(client_id,project_id,answer_id,kind,filename,media_type,
                                        byte_size,sha256,content,created_at) VALUES(?,?,?,'raw_text','old.txt','text/plain',4,'abc',?,?)""",
                                     (project["client_id"], project["id"], answer_id, b"old\x00", now)).lastrowid
        conn.commit()
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 5)
    result = migrations.migrate()
    assert result["from"] == 4 and result["to"] == 5 and result["backup"]
    with connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert one(conn, "SELECT raw_text FROM answers WHERE id=?", (answer_id,))["raw_text"] == "旧原文"
        collection = one(conn, "SELECT * FROM web_collections WHERE id=?", (collection_id,))
        assert collection["collection_method"] == "manual" and collection["browser_attempt_count"] == 0
        citation = one(conn, "SELECT * FROM citations WHERE id=?", (citation_id,))
        assert citation["origin"] == "manual_page" and citation["title"] == "旧引用"
        assert one(conn, "SELECT content FROM answer_attachments WHERE id=?", (attachment_id,))["content"] == b"old\x00"
        assert one(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='browser_sessions'")
