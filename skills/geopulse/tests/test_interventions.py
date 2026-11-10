from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.db import all_rows, connect, one
from backend.app.main import create_app
from backend.app.services.remeasurements import remind_due_consumer_rounds
from backend.app.services.scheduler import run_due_schedules
from conftest import ADMIN_PASSWORD, api, demo_wave, execute_run
from test_action_verification import create_gap, make_official
from test_manual_web import COLLECTION_PROTOCOL, PRODUCT_URL, single_prompt_set


def draft_action(client, small_sample_n=1):
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"small_sample_n": small_sample_n}})
    baseline, baseline_run = make_official(client, "Intervention 基线")
    create_gap(client, baseline_run["id"])
    generated = api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/opportunities/generate", json={})
    opportunity = generated["items"][0]
    api(client, "POST", f"/api/projects/{client.project_id}/opportunities/{opportunity['id']}/review", json={
        "decision": "confirmed", "eligibility": "client_confirmed", "business_value": 4, "executability": 4,
        "reason": "Intervention 离线夹具",
    })
    action = api(client, "POST", f"/api/projects/{client.project_id}/opportunities/{opportunity['id']}/actions", json={
        "title": "证据-backed 内容干预", "geo_step": 3, "owner": "交付负责人",
    })
    return baseline, baseline_run, action


def approved_action(client, small_sample_n=1):
    baseline, baseline_run, action = draft_action(client, small_sample_n)
    for status in ("review", "approved"):
        api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={"status": status})
    return baseline, baseline_run, action


def detail(client, action_id):
    return api(client, "GET", f"/api/projects/{client.project_id}/actions/{action_id}")


def brief_payload(brief, claims=None):
    return {key: brief[key] for key in ("information_gain", "hypothesis", "expected_observation", "channels", "success_criteria")} | {
        "claims": claims if claims is not None else brief["claims"]}


def publish(client, action, asset_id, url="https://example.com/intervention", days_ago=0, **extra):
    published_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/publications", json={
        "asset_id": asset_id, "channel": "owned_site", "outlet": "客户官网", "url": url,
        "published_at": published_at, "relationship": "owned", "cost": None, **extra})


def target_official(client, repeats=1):
    wave = demo_wave(client, repeats=repeats)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    return wave, run


def test_pending_claims_versions_and_multi_channel_publications(client):
    baseline, _, action = draft_action(client)
    initial = detail(client, action["id"])
    brief = initial["briefs"][0]
    pending = [{"text": "尚未核实的产品事实", "status": "pending", "evidence_refs": []}]
    api(client, "PUT", f"/api/projects/{client.project_id}/briefs/{brief['id']}", json=brief_payload(brief, pending))
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={"status": "review"})
    error = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status",
                json={"status": "approved"}, expected=409)
    assert "待确认主张" in error["detail"]
    api(client, "PUT", f"/api/projects/{client.project_id}/briefs/{brief['id']}", json=brief_payload(brief))
    api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/status", json={"status": "approved"})
    approved = detail(client, action["id"])
    approved_brief = approved["briefs"][0]
    api(client, "PUT", f"/api/projects/{client.project_id}/briefs/{approved_brief['id']}",
        json=brief_payload(approved_brief), expected=409)
    new_brief = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/briefs",
                    json=brief_payload(approved_brief))
    assert new_brief["version"] == 2 and new_brief["status"] == "draft"

    first_asset = next(item for item in approved["assets"] if item["status"] == "approved")
    second_asset = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/assets", json={
        "brief_id": approved_brief["id"], "title": "渠道问答资产", "asset_type": "faq",
        "content": {"summary": "只保存内容摘要，不复制原始回答"}, "facts": approved_brief["claims"],
        "applicability": "已核实的自托管部署场景", "exclusions": "不承诺排名",
    })
    api(client, "POST", f"/api/projects/{client.project_id}/assets/{second_asset['id']}/approve")
    first = publish(client, action, first_asset["id"], notes="内部首条发布备注")
    second = publish(client, action, second_asset["id"], url="https://example.com/partner/intervention",
                     channel="partner", outlet="合作媒体", relationship="paid", cost=12.5, currency="cny",
                     notes="内部成本备注", days_ago=5)
    assert first["cost"] is None and second["cost"] == 12.5 and second["currency"] == "CNY"
    current = detail(client, action["id"])
    assert current["action"]["status"] == "published"
    assert current["action"]["published_url"] == first["url"]
    assert len(current["publications"]) == 2
    assert "asset_delta" not in str(current) and "per_asset" not in str(current)
    assert len(current["timeline"]) >= 4
    target = demo_wave(client)
    round_row = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/remeasurements", json={
        "rounds": [{"target_wave_id": target["id"], "offset_days": 7}]})["items"][0]
    expected_due = (datetime.fromisoformat(first["published_at"]) + timedelta(days=7)).astimezone(timezone.utc).isoformat(timespec="seconds")
    assert round_row["due_at"] == expected_due  # a backdated later Publication must not move the first-publication anchor

    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [baseline["id"]]})
    client_html = client.get(f"/api/projects/{client.project_id}/reports/{report['id']}/export?variant=client&format=html").text
    internal_html = client.get(f"/api/projects/{client.project_id}/reports/{report['id']}/export?variant=internal&format=html").text
    assert "客户决策摘要" in client_html and "唯一下一轮建议" in client_html
    assert "客户官网" in client_html and "合作渠道" in client_html and "owned_site" not in client_html
    assert "12.5" not in client_html and "内部成本备注" not in client_html
    assert "12.5" in internal_html and "内部成本备注" in internal_html


