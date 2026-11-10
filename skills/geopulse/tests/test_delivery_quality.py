from __future__ import annotations

import json

from backend.app.db import connect, one
from backend.app.engine.judge import fallback_observations, judge_answer
from backend.app.providers.base import ProviderResult
from conftest import api, demo_wave, execute_run
from test_judge_batches import disabled_demo_run, wait_batch


class MockJudge:
    def __init__(self, payload):
        self.payload = payload

    def ask_json(self, prompt, protocol):
        return ProviderResult(text=json.dumps(self.payload, ensure_ascii=False), model="deepseek-flash",
                              usage={"prompt_tokens": 100, "completion_tokens": 20}, latency_ms=25,
                              request_id="mock-judge", operations=[{"kind": "judge", "status": "succeeded",
                              "model": "deepseek-flash", "usage": {"prompt_tokens": 100, "completion_tokens": 20}}])


def entity():
    return {"id": 1, "name": "示例品牌", "role": "primary", "entity_card": {"aliases": []}}


def test_judge_guards_keep_fallback_recommendations_provisional():
    answer = "示例品牌提供报表。其他产品更值得推荐。"
    payload = {"brands": [{"entity_id": 1, "entity_status": "confirmed", "mentioned": True,
                           "depth": "recommended", "sentiment": "positive", "top_choice": True,
                           "evidence": "这句不在原文中", "citation_urls": []}], "discovered_entities": []}
    observations, _, _ = judge_answer(MockJudge(payload), answer, [entity()], {}, [])
    observation = observations[0]
    assert observation["judge_status"] == "llm-judge-evidence-fallback"
    assert observation["review_status"] == "pending" and observation["review_reason"] == "推荐深度待确认"

    payload["brands"][0].update(sentiment="negative", evidence="示例品牌提供报表。")
    negative, _, _ = judge_answer(MockJudge(payload), answer, [entity()], {}, [])
    assert negative[0]["depth"] == "mentioned" and not negative[0]["top_choice"]

    rules = fallback_observations("首选示例品牌，值得推荐。", [entity()], demo=False)[0]
    assert rules["depth"] == "recommended" and rules["review_status"] == "pending"
    assert rules["review_reason"] == "规则回退推荐深度待确认"

    # 逐字匹配不证明语义支持推荐；此类假阳性必须留给人工 revision。
    payload["brands"][0].update(sentiment="positive", evidence="其他产品更值得推荐。")
    verbatim, _, _ = judge_answer(MockJudge(payload), answer, [entity()], {}, [])
    assert verbatim[0]["evidence"] in answer and verbatim[0]["review_status"] == "machine"


def test_real_disabled_judge_requires_admin_confirmation_before_any_run(client):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "匿名真实配置", "vendor": "Test", "kind": "openai_compat", "model": "configured-chat",
        "base_url": "https://example.test/v1", "api_key": "test-only-secret", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 1, "output_per_million": 2},
    })
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "真实关闭 Judge 确认", "engine_ids": [engine["id"]],
        "repeats": 1, "use_judge": False,
    })
    assert wave["readiness"]["requires_judge_disabled_confirmation"]
    assert wave["readiness"]["duration"]["status"] == "unknown"
    error = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs", expected=409)
    assert error["detail"]["code"] == "judge_disabled_confirmation_required"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM runs")["count"] == 0
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts")["count"] == 0
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs",
              json={"confirm_judge_disabled": True})["run"]
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM audit_events WHERE object_type='run' AND object_id=? AND action='confirm_judge_disabled'",
                   (str(run["id"]),))["count"] == 1


def test_partial_judge_coverage_blocks_report_and_strict_comparison(client):
    engine, baseline, baseline_run = disabled_demo_run(client, repeats=1)
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/official", json={"run_id": baseline_run["id"]})
    answer_id = api(client, "GET", f"/api/projects/{client.project_id}/runs/{baseline_run['id']}/answers")["items"][0]["id"]
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{baseline_run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"], "answer_ids": [answer_id]})
    assert wait_batch(client, batch["id"]) == "done"
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [baseline["id"]]})
    detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")
    assert detail["snapshot"]["waves"][0]["quality"]["judge_lineage"] == "mixed"
    assert any("覆盖或配置不一致" in error for error in detail["gates"])
    api(client, "POST", f"/api/projects/{client.project_id}/reports/{report['id']}/status",
        json={"status": "data_checked", "reason": "尝试审批"}, expected=409)

    _, current, current_run = disabled_demo_run(client, repeats=1)
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{current['id']}/official", json={"run_id": current_run["id"]})
    comparison = api(client, "GET", f"/api/projects/{client.project_id}/compare?baseline_wave={baseline['id']}&current_wave={current['id']}")
    assert not comparison["comparable"]
    assert comparison.get("delta") is None
    assert "Judge" in comparison["reason"]


