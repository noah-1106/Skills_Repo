from __future__ import annotations

import time
import hashlib

from fastapi.testclient import TestClient

from backend.app.db import connect, loads, one
from backend.app.main import create_app
from conftest import api, execute_run


def disabled_demo_run(client, repeats=2):
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    engine = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"][0]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "Judge 漏配匿名回归", "engine_ids": [engine["id"]],
        "repeats": repeats, "use_judge": False,
    })
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    return engine, wave, run


def wait_batch(client, batch_id: int):
    deadline = time.monotonic() + 20
    from backend.app.services.measurement import Worker
    worker = Worker(2)
    worker.start()
    try:
        while time.monotonic() < deadline:
            with connect() as conn:
                status = one(conn, "SELECT status FROM judge_batches WHERE id=?", (batch_id,))["status"]
            if status not in ("queued", "running"):
                return status
            time.sleep(0.05)
        raise AssertionError(f"judge batch {batch_id} did not finish")
    finally:
        worker.stop()


def test_sixteen_disabled_answers_append_judge_revisions_without_recollecting(client):
    engine, _, run = disabled_demo_run(client)
    with connect() as conn:
        before_answers = {row["id"]: (row["raw_text"], row["raw_text_sha256"], row["usage_json"])
                          for row in conn.execute("SELECT * FROM answers WHERE run_id=?", (run["id"],))}
        assert len(before_answers) == 16
        before_citations = one(conn, "SELECT COUNT(*) AS count FROM citations WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)",
                               (run["id"],))["count"]
        before_revisions = one(conn, "SELECT MAX(revision) AS value FROM observations WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)",
                               (run["id"],))["value"]
        assert before_revisions == 1
        original_run = one(conn, "SELECT * FROM runs WHERE id=?", (run["id"],))

    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    assert batch["scope"] == "all_eligible" and batch["progress"]["total"] == 16
    assert batch["estimate"]["answer_calls"] == batch["estimate"]["search_calls"] == 0
    assert batch["estimate"]["judge_calls"] == 16
    assert "secret_ref" not in str(batch) and "cost_rule" not in str(batch)
    assert wait_batch(client, batch["id"]) == "done"

    with connect() as conn:
        after_answers = {row["id"]: (row["raw_text"], row["raw_text_sha256"], row["usage_json"])
                         for row in conn.execute("SELECT * FROM answers WHERE run_id=?", (run["id"],))}
        assert after_answers == before_answers
        current_run = one(conn, "SELECT * FROM runs WHERE id=?", (run["id"],))
        assert current_run == original_run
        attempts = conn.execute("SELECT * FROM call_attempts WHERE judge_batch_id=?", (batch["id"],)).fetchall()
        assert len(attempts) == 16
        assert {row["kind"] for row in attempts} == {"judge"}
        assert {row["status"] for row in attempts} == {"succeeded"}
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=? AND kind IN ('answer','search')",
                   (batch["id"],))["count"] == 0
        assert one(conn, "SELECT MIN(revision) AS value FROM observations WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)",
                   (run["id"],))["value"] == 1
        assert one(conn, "SELECT MAX(revision) AS value FROM observations WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)",
                   (run["id"],))["value"] == 2
        assert one(conn, "SELECT COUNT(*) AS count FROM observations o JOIN answers a ON a.id=o.answer_id WHERE a.run_id=? AND o.revision=2",
                   (run["id"],))["count"] == 48
        for row in conn.execute("SELECT answer_id,judge_meta_json FROM observations WHERE revision=2"):
            meta = loads(row["judge_meta_json"])
            assert meta["judge_batch_id"] == batch["id"]
            assert meta["answer_raw_sha256"] == before_answers[row["answer_id"]][1]
        assert one(conn, "SELECT COUNT(*) AS count FROM citations WHERE answer_id IN (SELECT id FROM answers WHERE run_id=?)",
                   (run["id"],))["count"] == before_citations
    exported = api(client, "GET", f"/api/projects/{client.project_id}/export")
    assert exported["tables"]["judge_batches"][0]["id"] == batch["id"]
    assert len(exported["tables"]["judge_batch_items"]) == 16
    assert loads(exported["tables"]["judge_batches"][0]["judge_engine_snapshot_json"])["secret_ref"] == ""