def test_rounds_freeze_runs_comparison_and_provider_schedule_boundaries(client):
    baseline, baseline_run, action = approved_action(client, small_sample_n=1)
    current = detail(client, action["id"])
    asset = next(item for item in current["assets"] if item["status"] == "approved")
    publish(client, action, asset["id"])
    targets = [demo_wave(client) for _ in range(3)]
    created = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/remeasurements", json={
        "rounds": [{"target_wave_id": wave["id"], "offset_days": days} for wave, days in zip(targets, (7, 14, 28))],
    })["items"]
    assert [row["offset_days"] for row in created] == [7, 14, 28]
    assert all(row["evidence_strength"] == "尚未测量"
               for row in detail(client, action["id"])["decision_summary"]["observations"])
    assert all(row["baseline_run_id"] == baseline_run["id"] for row in created)
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM schedules WHERE action_id=?", (action["id"],))["count"] == 3

    replacement = api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/runs")["run"]
    assert execute_run(client, replacement["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/official", json={"run_id": replacement["id"]})
    # The baseline official Run changes after round creation; the frozen D7 basis must not move.
    d7_wave = targets[0]
    d7_run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{d7_wave['id']}/runs")["run"]
    assert execute_run(client, d7_run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{d7_wave['id']}/official", json={"run_id": d7_run["id"]})
    with connect() as conn:
        answer = one(conn, "SELECT * FROM answers WHERE run_id=? LIMIT 1", (d7_run["id"],))
        conn.execute("""INSERT INTO citations(client_id,project_id,answer_id,raw_url,title,domain,content_hash,returned_at)
            VALUES(?,?,?,?,?,?,?,?)""", (answer["client_id"], answer["project_id"], answer["id"],
            "https://example.com/cited-source", "离线引用夹具", "example.com", "citation-fixture-hash",
            datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
    assessed = api(client, "POST", f"/api/projects/{client.project_id}/remeasurements/{created[0]['id']}/assess",
                   json={"reason": "固定正式 Run 的离线 cohort 复测"})
    assert assessed["status"] == "measured" and assessed["observed_change"] == "improved"
    assert assessed["baseline_run_id"] == baseline_run["id"] and assessed["target_run_id"] == d7_run["id"]
    assert assessed["comparison_hash"] and assessed["comparison"]["comparable"]
    assert {ref["kind"] for ref in assessed["evidence_refs"]} == {"answer", "observation", "citation"}
    assert assessed["attribution_status"] == "not_attributable"
    api(client, "POST", f"/api/projects/{client.project_id}/remeasurements/{created[0]['id']}/assess", json={}, expected=409)

    new_target_run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{d7_wave['id']}/runs")["run"]
    assert execute_run(client, new_target_run["id"]) == "done"
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{d7_wave['id']}/official", json={"run_id": new_target_run["id"]})
    frozen = next(row for row in detail(client, action["id"])["rounds"] if row["id"] == created[0]["id"])
    assert frozen["target_run_id"] == d7_run["id"] and frozen["comparison_hash"] == assessed["comparison_hash"]

    with connect() as conn:
        due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        conn.execute("UPDATE schedules SET scheduled_at=?,next_run_at=? WHERE remeasurement_round_id=?",
                     (due, due, created[1]["id"]))
        conn.commit()
    assert run_due_schedules() == 1
    with connect() as conn:
        target_wave = one(conn, "SELECT * FROM waves WHERE id=?", (targets[1]["id"],))
        round_row = one(conn, "SELECT * FROM action_remeasurement_rounds WHERE id=?", (created[1]["id"],))
        assert target_wave["official_run_id"] is None
        assert round_row["target_run_id"] is None and round_row["status"] == "pending_measurement"


def test_insufficient_and_incomparable_are_not_improvement(client):
    _, _, action = approved_action(client, small_sample_n=30)
    asset = next(item for item in detail(client, action["id"])["assets"] if item["status"] == "approved")
    publish(client, action, asset["id"])
    same, _ = target_official(client)
    different, _ = target_official(client, repeats=2)
    rounds = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/remeasurements", json={
        "rounds": [{"target_wave_id": same["id"], "offset_days": 7},
                   {"target_wave_id": different["id"], "offset_days": 14}],
    })["items"]
    insufficient = api(client, "POST", f"/api/projects/{client.project_id}/remeasurements/{rounds[0]['id']}/assess", json={})
    incomparable = api(client, "POST", f"/api/projects/{client.project_id}/remeasurements/{rounds[1]['id']}/assess", json={})
    assert insufficient["status"] == "insufficient_evidence" and insufficient["observed_change"] == "unknown"
    assert incomparable["status"] == "incomparable" and incomparable["observed_change"] == "unknown"
    assert incomparable["comparison"]["mismatches"]


def test_consumer_web_round_only_reminds_and_read_roles_are_redacted(client):
    _, _, action = approved_action(client)
    asset = next(item for item in detail(client, action["id"])["assets"] if item["status"] == "approved")
    publish(client, action, asset["id"], days_ago=8, cost=99, currency="CNY", notes="内部渠道成本")
    existing = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"]
    target = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "复测提醒人工 Web", "vendor": "Manual fixture", "kind": "manual_web", "base_url": PRODUCT_URL,
        "measurement_target": "consumer_web", "mode": "memory"})
    judge = next(item for item in existing if item["kind"] == "demo")
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": single_prompt_set(client), "label": "Consumer Web 复测", "engine_ids": [target["id"]],
        "judge_engine_id": judge["id"], "repeats": 1, "use_judge": True, "collection_protocol": COLLECTION_PROTOCOL})
    rounds = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/remeasurements", json={
        "rounds": [{"target_wave_id": wave["id"], "offset_days": 7}]})["items"]
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM schedules WHERE remeasurement_round_id=?", (rounds[0]["id"],))["count"] == 0
        assert one(conn, "SELECT COUNT(*) AS count FROM runs WHERE wave_id=?", (wave["id"],))["count"] == 0
    assert remind_due_consumer_rounds() == 1
    assert remind_due_consumer_rounds() == 0
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM runs WHERE wave_id=?", (wave["id"],))["count"] == 0
        assert one(conn, "SELECT COUNT(*) AS count FROM alerts WHERE dedupe_key=?", (f"remeasurement-round:{rounds[0]['id']}",))["count"] == 1
    api(client, "POST", f"/api/projects/{client.project_id}/schedules", json={
        "wave_id": wave["id"], "action_id": action["id"], "scheduled_at": datetime.now(timezone.utc).isoformat()}, expected=409)

    user = api(client, "POST", "/api/users", json={"email": "intervention-viewer@test.local", "password": "viewer-password"})
    api(client, "POST", f"/api/projects/{client.project_id}/memberships", json={"user_id": user["id"], "role": "viewer"})
    with TestClient(create_app()) as scoped:
        login = api(scoped, "POST", "/api/auth/login", json={"email": "intervention-viewer@test.local", "password": "viewer-password"})
        scoped.headers["X-CSRF-Token"] = login["csrf_token"]
        redacted = api(scoped, "GET", f"/api/projects/{client.project_id}/actions/{action['id']}")
        assert "cost" not in redacted["publications"][0] and "notes" not in redacted["publications"][0]
        assert "evidence_json" not in redacted["opportunity"] and "score_json" not in redacted["opportunity"]
        assert redacted["opportunity"]["evidence"]["evidence_count"] >= 1
        assert all("evidence_refs" not in claim for brief in redacted["briefs"] for claim in brief["claims"])
        listed = api(scoped, "GET", f"/api/projects/{client.project_id}/opportunities")["items"]
        assert all("score_detail" not in item and "evidence" not in item["evidence"] for item in listed)
        assert listed[0]["evidence"]["evidence_count"] >= 1
        api(scoped, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/publications", json={
            "asset_id": asset["id"], "channel": "owned_site", "url": "https://example.com/forbidden",
            "published_at": datetime.now(timezone.utc).isoformat()}, expected=403)