def test_full_effective_judge_lineage_allows_strict_comparison(client):
    engine, baseline, baseline_run = disabled_demo_run(client, repeats=1)
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{baseline['id']}/official", json={"run_id": baseline_run["id"]})
    _, current, current_run = disabled_demo_run(client, repeats=1)
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{current['id']}/official", json={"run_id": current_run["id"]})
    for run in (baseline_run, current_run):
        batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                    json={"judge_engine_id": engine["id"]})
        assert wait_batch(client, batch["id"]) == "done"
    comparison = api(client, "GET", f"/api/projects/{client.project_id}/compare?baseline_wave={baseline['id']}&current_wave={current['id']}")
    assert comparison["comparable"] and comparison["delta"]


def test_report_and_handoff_expose_actual_models_formulas_and_next_action(client):
    engine = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"][0]
    engine = api(client, "PUT", f"/api/projects/{client.project_id}/engines/{engine['id']}", json={
        "name": engine["name"], "vendor": "Mock", "kind": "demo", "model": "deepseek-chat",
        "base_url": "", "api_key": "", "mode": "memory",
    })
    prompt_set_id = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]["id"]
    judge_engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": "独立 Mock Judge", "vendor": "Mock", "kind": "demo", "model": "deepseek-chat",
        "base_url": "", "api_key": "", "mode": "memory",
    })
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set_id, "label": "双模型回显", "engine_ids": [engine["id"]],
        "judge_engine_id": judge_engine["id"], "repeats": 1, "use_judge": True,
    })
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    with connect() as conn:
        conn.execute("UPDATE answers SET model='deepseek-flash' WHERE run_id=?", (run["id"],))
        conn.execute("UPDATE call_attempts SET model='deepseek-flash' WHERE run_id=? AND kind='judge'", (run["id"],))
        conn.commit()
    api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    handoff = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run['id']}/handoff")
    assert handoff["next_action"]["kind"] == "generate_opportunities"
    assert handoff["external_sync"]["automatic"] is False and handoff["work_log"]["mode"] == "manual_reminder_only"
    assert "cost" not in str(handoff).lower() and "secret_ref" not in str(handoff)
    report = api(client, "POST", f"/api/projects/{client.project_id}/reports", json={"wave_ids": [wave["id"]]})
    detail = api(client, "GET", f"/api/projects/{client.project_id}/reports/{report['id']}")
    snapshot = detail["snapshot"]["waves"][0]
    models = snapshot["quality"]["models"]
    assert models["answers"][0]["configured_model"] == "deepseek-chat"
    assert models["answers"][0]["actual_models"] == ["deepseek-flash"]
    assert models["judges"][0]["actual_models"] == ["deepseek-flash"]
    coverage = next(item for item in snapshot["metric_appendix"]["items"] if item["key"] == "coverage")
    assert coverage["observed"]["hits"] == snapshot["metrics"]["coverage"]["hits"]
    assert coverage["observed"]["n"] == snapshot["metrics"]["coverage"]["n"]
    assert "Σ(weight(g)" in coverage["formula"]
    html = client.get(f"/api/projects/{client.project_id}/reports/{report['id']}/export?variant=internal&format=html")
    assert html.status_code == 200
    assert "deepseek-flash" in html.text and "指标公式与分母附录" in html.text


