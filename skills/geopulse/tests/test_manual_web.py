from __future__ import annotations

import base64
import copy
import hashlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import migrations
from backend.app.db import connect, dumps, one
from backend.app.main import create_app
from backend.app.providers import ProviderError, build_provider
from backend.app.services.measurement import Worker, create_run
from conftest import ADMIN_PASSWORD, api, demo_wave, execute_run

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PRODUCT_URL = "https://consumer.example.test/chat"
COLLECTION_PROTOCOL = {
    "product_url": PRODUCT_URL,
    "platform": "test_consumer",
    "surface": "desktop_web",
    "page_mode": "default",
    "networking": False,
    "deep_thinking": False,
    "deep_research": False,
    "session_mode": "new",
    "login_state": "anonymous",
    "account_type": "",
    "region": "CN",
    "language": "zh-CN",
    "context_clearing": "new_session",
    "follow_up_policy": "none",
    "protocol_version": "manual-web-v1",
}
ACTUAL_CONTEXT = {key: value for key, value in COLLECTION_PROTOCOL.items()
                  if key not in {"product_url", "platform", "protocol_version"}}


def single_prompt_set(client) -> int:
    project = client.project_id
    api(client, "PUT", f"/api/projects/{project}/settings", json={"settings": {
        "prompt_quotas": {"brand": 0, "scene": 0, "compare": 0, "choice": 0}}})
    prompt_set = api(client, "POST", f"/api/projects/{project}/prompt-sets", json={"name": "人工 Web 单题夹具"})
    imported = api(client, "POST", f"/api/projects/{project}/prompt-sets/{prompt_set['id']}/items", json={
        "items": [{"text": "哪些 GEO 工具适合证据审计？", "dimension": "choice",
                   "query_type": "discovery", "priority": 5, "eligibility": "eligible"}]})
    item_id = imported["items"][0]["id"]
    api(client, "POST", f"/api/projects/{project}/prompt-sets/{prompt_set['id']}/items/{item_id}/review",
        json={"status": "reviewed", "eligibility": "eligible"})
    api(client, "POST", f"/api/projects/{project}/prompt-sets/{prompt_set['id']}/status",
        json={"status": "reviewing", "reason": "隔离测试提交审核"})
    api(client, "POST", f"/api/projects/{project}/prompt-sets/{prompt_set['id']}/status",
        json={"status": "frozen", "reason": "隔离测试冻结"})
    return prompt_set["id"]


def manual_run(client):
    project = client.project_id
    existing = api(client, "GET", f"/api/projects/{project}/engines")["items"]
    target = api(client, "POST", f"/api/projects/{project}/engines", json={
        "name": f"人工 Consumer Web 夹具 {len(existing) + 1}", "vendor": "Manual fixture", "kind": "manual_web",
        "base_url": PRODUCT_URL, "measurement_target": "consumer_web", "mode": "memory"})
    assert not target["has_api_key"]
    judge = next(item for item in existing if item["kind"] == "demo")
    wave = api(client, "POST", f"/api/projects/{project}/waves", json={
        "prompt_set_id": single_prompt_set(client), "label": "人工 Consumer Web Wave",
        "engine_ids": [target["id"]], "judge_engine_id": judge["id"], "repeats": 1,
        "use_judge": True, "collection_protocol": COLLECTION_PROTOCOL})
    assert wave["estimate"]["collection_tasks"] == 1
    assert wave["estimate"]["answer_calls"] == wave["estimate"]["search_calls"] == 0
    assert wave["estimate"]["judge_calls"] == 1
    assert wave["estimate"]["by_engine"][0]["engine"] == judge["name"]
    run = api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/runs")["run"]
    answer = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/answers")["items"][0]
    assert run["status"] == "running"
    assert answer["status"] == answer["collection_status"] == "awaiting_collection"
    return target, judge, wave, run, answer