def test_cross_project_evidence_is_rejected(client):
    _, _, action = draft_action(client)
    original_project = client.project_id
    other = api(client, "POST", "/api/projects", json={"client_name": "其他客户", "name": "跨项目证据隔离"})
    try:
        client.project_id = other["id"]
        single_prompt_set(client)
        api(client, "POST", f"/api/projects/{other['id']}/engines", json={
            "name": "其他项目 Demo", "vendor": "Demo", "kind": "demo", "mode": "memory"})
        entity = api(client, "POST", f"/api/projects/{other['id']}/entities", json={
            "name": "其他项目品牌", "role": "primary", "entity_card": {"aliases": []}})
        api(client, "POST", f"/api/projects/{other['id']}/entities/{entity['id']}/review",
            json={"decision": "confirmed", "reason": "跨项目隔离夹具"})
        wave = demo_wave(client)
        run = api(client, "POST", f"/api/projects/{other['id']}/waves/{wave['id']}/runs")["run"]
        assert execute_run(client, run["id"]) == "done"
        other_answer = api(client, "GET", f"/api/projects/{other['id']}/runs/{run['id']}/answers")["items"][0]
    finally:
        client.project_id = original_project
    brief = detail(client, action["id"])["briefs"][0]
    claims = [{"text": "错误引用其他项目", "status": "evidence_linked",
               "evidence_refs": [{"answer_id": other_answer["id"]}]}]
    error = api(client, "PUT", f"/api/projects/{original_project}/briefs/{brief['id']}",
                json=brief_payload(brief, claims), expected=400)
    assert "基线证据范围" in error["detail"]


