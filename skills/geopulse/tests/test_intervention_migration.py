from __future__ import annotations

import hashlib

from backend.app import migrations
from backend.app.db import connect, one


def test_populated_v5_migration_backfills_legacy_once_without_inventing_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "v5.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("GEOPULSE_ADMIN_PASSWORD", "migration-test-password")
    original_migrations = migrations.MIGRATIONS
    original_version = migrations.SCHEMA_VERSION
    monkeypatch.setattr(migrations, "MIGRATIONS", {number: path for number, path in original_migrations.items() if number <= 5})
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 5)
    migrations.initialize()
    raw_text = "v5 原始回答与 hash 必须在迁移后保持不变"
    raw_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects LIMIT 1")
        prompt_set = one(conn, "SELECT * FROM prompt_sets WHERE project_id=? LIMIT 1", (project["id"],))
        wave_id = conn.execute("""INSERT INTO waves(client_id,project_id,prompt_set_id,entity_version,label,protocol_json,stats_json,created_at)
            VALUES(?,?,?,'v1','v5 Wave','{}','{}','2026-11-01T00:00:00+00:00')""",
            (project["client_id"], project["id"], prompt_set["id"])).lastrowid
        wave = one(conn, "SELECT * FROM waves WHERE id=?", (wave_id,))
        prompt = one(conn, "SELECT * FROM prompt_items WHERE project_id=? LIMIT 1", (project["id"],))
        engine = one(conn, "SELECT * FROM engine_configs WHERE project_id=? LIMIT 1", (project["id"],))
        user = one(conn, "SELECT * FROM users LIMIT 1")
        run_id = conn.execute("""INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json)
            VALUES(?,?,?,1,'done','{}')""", (project["client_id"], project["id"], wave["id"])).lastrowid
        answer_id = conn.execute("""INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,
            raw_text,status,created_at,completed_at,raw_text_sha256,valid_sample)
            VALUES(?,?,?,?,?,1,?,'succeeded','2026-11-01T00:00:00+00:00','2026-11-01T00:00:01+00:00',?,1)""",
            (project["client_id"], project["id"], run_id, prompt["id"], engine["id"], raw_text, raw_hash)).lastrowid
        opportunity_id = conn.execute("""INSERT INTO opportunities(client_id,project_id,wave_id,prompt_item_id,evidence_json,gap_type,
            eligibility,status,created_at,updated_at) VALUES(?,?,?,?,?,'缺席','client_confirmed','actioned',
            '2026-11-01T00:00:00+00:00','2026-11-01T00:00:00+00:00')""",
            (project["client_id"], project["id"], wave["id"], prompt["id"], f'{{"answer_ids":[{answer_id}]}}')).lastrowid
        action_id = conn.execute("""INSERT INTO actions(client_id,project_id,opportunity_id,geo_step,title,target_url,artifact_version,
            published_at,published_url,status,target_wave_id,created_at,updated_at)
            VALUES(?,?,?,3,'v5 单发布','https://example.com/target','v1','2026-11-01T10:00:00+08:00',
            'https://example.com/published','published',?,'2026-11-01T00:00:00+00:00','2026-11-01T10:00:00+08:00')""",
            (project["client_id"], project["id"], opportunity_id, wave["id"])).lastrowid
        event_id = conn.execute("""INSERT INTO external_events(client_id,project_id,event_at,kind,description,source,created_by,created_at)
            VALUES(?,?,?,'内容发布','v5 发布事件','https://example.com/published',?,'2026-11-01T10:00:00+08:00')""",
            (project["client_id"], project["id"], "2026-11-01T10:00:00+08:00", user["id"])).lastrowid
        schedule_id = conn.execute("""INSERT INTO schedules(client_id,project_id,wave_id,scheduled_at,next_run_at,anchor_at,action_id,created_at,updated_at)
            VALUES(?,?,?,'2026-11-15T10:00:00+08:00','2026-11-15T10:00:00+08:00','2026-11-01T10:00:00+08:00',?,
            '2026-11-01T10:00:00+08:00','2026-11-01T10:00:00+08:00')""",
            (project["client_id"], project["id"], wave["id"], action_id)).lastrowid
        snapshot = '{"schema_version":1,"legacy_raw":"不得改写"}'
        report_id = conn.execute("""INSERT INTO reports(client_id,project_id,wave_ids_json,data_snapshot_json,data_snapshot_hash,version,
            client_html,internal_html,created_at,updated_at) VALUES(?,?,?,?,'legacy-report-hash',1,'<p>legacy</p>','<p>internal</p>',
            '2026-11-01T00:00:00+00:00','2026-11-01T00:00:00+00:00')""",
            (project["client_id"], project["id"], f'[{wave["id"]}]', snapshot)).lastrowid
        conn.commit()

    monkeypatch.setattr(migrations, "MIGRATIONS", original_migrations)
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", original_version)
    result = migrations.migrate()
    assert result["from"] == 5 and result["to"] == original_version and result["backup"]
    with connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        answer = one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,))
        assert answer["raw_text"] == raw_text and answer["raw_text_sha256"] == raw_hash
        report = one(conn, "SELECT * FROM reports WHERE id=?", (report_id,))
        assert report["data_snapshot_json"] == snapshot and report["data_snapshot_hash"] == "legacy-report-hash"
        assert report["client_html"] == "<p>legacy</p>"
        brief = one(conn, "SELECT * FROM content_briefs WHERE action_id=?", (action_id,))
        asset = one(conn, "SELECT * FROM action_assets WHERE action_id=?", (action_id,))
        publication = one(conn, "SELECT * FROM asset_publications WHERE action_id=?", (action_id,))
        assert brief["status"] == asset["status"] == "legacy" and brief["claims_json"] == "[]"
        assert publication["cost"] is None and publication["url"] == "https://example.com/published"
        event = one(conn, "SELECT * FROM external_events WHERE id=?", (event_id,))
        assert event["action_id"] == action_id and event["asset_id"] == asset["id"]
        assert event["publication_id"] == publication["id"]
        assert one(conn, "SELECT COUNT(*) AS count FROM external_events WHERE action_id=?", (action_id,))["count"] == 1
        round_row = one(conn, "SELECT * FROM action_remeasurement_rounds WHERE action_id=?", (action_id,))
        assert round_row["status"] == "legacy_unavailable" and round_row["baseline_run_id"] is None
        assert round_row["comparison_json"] == "{}"
        schedule = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))
        assert schedule["remeasurement_round_id"] == round_row["id"]
        assert schedule["anchor_at"] == "2026-11-01T10:00:00+08:00"
    assert migrations.migrate()["from"] == original_version
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM asset_publications WHERE action_id=?", (action_id,))["count"] == 1
        assert one(conn, "SELECT COUNT(*) AS count FROM action_remeasurement_rounds WHERE action_id=?", (action_id,))["count"] == 1