def valid_draft() -> dict:
    return {
        "draft_text": "GeoPulse 适合需要自托管和证据审计的团队。",
        "actual_url": PRODUCT_URL + "/conversation/123",
        "observed_mode": "default",
        "observed_at": "2026-11-07T10:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "session_context": copy.deepcopy(ACTUAL_CONTEXT),
        "retrieval_status": "off",
        "notes": "人工测试夹具，不代表真实消费者平台 live 验收。",
        "citations": [{"url": "https://docs.example.test/geopulse", "title": "人工看到的引用卡片",
                       "text": "GeoPulse 证据审计"}],
        "status": "review_pending",
    }


def upload(client, answer_id: int, content: bytes = PNG, *, kind="screenshot", filename="evidence.png",
           media_type="image/png", expected=200, checksum=None):
    response = client.post(
        f"/api/projects/{client.project_id}/answers/{answer_id}/attachments",
        params={"kind": kind, "filename": filename, "media_type": media_type}, content=content,
        headers={"X-Content-SHA256": checksum if checksum is not None else hashlib.sha256(content).hexdigest(),
                 "Content-Type": "application/octet-stream"})
    assert response.status_code == expected, response.text
    return response.json()


def submit(client, answer_id: int, payload=None, expected=200):
    return api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer_id}/collection/submit",
               json=payload or valid_draft(), expected=expected)


def complete_manual(client, answer_id: int, run_id: int):
    upload(client, answer_id)
    submitted = submit(client, answer_id)
    assert submitted["answer_status"] == "judging"
    assert execute_run(client, run_id) == "done"
    return submitted


def arbitrate_all(client, answer_id: int):
    answer = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer_id}")
    for observation in answer["observations"]:
        payload = {key: observation[key] for key in
                   ("entity_status", "mentioned", "depth", "sentiment", "top_choice")}
        payload.update({"evidence": observation["evidence"], "reason": "人工 Web 离线测试复核", "arbitrate": True})
        api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer_id}/observations/{observation['id']}/revisions",
            json=payload)


def test_manual_collection_immutable_submission_independent_judge_and_export(client, tmp_path):
    target, judge, wave, run, answer = manual_run(client)
    project = client.project_id
    with pytest.raises(ProviderError) as error:
        build_provider(target)
    assert error.value.kind == "manual_target_not_provider"
    Worker(1).recover()
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (answer["id"],))["status"] == "awaiting_collection"

    draft = valid_draft()
    saved = api(client, "PUT", f"/api/projects/{project}/answers/{answer['id']}/collection/draft", json=draft)
    assert saved["status"] == "review_pending"
    upload(client, answer["id"], b"not-a-png", expected=400)
    upload(client, answer["id"], checksum="0" * 64, expected=400)
    attachment = upload(client, answer["id"])
    download = client.get(f"/api/projects/{project}/attachments/{attachment['id']}")
    assert download.status_code == 200 and download.content == PNG
    assert download.headers["x-content-sha256"] == attachment["sha256"]
    assert download.headers["content-security-policy"].startswith("sandbox")

    submitted = submit(client, answer["id"])
    submit(client, answer["id"], expected=409)
    assert execute_run(client, run["id"]) == "done"
    detail = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}")
    assert detail["status"] == "succeeded" and detail["valid_sample"] == 1
    assert detail["usage"] == {}
    assert detail["raw_text_sha256"] == hashlib.sha256(detail["raw_text"].encode()).hexdigest()
    assert [item["kind"] for item in detail["call_attempts"]] == ["judge"], detail["call_attempts"]
    assert detail["call_attempts"][0]["engine_config_id"] == judge["id"]
    assert all(item["judge_status"] == "demo-rules" for item in detail["observations"])
    assert all(item["origin"] == "manual_page" for item in detail["citations"])
    metrics = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/metrics")
    assert metrics["quality"]["evidence_coverage"]["hits"] == 1
    assert metrics["quality"]["collection_status_counts"] == {"completed": 1}
    assert metrics["measurement_targets"] == ["consumer_web"]

    arbitrate_all(client, answer["id"])
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    report = api(client, "POST", f"/api/projects/{project}/reports", json={"wave_ids": [wave["id"]]})
    report_detail = api(client, "GET", f"/api/projects/{project}/reports/{report['id']}")
    assert report_detail["gates"] == []
    assert report_detail["snapshot"]["waves"][0]["collection_evidence"][0]["valid"]
    html = client.get(f"/api/projects/{project}/reports/{report['id']}/export?variant=client&format=html")
    assert "人工 Consumer Web" in html.text and "人工记录的页面引用" in html.text
    assert "<h2>原始回答与判定</h2>" not in html.text
    assert "内部成本与质量" not in html.text

    exported = api(client, "GET", f"/api/projects/{project}/export")
    assert exported["export_contract"] == "geopulse-project-v2"
    blobs = [row["content"] for row in exported["tables"]["answer_attachments"]]
    assert base64.b64decode(blobs[0]["data"]) == PNG and blobs[0]["encoding"] == "base64"
    from backend.app.migrations import backup, restore
    backup_path = tmp_path / "with-evidence.db"
    backup(backup_path)
    restored = tmp_path / "restored.db"
    restore(backup_path, restored)
    import sqlite3
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT content FROM answer_attachments WHERE id=?", (attachment["id"],)).fetchone()[0] == PNG