def test_retention_preserves_frozen_assessment_and_marks_refs_unavailable(client):
    baseline, _, action = approved_action(client, small_sample_n=1)
    asset = next(item for item in detail(client, action["id"])["assets"] if item["status"] == "approved")
    publish(client, action, asset["id"])
    target, _ = target_official(client)
    round_row = api(client, "POST", f"/api/projects/{client.project_id}/actions/{action['id']}/remeasurements", json={
        "rounds": [{"target_wave_id": target["id"], "offset_days": 7}]})["items"][0]
    assessed = api(client, "POST", f"/api/projects/{client.project_id}/remeasurements/{round_row['id']}/assess", json={})
    with connect() as conn:
        conn.execute("UPDATE answers SET completed_at='2020-01-01T00:00:00+00:00' WHERE project_id=?", (client.project_id,))
        conn.commit()
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {"retention_days": 30, "small_sample_n": 1}})
    api(client, "POST", f"/api/projects/{client.project_id}/retention/execute", json={"confirm": True})
    current = detail(client, action["id"])
    frozen = current["rounds"][0]
    assert frozen["comparison_hash"] == assessed["comparison_hash"] and frozen["target_run_id"] == assessed["target_run_id"]
    assert all(ref["available_now"] is False and ref["unavailable_reason"] == "raw_purged"
               for ref in frozen["evidence_refs"] if ref["kind"] == "answer")
    assert all(ref["available_now"] is False for brief in current["briefs"] for claim in brief["claims"]
               for ref in claim["evidence_refs"])
    exported = api(client, "GET", f"/api/projects/{client.project_id}/export")
    for table in ("content_briefs", "action_assets", "asset_publications", "action_remeasurement_rounds"):
        assert exported["tables"][table]
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [baseline["id"], target["id"]]})
    gates = api(client, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")["gates"]
    assert any("原文已按保留策略清理" in gate for gate in gates)