def test_populated_v6_to_v7_preserves_answers_observations_and_report_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "v6.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("GEOPULSE_ADMIN_PASSWORD", "migration-test-password")
    original_migrations = migrations.MIGRATIONS
    original_version = migrations.SCHEMA_VERSION
    monkeypatch.setattr(migrations, "MIGRATIONS", {number: path for number, path in original_migrations.items() if number <= 6})
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 6)
    migrations.initialize()
    raw = "v6 原文、判定与报告必须原样保留"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects LIMIT 1")
        prompt_set = one(conn, "SELECT * FROM prompt_sets WHERE project_id=? LIMIT 1", (project["id"],))
        prompt = one(conn, "SELECT * FROM prompt_items WHERE project_id=? LIMIT 1", (project["id"],))
        engine = one(conn, "SELECT * FROM engine_configs WHERE project_id=? LIMIT 1", (project["id"],))
        entity = one(conn, "SELECT * FROM brand_entities WHERE project_id=? AND role='primary'", (project["id"],))
        wave_id = conn.execute("""INSERT INTO waves(client_id,project_id,prompt_set_id,entity_version,label,protocol_json,stats_json,created_at)
            VALUES(?,?,?,'v1','v6 Wave','{}','{}','2026-11-01T00:00:00+00:00')""",
            (project["client_id"], project["id"], prompt_set["id"])).lastrowid
        run_id = conn.execute("INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json) VALUES(?,?,?,1,'done','{}')",
                              (project["client_id"], project["id"], wave_id)).lastrowid
        answer_id = conn.execute("""INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,
            raw_text,status,created_at,completed_at,raw_text_sha256,valid_sample)
            VALUES(?,?,?,?,?,1,?,'succeeded','2026-11-01T00:00:00+00:00','2026-11-01T00:00:01+00:00',?,1)""",
            (project["client_id"], project["id"], run_id, prompt["id"], engine["id"], raw, digest)).lastrowid
        observation_id = conn.execute("""INSERT INTO observations(client_id,project_id,answer_id,brand_entity_id,revision,
            entity_status,mentioned,depth,sentiment,evidence,judge_status,created_at)
            VALUES(?,?,?,?,1,'confirmed',1,'recommended','positive',?,'human-arbitrated','2026-11-01T00:00:02+00:00')""",
            (project["client_id"], project["id"], answer_id, entity["id"], raw)).lastrowid
        report_snapshot = '{"schema_version":2,"legacy":"不变"}'
        report_id = conn.execute("""INSERT INTO reports(client_id,project_id,wave_ids_json,data_snapshot_json,data_snapshot_hash,
            version,client_html,internal_html,created_at,updated_at) VALUES(?,?,?,?,'v6-report-hash',1,'<p>v6</p>','<p>v6 internal</p>',
            '2026-11-01T00:00:00+00:00','2026-11-01T00:00:00+00:00')""",
            (project["client_id"], project["id"], f'[{wave_id}]', report_snapshot)).lastrowid
        conn.commit()
    monkeypatch.setattr(migrations, "MIGRATIONS", original_migrations)
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", original_version)
    result = migrations.migrate()
    assert result["from"] == 6 and result["to"] == 7 and result["backup"]
    with connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert one(conn, "SELECT raw_text,raw_text_sha256 FROM answers WHERE id=?", (answer_id,)) == {"raw_text": raw, "raw_text_sha256": digest}
        assert one(conn, "SELECT id,revision,evidence FROM observations WHERE id=?", (observation_id,)) == {
            "id": observation_id, "revision": 1, "evidence": raw}
        report = one(conn, "SELECT * FROM reports WHERE id=?", (report_id,))
        assert report["data_snapshot_json"] == report_snapshot and report["data_snapshot_hash"] == "v6-report-hash"
        assert report["client_html"] == "<p>v6</p>"
        assert "judge_batch_id" in {row["name"] for row in conn.execute("PRAGMA table_info(call_attempts)")}
        assert one(conn, "SELECT COUNT(*) AS count FROM judge_batches")["count"] == 0
    assert migrations.migrate()["from"] == 7
