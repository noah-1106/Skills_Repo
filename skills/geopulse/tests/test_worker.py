from backend.app.db import connect, one
from backend.app.providers.base import ProviderError, ProviderResult
from backend.app.services.measurement import Worker, process_answer
from conftest import api, demo_wave


def test_restart_recovers_raw_answer_without_repeating_provider(client, monkeypatch):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    with connect() as conn:
        first = one(conn, "SELECT id FROM answers WHERE run_id=? ORDER BY id LIMIT 1", (run["id"],))
        conn.execute("UPDATE answers SET status='cancelled' WHERE run_id=? AND id!=?", (run["id"], first["id"]))
        conn.execute("UPDATE answers SET raw_text='保留的原始 GeoPulse 回答。',status='running' WHERE id=?", (first["id"],))
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
        conn.commit()
    Worker(1).recover()
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (first["id"],))["status"] == "judging"
    process_answer(first["id"])
    with connect() as conn:
        answer = one(conn, "SELECT * FROM answers WHERE id=?", (first["id"],))
        assert answer["status"] == "succeeded"
        assert answer["raw_text"] == "保留的原始 GeoPulse 回答。"
        assert one(conn, "SELECT status FROM runs WHERE id=?", (run["id"],))["status"] == "partial"


def test_only_safe_retryable_failures_are_requeued(client, monkeypatch):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    with connect() as conn:
        first = one(conn, "SELECT id FROM answers WHERE run_id=? ORDER BY id LIMIT 1", (run["id"],))
        conn.execute("UPDATE answers SET status='cancelled' WHERE run_id=? AND id!=?", (run["id"], first["id"]))
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
        conn.commit()
    calls = []

    class FlakyProvider:
        def ask(self, prompt, protocol):
            calls.append(prompt)
            if len(calls) == 1:
                raise ProviderError("temporary", "http_500", retryable=True)
            return ProviderResult(text="GeoPulse 值得考虑。", model="fake", usage={}, operations=[
                {"kind": "answer", "status": "succeeded", "usage": {}, "model": "fake"}])

    monkeypatch.setattr("backend.app.services.measurement.build_provider", lambda *args: FlakyProvider())
    monkeypatch.setattr("backend.app.services.measurement.time.sleep", lambda seconds: None)
    process_answer(first["id"])
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (first["id"],))["status"] == "queued"
    process_answer(first["id"])
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (first["id"],))["status"] == "succeeded"
    assert len(calls) == 2


def test_outcome_unknown_timeout_requires_manual_retry(client, monkeypatch):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    with connect() as conn:
        first = one(conn, "SELECT id FROM answers WHERE run_id=? ORDER BY id LIMIT 1", (run["id"],))
        conn.execute("UPDATE answers SET status='cancelled' WHERE run_id=? AND id!=?", (run["id"], first["id"]))
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
        conn.commit()

    class TimeoutProvider:
        def ask(self, prompt, protocol):
            raise ProviderError("unknown", "timeout", retryable=True, outcome_unknown=True)

    monkeypatch.setattr("backend.app.services.measurement.build_provider", lambda *args: TimeoutProvider())
    process_answer(first["id"])
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (first["id"],))["status"] == "failed"