@pytest.mark.parametrize("mutation", [
    {"draft_text": "   "},
    {"actual_url": "https://other.example.test/chat"},
    {"observed_at": "2026-11-07T10:00:00"},
    {"observed_at": "2026-11-07T10:00:00+00:00"},
    {"timezone": "Not/AZone"},
    {"observed_mode": "another-mode"},
    {"citations": [{"url": "javascript:alert(1)"}]},
])
def test_submission_rejects_missing_or_inconsistent_facts(client, mutation):
    _, _, _, _, answer = manual_run(client)
    upload(client, answer["id"])
    payload = valid_draft() | mutation
    submit(client, answer["id"], payload, expected=422)
    with connect() as conn:
        row = one(conn, "SELECT status,raw_text,valid_sample FROM answers WHERE id=?", (answer["id"],))
        assert row["status"] == "awaiting_collection" and row["raw_text"] is None and row["valid_sample"] is None


def test_submission_requires_screenshot_and_valid_context_keys(client):
    _, _, _, _, answer = manual_run(client)
    submit(client, answer["id"], expected=422)
    payload = valid_draft()
    payload["session_context"]["cookie"] = "must-not-be-stored"
    api(client, "PUT", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/draft",
        json=payload, expected=400)
    upload(client, answer["id"], b"x" * (10 * 1024 * 1024 + 1), kind="raw_text",
           filename="too-large.txt", media_type="text/plain", expected=400)


@pytest.mark.parametrize("content,media_type,filename", [
    (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", "image/jpeg", "evidence.jpg"),
    (b"RIFF\x04\x00\x00\x00WEBP", "image/webp", "evidence.webp"),
])
def test_screenshot_magic_variants_and_attachment_limit(client, content, media_type, filename):
    _, _, _, _, answer = manual_run(client)
    uploaded = upload(client, answer["id"], content, filename=filename, media_type=media_type)
    assert uploaded["byte_size"] == len(content)
    for index in range(11):
        upload(client, answer["id"], f"raw evidence {index}".encode(), kind="raw_text",
               filename=f"evidence-{index}.txt", media_type="text/plain")
    upload(client, answer["id"], b"one too many", kind="raw_text",
           filename="evidence-12.txt", media_type="text/plain", expected=409)
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert len(collection["attachments"]) == 12


@pytest.mark.parametrize("failure_type", [
    "captcha", "login_expired", "empty", "truncated", "error_page", "stream_interrupted", "other"])
def test_collection_failures_are_not_zero_mentions(client, failure_type):
    _, _, _, run, answer = manual_run(client)
    result = api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/fail",
                 json={"failure_type": failure_type, "failure_detail": "人工失败登记"})
    assert result["answer_status"] == "failed"
    with connect() as conn:
        row = one(conn, "SELECT valid_sample,raw_text FROM answers WHERE id=?", (answer["id"],))
        assert row["valid_sample"] == 0 and row["raw_text"] is None
        assert one(conn, "SELECT status FROM runs WHERE id=?", (run["id"],))["status"] == "failed"
    metrics = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}/metrics")
    assert metrics["quality"]["valid_samples"] == 0
    assert metrics["quality"]["collection_failure_counts"] == {failure_type: 1}