def test_selected_batch_is_idempotent_at_worker_and_preserves_old_revision(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    answer_id = next(iter(api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}/answers")["items"]))["id"]
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"], "answer_ids": [answer_id]})
    assert wait_batch(client, batch["id"]) == "done"
    with connect() as conn:
        item_id = one(conn, "SELECT id FROM judge_batch_items WHERE batch_id=?", (batch["id"],))["id"]
        calls = one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"]
        observations = one(conn, "SELECT COUNT(*) AS count FROM observations WHERE answer_id=?", (answer_id,))["count"]
    from backend.app.services.judge_batches import process_judge_item
    process_judge_item(item_id)
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"] == calls
        assert one(conn, "SELECT COUNT(*) AS count FROM observations WHERE answer_id=?", (answer_id,))["count"] == observations
        assert one(conn, "SELECT MIN(revision) AS value FROM observations WHERE answer_id=?", (answer_id,))["value"] == 1


def test_raw_purge_and_cross_run_answers_cannot_be_rejudged(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    answers = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}/answers")["items"]
    purged_id = answers[0]["id"]
    with connect() as conn:
        conn.execute("UPDATE answers SET raw_text=NULL,content_retained=0,content_purged_at='2026-11-10T00:00:00+00:00' WHERE id=?", (purged_id,))
        conn.commit()
    error = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"], "answer_ids": [purged_id]}, expected=409)
    assert error["detail"]["excluded"] == [{"answer_id": purged_id, "reason": "raw_purged"}]
    mismatch_id = answers[1]["id"]
    with connect() as conn:
        conn.execute("UPDATE answers SET raw_text_sha256='not-the-raw-hash' WHERE id=?", (mismatch_id,))
        conn.commit()
    error = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"], "answer_ids": [mismatch_id]}, expected=409)
    assert error["detail"]["excluded"] == [{"answer_id": mismatch_id, "reason": "raw_hash_mismatch"}]
    _, _, other_run = disabled_demo_run(client, repeats=1)
    other_answer = api(client, "GET", f"/api/projects/{client.project_id}/runs/{other_run['id']}/answers")["items"][0]
    api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
        json={"judge_engine_id": engine["id"], "answer_ids": [other_answer["id"]]}, expected=404)


def test_unsubmitted_consumer_web_evidence_cannot_be_rejudged(client):
    from test_manual_web import manual_run

    _, judge, _, run, answer = manual_run(client)
    raw = "仅用于补判资格校验的匿名原文。"
    with connect() as conn:
        conn.execute("UPDATE runs SET status='done' WHERE id=?", (run["id"],))
        conn.execute("""UPDATE answers SET raw_text=?,raw_text_sha256=?,status='succeeded',valid_sample=1,
                        content_retained=1 WHERE id=?""", (raw, hashlib.sha256(raw.encode()).hexdigest(), answer["id"]))
        conn.commit()
    error = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": judge["id"], "answer_ids": [answer["id"]]}, expected=409)
    assert error["detail"]["excluded"] == [{"answer_id": answer["id"], "reason": "collection_evidence_incomplete"}]
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM judge_batches")["count"] == 0
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts")["count"] == 0


def test_real_batch_requires_separate_confirmation_and_releases_own_budget(client):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "真实补判 Mock 配置", "vendor": "Test", "kind": "openai_compat", "model": "configured-chat",
        "base_url": "https://example.test/v1", "api_key": "test-only-secret", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 10, "output_per_million": 20,
                      "estimated_output_tokens": 1800},
    })
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "真实补判确认", "engine_ids": [engine["id"]], "repeats": 1, "use_judge": False,
    })
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
              json={"confirm_judge_disabled": True})["run"]
    raw = "这是一条匿名化有效原文。"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with connect() as conn:
        conn.execute("""UPDATE answers SET raw_text=?,raw_text_sha256=?,status='succeeded',valid_sample=1,
                        content_retained=1,model='returned-flash',completed_at='2026-11-10T00:00:00+00:00' WHERE run_id=?""",
                     (raw, digest, run["id"]))
        conn.execute("UPDATE runs SET status='done',finished_at='2026-11-10T00:00:01+00:00' WHERE id=?", (run["id"],))
        conn.commit()
    error = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]}, expected=409)
    assert error["detail"]["code"] == "judge_batch_confirmation_required"
    assert error["detail"]["estimate"]["answer_calls"] == error["detail"]["estimate"]["search_calls"] == 0
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM judge_batches")["count"] == 0
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE kind='judge'")["count"] == 0
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"budget": {
        "enabled": True, "hard_limit": True, "amount": 100, "currency": "CNY"}}})
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"], "confirm": True})
    with connect() as conn:
        reservation = one(conn, "SELECT * FROM budget_reservations WHERE operation_id=?", (f"judge-batch:{batch['id']}",))
        assert reservation["status"] == "active" and reservation["run_id"] is None
    api(client, "POST", f"/api/projects/{client.project_id}/judge-batches/{batch['id']}/cancel", json={})
    with connect() as conn:
        assert one(conn, "SELECT status FROM budget_reservations WHERE id=?", (reservation["id"],))["status"] == "released"


