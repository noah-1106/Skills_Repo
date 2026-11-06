from datetime import datetime, timedelta, timezone

from backend.app.db import connect, one
from backend.app.migrations import backup, current_version, restore
from backend.app.services.scheduler import run_due_schedules
from conftest import api, demo_wave


def test_entity_version_review_and_pool_diff_are_project_scoped(client):
    project_id = client.project_id
    created = api(client, "POST", f"/api/projects/{project_id}/entities", json={
        "name": "Acme Cloud", "role": "competitor", "entity_card": {"aliases": ["Acme"], "category": "GEO"},
    })
    assert created["status"] == "draft"
    reviewed = api(client, "POST", f"/api/projects/{project_id}/entities/{created['id']}/review",
                   json={"decision": "confirmed", "reason": "官网与产品文档一致"})
    assert reviewed["status"] == "confirmed"
    version = api(client, "POST", f"/api/projects/{project_id}/entities/{created['id']}/versions", json={
        "name": "Acme Cloud", "role": "competitor", "entity_card": {"aliases": ["Acme", "AcmeCloud"]},
    })
    assert version["version"] == 2 and version["status"] == "draft"
    api(client, "POST", f"/api/projects/{project_id}/entities/{version['id']}/review",
        json={"decision": "confirmed", "reason": "补充官网使用的连写别名"})
    other = api(client, "POST", "/api/projects", json={"client_name": "其他客户", "name": "其他项目"})
    other_entity = api(client, "POST", f"/api/projects/{other['id']}/entities", json={"name": "SecretOther"})
    diff = api(client, "GET", f"/api/projects/{project_id}/entities/pool-diff?before={created['id']}&after={other_entity['id']}")
    assert diff["added"] == [] and diff["changed"] == []
    assert [row["id"] for row in diff["removed"]] == [created["id"]]


def test_opportunity_approval_action_publication_and_events(client, official_demo):
    wave_id, run_id = official_demo
    project_id = client.project_id
    answers = api(client, "GET", f"/api/projects/{project_id}/runs/{run_id}/answers")["items"]
    answer_id = answers[0]["id"]
    detail = api(client, "GET", f"/api/projects/{project_id}/answers/{answer_id}")
    for observation in detail["observations"]:
        if observation["revision"] != 1:
            continue
        primary = observation["role"] == "primary"
        api(client, "POST", f"/api/projects/{project_id}/answers/{answer_id}/observations/{observation['id']}/revisions",
            json={"entity_status": "confirmed", "mentioned": not primary,
                  "depth": "absent" if primary else "recommended", "sentiment": "unknown" if primary else "positive",
                  "top_choice": not primary, "evidence": "" if primary else detail["raw_text"],
                  "reason": "构造竞品领先机会夹具", "arbitrate": True})
    generated = api(client, "POST", f"/api/projects/{project_id}/waves/{wave_id}/opportunities/generate")
    assert generated["count"] == 1
    opportunity = generated["items"][0]
    assert opportunity["status"] == "candidate" and opportunity["score"] is None
    api(client, "POST", f"/api/projects/{project_id}/opportunities/{opportunity['id']}/actions", expected=409,
        json={"title": "未审核行动", "geo_step": 3})
    api(client, "PUT", f"/api/projects/{project_id}/settings",
        json={"settings": {"score_weights": {"business_value": 100}}})
    confirmed = api(client, "POST", f"/api/projects/{project_id}/opportunities/{opportunity['id']}/review",
                    json={"decision": "confirmed", "eligibility": "client_confirmed", "business_value": 5,
                          "executability": 4, "reason": "该发现题适用于客户业务"})
    assert confirmed["status"] == "confirmed" and confirmed["score"] > 0
    assert confirmed["score_detail"]["weights"]["business_value"] == 1.0  # wave 冻结权重，不读取事后项目设置
    action = api(client, "POST", f"/api/projects/{project_id}/opportunities/{opportunity['id']}/actions",
                 json={"title": "补充自托管事实页", "geo_step": 3, "owner": "交付负责人"})
    api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status", json={"status": "review"})
    api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status", json={"status": "approved"})
    api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status", expected=400,
        json={"status": "published"})
    api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status", expected=400,
        json={"status": "published", "published_at": "2026-11-06T10:00:00+08:00", "published_url": "javascript:alert(1)"})
    published = api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status",
                    json={"status": "published", "published_at": "2026-11-06T10:00:00+08:00",
                          "published_url": "https://example.com/geopulse-self-hosted"})
    assert published["published_at"]
    events = api(client, "GET", f"/api/projects/{project_id}/events")["items"]
    assert events[0]["source"] == "https://example.com/geopulse-self-hosted"
    next_wave = demo_wave(client)
    api(client, "POST", f"/api/projects/{project_id}/actions/{action['id']}/status",
        json={"status": "remeasure_due", "target_wave_id": next_wave["id"]})


def test_scheduler_backup_export_and_secret_exclusion(client, official_demo, tmp_path):
    wave_id, _ = official_demo
    project_id = client.project_id
    engine = api(client, "POST", f"/api/projects/{project_id}/engines", json={
        "name": "test-production", "vendor": "Test", "kind": "openai_compat", "model": "test-model",
        "base_url": "https://example.test/v1", "api_key": "test-only-secret-value", "mode": "memory",
    })
    assert engine["has_api_key"] and "secret_ref" not in engine
    exported = api(client, "GET", f"/api/projects/{project_id}/export")
    assert exported["sha256"]
    assert "test-only-secret-value" not in str(exported)
    assert all(not row["secret_ref"] for row in exported["tables"]["engine_configs"])
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    schedule = api(client, "POST", f"/api/projects/{project_id}/schedules", json={"wave_id": wave_id, "scheduled_at": due})
    assert run_due_schedules() == 1
    assert run_due_schedules() == 0
    with connect() as conn:
        assert one(conn, "SELECT status,last_run_id FROM schedules WHERE id=?", (schedule["id"],))["status"] == "done"
        assert one(conn, "SELECT COUNT(*) AS count FROM runs WHERE wave_id=?", (wave_id,))["count"] == 2
    manifest = backup(tmp_path / "safe-backup.db")
    assert manifest["schema_version"] == 1
    restored = tmp_path / "restored.db"
    restore(tmp_path / "safe-backup.db", restored)
    assert current_version(restored) == 1