def test_retry_recollect_cancel_and_scheduler_guard(client):
    _, _, wave, run, answer = manual_run(client)
    project = client.project_id
    api(client, "POST", f"/api/projects/{project}/schedules",
        json={"wave_id": wave["id"], "recurrence_days": 7}, expected=409)
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM schedules WHERE wave_id=?", (wave["id"],))["count"] == 0
    upload(client, answer["id"])
    api(client, "POST", f"/api/projects/{project}/answers/{answer['id']}/collection/fail",
        json={"failure_type": "captcha", "failure_detail": "需要重采"})
    retried = api(client, "POST", f"/api/projects/{project}/runs/{run['id']}/retry", json={})
    assert retried["queued"] == 1
    with connect() as conn:
        assert one(conn, "SELECT status FROM answers WHERE id=?", (answer["id"],))["status"] == "awaiting_collection"
        assert one(conn, "SELECT status FROM web_collections WHERE answer_id=?", (answer["id"],))["status"] == "recollect_required"
        assert one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=?", (answer["id"],))["count"] == 0
        project_row = one(conn, "SELECT * FROM projects WHERE id=?", (project,))
        wave_row = one(conn, "SELECT * FROM waves WHERE id=?", (wave["id"],))
        with pytest.raises(HTTPException) as error:
            create_run(project_row, wave_row, 1, conn=conn)
        assert error.value.status_code == 409
    complete_manual(client, answer["id"], run["id"])

    _, _, _, second_run, second_answer = manual_run(client)
    api(client, "POST", f"/api/projects/{project}/runs/{second_run['id']}/cancel", json={})
    with connect() as conn:
        row = one(conn, "SELECT status,valid_sample FROM answers WHERE id=?", (second_answer["id"],))
        assert row["status"] == "cancelled" and row["valid_sample"] == 0
        assert one(conn, "SELECT status FROM runs WHERE id=?", (second_run["id"],))["status"] == "cancelled"


def test_collection_permissions_cross_project_and_report_evidence_gate(client):
    _, _, wave, run, answer = manual_run(client)
    project = client.project_id
    complete_manual(client, answer["id"], run["id"])
    arbitrate_all(client, answer["id"])
    collection = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}/collection")
    attachment_id = collection["attachments"][0]["id"]
    other_project = api(client, "POST", "/api/projects", json={"client_name": "其他客户", "name": "隔离项目"})
    api(client, "GET", f"/api/projects/{other_project['id']}/answers/{answer['id']}/collection", expected=404)
    api(client, "GET", f"/api/projects/{other_project['id']}/attachments/{attachment_id}", expected=404)
    for role in ("reviewer", "viewer"):
        user = api(client, "POST", "/api/users", json={"email": f"web-{role}@test.local", "password": "role-test-password"})
        api(client, "POST", f"/api/projects/{project}/memberships", json={"user_id": user["id"], "role": role})
        with TestClient(create_app()) as scoped:
            login = api(scoped, "POST", "/api/auth/login", json={"email": f"web-{role}@test.local", "password": "role-test-password"})
            scoped.headers["X-CSRF-Token"] = login["csrf_token"]
            redacted = api(scoped, "GET", f"/api/projects/{project}/answers/{answer['id']}/collection")
            assert redacted["draft_text"] is None and redacted["notes"] == ""
            api(scoped, "GET", f"/api/projects/{project}/attachments/{attachment_id}", expected=403)
            api(scoped, "POST", f"/api/projects/{project}/answers/{answer['id']}/collection/submit",
                json=valid_draft(), expected=403)
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    with connect() as conn:
        conn.execute("UPDATE answer_attachments SET content=? WHERE id=?", (b"tampered", attachment_id))
        conn.commit()
    report = api(client, "POST", f"/api/projects/{project}/reports", json={"wave_ids": [wave["id"]]})
    detail = api(client, "GET", f"/api/projects/{project}/reports/{report['id']}")
    assert any("Consumer Web 样本" in item for item in detail["gates"])
    api(client, "POST", f"/api/projects/{project}/reports/{report['id']}/status",
        json={"status": "data_checked"}, expected=409)