def test_retry_requeues_only_known_failed_items(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    with connect() as conn:
        item = one(conn, "SELECT * FROM judge_batch_items WHERE batch_id=? ORDER BY id LIMIT 1", (batch["id"],))
        conn.execute("UPDATE judge_batch_items SET status='failed',error_type='mock_definite_failure',outcome_unknown=0 WHERE id=?", (item["id"],))
        conn.execute("UPDATE judge_batch_items SET status='cancelled' WHERE batch_id=? AND id!=?", (batch["id"], item["id"]))
        conn.execute("UPDATE judge_batches SET status='failed' WHERE id=?", (batch["id"],))
        conn.commit()
    retried = api(client, "POST", f"/api/projects/{client.project_id}/judge-batches/{batch['id']}/retry", json={})
    assert retried["progress"] == {"cancelled": 7, "queued": 1, "total": 8}
    assert wait_batch(client, batch["id"]) == "partial"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"] == 1
        assert one(conn, "SELECT COUNT(*) AS count FROM observations WHERE answer_id=? AND revision=2", (item["answer_id"],))["count"] == 3
        assert one(conn, "SELECT COUNT(*) AS count FROM observations o JOIN judge_batch_items i ON i.answer_id=o.answer_id "
                         "WHERE i.batch_id=? AND i.status='cancelled' AND o.revision=2", (batch["id"],))["count"] == 0


def test_recovery_does_not_replay_interrupted_unknown_item(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    with connect() as conn:
        item = one(conn, "SELECT * FROM judge_batch_items WHERE batch_id=? ORDER BY id LIMIT 1", (batch["id"],))
        conn.execute("UPDATE judge_batch_items SET status='running',attempt_no=1 WHERE id=?", (item["id"],))
        conn.execute("UPDATE judge_batches SET status='running' WHERE id=?", (batch["id"],))
        conn.commit()
    from backend.app.services.judge_batches import recover_judge_batches
    recover_judge_batches()
    with connect() as conn:
        interrupted = one(conn, "SELECT * FROM judge_batch_items WHERE id=?", (item["id"],))
        assert interrupted["status"] == "failed" and interrupted["outcome_unknown"] == 1
        assert interrupted["error_type"] == "interrupted_unknown"
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"] == 0
    assert wait_batch(client, batch["id"]) == "partial"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"] == 7
        assert one(conn, "SELECT COUNT(*) AS count FROM observations WHERE answer_id=? AND revision=2", (item["answer_id"],))["count"] == 0
    api(client, "POST", f"/api/projects/{client.project_id}/judge-batches/{batch['id']}/retry", json={}, expected=409)


def test_batch_routes_enforce_project_and_role_boundaries(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    other = api(client, "POST", "/api/projects", json={"client_name": "其他客户", "name": "隔离项目"})
    other_engine = api(client, "GET", f"/api/projects/{other['id']}/engines")["items"][0]
    api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
        json={"judge_engine_id": other_engine["id"]}, expected=409)
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    user = api(client, "POST", "/api/users", json={"email": "viewer@test.local", "password": "viewer-test-password"})
    api(client, "POST", f"/api/projects/{client.project_id}/memberships", json={"user_id": user["id"], "role": "viewer"})
    with TestClient(create_app()) as viewer:
        login = viewer.post("/api/auth/login", json={"email": "viewer@test.local", "password": "viewer-test-password"})
        assert login.status_code == 200
        viewer.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        batches = viewer.get(f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches")
        assert batches.status_code == 200
        detail = viewer.get(f"/api/projects/{client.project_id}/judge-batches/{batch['id']}")
        assert detail.status_code == 200
        assert "estimated_cost" not in detail.json()["estimate"]
        assert "budget_confirmation_reason" not in detail.json()
        assert "secret_ref" not in str(detail.json())
        forbidden = viewer.post(f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                                json={"judge_engine_id": engine["id"]})
        assert forbidden.status_code == 403