def test_source_domain_settings_normalize_without_rewriting_citations(client):
    wave = demo_wave(client)
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    with connect() as conn:
        before = conn.execute("SELECT id,source_type,domain FROM citations ORDER BY id").fetchall()
    result = api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {
        "source_domains": {"Example.COM.": "新闻", "行业.example": "行业"}}})
    assert result["settings"]["source_domains"]["example.com"] == "新闻"
    api(client, "PUT", f"/api/projects/{client.project_id}/settings", json={"settings": {
        "source_domains": {"https://example.com/path": "新闻"}}}, expected=400)
    with connect() as conn:
        after = conn.execute("SELECT id,source_type,domain FROM citations ORDER BY id").fetchall()
        assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_handoff_drives_zero_candidate_report_approval_worklog_and_wave_completion(client):
    engine, wave, run = disabled_demo_run(client, repeats=1)
    project = client.project_id
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/official", json={"run_id": run["id"]})
    stale = api(client, "POST", f"/api/projects/{project}/reports", json={"wave_ids": [wave["id"]]})
    stale_detail = api(client, "GET", f"/api/projects/{project}/reports/{stale['id']}")
    assert any("Judge" in gate for gate in stale_detail["gates"])

    batch = api(client, "POST", f"/api/projects/{project}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    assert wait_batch(client, batch["id"]) == "done"
    handoff = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")
    assert handoff["next_action"]["kind"] == "generate_opportunities"
    opportunities = api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/opportunities/generate")
    for opportunity in opportunities["items"]:
        api(client, "POST", f"/api/projects/{project}/opportunities/{opportunity['id']}/review",
            json={"decision": "rejected", "reason": "交接测试：本轮不投入"})
    handoff = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")
    assert handoff["opportunities"]["checked"]
    assert handoff["next_action"]["kind"] == "create_report"
    assert "最新报告快照" in handoff["next_action"]["reason"]
    assert api(client, "GET", f"/api/projects/{project}/reports/{stale['id']}")["data_snapshot_hash"] == stale["data_snapshot_hash"]

    report = api(client, "POST", f"/api/projects/{project}/reports", json={"wave_ids": [wave["id"]]})
    assert report["version"] == stale["version"] + 1
    assert api(client, "GET", f"/api/projects/{project}/reports/{report['id']}")["gates"] == []
    assert api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")["next_action"] == {
        "kind": "approve_report", "report_id": report["id"]}
    for status in ("data_checked", "strategy_reviewed", "client_approved"):
        api(client, "POST", f"/api/projects/{project}/reports/{report['id']}/status", json={"status": status})
    handoff = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")
    assert handoff["next_action"]["kind"] == "record_work_log_reminder"
    assert handoff["work_log"] == {"entries": 0, "hours": 0, "missing": True, "mode": "manual_reminder_only"}
    api(client, "POST", f"/api/projects/{project}/work-logs",
        json={"hours": 0.5, "kind": "交付复核", "note": "人工登记", "work_date": "2026-11-10"})
    assert api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")["next_action"]["kind"] == "close_or_analyze_wave"
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/status", json={"status": "analyzed"})
    assert api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/handoff")["next_action"]["kind"] == "complete"


def test_opportunity_check_is_distinct_from_not_checked(client, official_demo):
    wave_id, run_id = official_demo
    handoff = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/handoff")
    assert handoff["opportunities"]["status"] == "not_checked"
    result = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave_id}/opportunities/generate")
    handoff = api(client, "GET", f"/api/projects/{client.project_id}/runs/{run_id}/handoff")
    assert handoff["opportunities"]["checked"] and handoff["opportunities"]["generated_count"] == result["count"]
    assert handoff["opportunities"]["status"] == ("checked_empty" if not result["items"] else "checked")


def test_cancel_queued_batch_makes_no_calls_or_new_revisions(client):
    engine, _, run = disabled_demo_run(client, repeats=1)
    batch = api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/judge-batches",
                json={"judge_engine_id": engine["id"]})
    cancelled = api(client, "POST", f"/api/projects/{client.project_id}/judge-batches/{batch['id']}/cancel", json={})
    assert cancelled["status"] == "cancelled"
    from backend.app.services.measurement import Worker
    worker = Worker(1)
    worker.recover()
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE judge_batch_id=?", (batch["id"],))["count"] == 0
        assert one(conn, "SELECT MAX(revision) AS value FROM observations")["value"] == 1
        assert one(conn, "SELECT COUNT(*) AS count FROM judge_batch_items WHERE batch_id=? AND status!='cancelled'",
                   (batch["id"],))["count"] == 0