def test_web_retention_tombstone_and_cross_surface_comparison(client):
    _, _, wave, run, answer = manual_run(client)
    project = client.project_id
    complete_manual(client, answer["id"], run["id"])
    arbitrate_all(client, answer["id"])
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    baseline = demo_wave(client)
    baseline_run = api(client, "POST", f"/api/projects/{project}/waves/{baseline['id']}/runs")["run"]
    assert execute_run(client, baseline_run["id"]) == "done"
    api(client, "POST", f"/api/projects/{project}/waves/{baseline['id']}/official", json={"run_id": baseline_run["id"]})
    comparison = api(client, "GET", f"/api/projects/{project}/compare",
                     params={"baseline_wave": baseline["id"], "current_wave": wave["id"]})
    assert comparison["comparison_scope"] == "cross_surface" and comparison["exploratory"]
    assert comparison["delta"] is None and comparison["transitions"] == []

    with connect() as conn:
        conn.execute("UPDATE answers SET completed_at='2020-01-01T00:00:00+00:00' WHERE id=?", (answer["id"],))
        conn.commit()
    api(client, "PUT", f"/api/projects/{project}/settings", json={"settings": {"retention_days": 30}})
    result = api(client, "POST", f"/api/projects/{project}/retention/execute", json={"confirm": True})
    assert result["purged_count"] == 1 and result["attachment_purged_count"] == 1
    collection = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}/collection")
    assert collection["draft_text"] == "" and collection["content_purged_at"]
    assert collection["citations"][0]["text"] == ""
    assert not collection["attachments"][0]["available"]
    api(client, "GET", f"/api/projects/{project}/attachments/{collection['attachments'][0]['id']}", expected=410)
    report = api(client, "POST", f"/api/projects/{project}/reports", json={"wave_ids": [wave["id"]]})
    detail = api(client, "GET", f"/api/projects/{project}/reports/{report['id']}")
    assert any("Consumer Web 样本" in item for item in detail["gates"])


def test_populated_v2_migration_preserves_engine_ids_and_foreign_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOPULSE_DB", str(tmp_path / "v2.db"))
    monkeypatch.setenv("GEOPULSE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("GEOPULSE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GEOPULSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 2)
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
                               (project["client_id"], project["id"], prompt_set["id"], "entities", "v2 数据",
                                dumps(protocol), "{}", now)).lastrowid
        run_id = conn.execute("INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json) VALUES(?,?,?,1,'done',?)",
                              (project["client_id"], project["id"], wave_id, dumps({"protocol": protocol}))).lastrowid
        answer_id = conn.execute("INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,raw_text,status,created_at) VALUES(?,?,?,?,?,1,'旧原文','succeeded',?)",
                                 (project["client_id"], project["id"], run_id, prompt["id"], engine["id"], now)).lastrowid
        conn.commit()
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 3)
    result = migrations.migrate()
    assert result["from"] == 2 and result["to"] == 3 and result["backup"]
    with connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        migrated = one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,))
        assert migrated["engine_config_id"] == engine["id"] and migrated["raw_text"] == "旧原文"
        assert migrated["raw_text_sha256"] == ""
        assert one(conn, "SELECT kind FROM engine_configs WHERE id=?", (engine["id"],))["kind"] == "demo"
