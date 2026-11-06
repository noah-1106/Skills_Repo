#!/usr/bin/env python3
"""2700-call persistence/read-path stress acceptance using only DemoProvider."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "test-results" / "stress-simulated.json")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="geopulse-stress-") as temporary:
        temp = Path(temporary)
        os.environ.update({
            "GEOPULSE_DB": str(temp / "stress.db"), "GEOPULSE_SECRETS": str(temp / "secrets.json"),
            "GEOPULSE_CONFIG": str(temp / "missing-config.json"), "GEOPULSE_BACKUP_DIR": str(temp / "backups"),
            "GEOPULSE_EXPORT_DIR": str(temp / "exports"), "GEOPULSE_DISABLE_WORKER": "1",
            "GEOPULSE_ADMIN_EMAIL": "admin@stress.local", "GEOPULSE_ADMIN_PASSWORD": "stress-admin-password",
        })
        from fastapi.testclient import TestClient
        from backend.app.db import all_rows, connect, one, utc_now
        from backend.app.main import create_app
        from backend.app.migrations import initialize
        from backend.app.providers.demo import DemoProvider
        from backend.app.services import measurement
        from backend.app.services.measurement import Worker, create_run, create_wave
        from backend.app.services.prompts import add_items, create_set, freeze_set

        initialize()
        with connect() as conn:
            project = one(conn, "SELECT * FROM projects ORDER BY id LIMIT 1")
            actor = one(conn, "SELECT id FROM users WHERE global_role='admin' ORDER BY id LIMIT 1")["id"]
            prompt_set = create_set(conn, project, actor, "2700 调用压力问题集")
            items = [{
                "text": f"压力意图 {intent:03d} 的表述 {variant}：哪些 GEO 监测工具适合场景 {intent}-{variant}？",
                "canonical_intent_id": f"stress-intent-{intent:03d}",
                "dimension": ("brand", "scene", "compare", "choice")[(intent * 3 + variant) % 4],
                "query_type": "discovery", "priority": 4, "eligibility": "eligible", "source": "离线压力夹具",
            } for intent in range(100) for variant in range(3)]
            added = add_items(conn, prompt_set, actor, items)
            assert len(added["items"]) == 300
            conn.execute("UPDATE prompt_sets SET status='reviewing' WHERE id=?", (prompt_set["id"],))
            conn.execute("UPDATE prompt_items SET status='reviewed' WHERE prompt_set_id=?", (prompt_set["id"],))
            prompt_set = one(conn, "SELECT * FROM prompt_sets WHERE id=?", (prompt_set["id"],))
            freeze_set(conn, prompt_set, actor, project)
            original_engine = one(conn, "SELECT * FROM engine_configs WHERE project_id=? AND kind='demo'", (project["id"],))
            conn.execute("UPDATE engine_configs SET rate_limit=600 WHERE id=?", (original_engine["id"],))
            engine_ids = [original_engine["id"]]
            for suffix in ("b", "c"):
                engine_ids.append(conn.execute(
                    "INSERT INTO engine_configs(client_id,project_id,name,vendor,kind,mode,rate_limit,created_at) VALUES(?,?,?,?,?,'memory',600,?)",
                    (project["client_id"], project["id"], f"demo-{suffix}", "GeoPulse", "demo", utc_now())).lastrowid)
            conn.commit()

        lock = threading.Lock()
        active_workers = active_providers = calls = 0
        max_workers = max_providers = 0
        original_process = measurement.process_answer
        original_ask = DemoProvider.ask

        def measured_process(answer_id: int) -> None:
            nonlocal active_workers, max_workers
            with lock:
                active_workers += 1
                max_workers = max(max_workers, active_workers)
            try:
                original_process(answer_id)
            finally:
                with lock:
                    active_workers -= 1

        def counted_ask(self, prompt: str, protocol: dict):
            nonlocal active_providers, max_providers, calls
            with lock:
                calls += 1
                active_providers += 1
                max_providers = max(max_providers, active_providers)
            try:
                return original_ask(self, prompt, protocol)
            finally:
                with lock:
                    active_providers -= 1

        measurement.process_answer = measured_process
        DemoProvider.ask = counted_ask
        wave = create_wave(project, actor, {"label": "100×3×3×3 离线压力 Wave", "prompt_set_id": prompt_set["id"],
                                            "engine_ids": engine_ids, "repeats": 3, "use_judge": True})
        run = create_run(project, wave, actor)
        worker = Worker(4)
        started = time.monotonic()
        worker.start()
        try:
            while time.monotonic() - started < args.timeout:
                with connect() as conn:
                    current = one(conn, "SELECT status FROM runs WHERE id=?", (run["id"],))
                if current["status"] in ("done", "partial", "failed", "cancelled"):
                    break
                time.sleep(0.25)
            else:
                raise AssertionError(f"stress run did not finish within {args.timeout}s: {current}")
        finally:
            worker.stop()
        execution_seconds = time.monotonic() - started
        assert current["status"] == "done", current
        assert calls == 2700, calls
        assert max_workers <= 4 and max_providers <= 3, (max_workers, max_providers)

        with connect() as conn:
            first = one(conn, "SELECT id,raw_text FROM answers WHERE run_id=? ORDER BY id LIMIT 1", (run["id"],))
        before_calls = calls
        original_process(first["id"])
        measurement.Worker(1).recover()
        assert calls == before_calls, "recovering a completed answer repeated a provider call"
        with connect() as conn:
            assert one(conn, "SELECT raw_text FROM answers WHERE id=?", (first["id"],))["raw_text"] == first["raw_text"]
            counts = {row["status"]: row["count"] for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM answers WHERE run_id=? GROUP BY status", (run["id"],))}
            answer_count = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=?", (run["id"],))["count"]
            observation_count = one(conn, "SELECT COUNT(*) AS count FROM observations o JOIN answers a ON a.id=o.answer_id WHERE a.run_id=?", (run["id"],))["count"]
            duplicate_samples = one(conn, """SELECT COUNT(*) AS count FROM (
                SELECT prompt_item_id,engine_config_id,round_no FROM answers WHERE run_id=?
                GROUP BY prompt_item_id,engine_config_id,round_no HAVING COUNT(*)>1)""", (run["id"],))["count"]
            duplicate_observations = one(conn, """SELECT COUNT(*) AS count FROM (
                SELECT o.answer_id,o.brand_entity_id,o.revision FROM observations o JOIN answers a ON a.id=o.answer_id
                WHERE a.run_id=? GROUP BY o.answer_id,o.brand_entity_id,o.revision HAVING COUNT(*)>1)""", (run["id"],))["count"]
        assert answer_count == 2700 and counts == {"succeeded": 2700}, (answer_count, counts)
        assert observation_count == 8100, observation_count
        assert duplicate_samples == duplicate_observations == 0

        read_api = {}
        with TestClient(create_app()) as client:
            login = client.post("/api/auth/login", json={"email": "admin@stress.local", "password": "stress-admin-password"})
            assert login.status_code == 200, login.text
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            project_id = client.get("/api/projects").json()["items"][0]["id"]
            endpoints = [
                ("overview", f"/api/projects/{project_id}/overview", 15),
                ("waves", f"/api/projects/{project_id}/waves", 15),
                ("run", f"/api/projects/{project_id}/runs/{run['id']}", 20),
                ("answers_50", f"/api/projects/{project_id}/runs/{run['id']}/answers?limit=50", 15),
                ("metrics", f"/api/projects/{project_id}/runs/{run['id']}/metrics", 5),
            ]
            for name, path, repetitions in endpoints:
                latencies = []
                for _ in range(repetitions):
                    request_started = time.perf_counter()
                    response = client.get(path)
                    latencies.append((time.perf_counter() - request_started) * 1000)
                    assert response.status_code == 200, response.text
                read_api[name] = {"requests": repetitions, "p95_ms": percentile95(latencies),
                                  "mean_ms": round(statistics.mean(latencies), 2), "max_ms": round(max(latencies), 2)}
        with connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db_bytes = (temp / "stress.db").stat().st_size
        result = {
            "status": "passed", "provider": "demo", "external_network_calls": 0,
            "shape": {"canonical_intents": 100, "phrasings_per_intent": 3, "engines": 3, "rounds": 3},
            "provider_calls": calls, "answers": answer_count, "observations": observation_count,
            "answer_statuses": counts, "duplicate_sample_keys": duplicate_samples,
            "duplicate_observation_revisions": duplicate_observations,
            "recovery_repeated_provider_calls": calls - before_calls,
            "worker_threads": 4, "max_active_workers": max_workers, "max_active_provider_calls": max_providers,
            "execution_seconds": round(execution_seconds, 2), "db_bytes": db_bytes,
            "read_api": read_api,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
