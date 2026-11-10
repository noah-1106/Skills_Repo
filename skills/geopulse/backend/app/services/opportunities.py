"""Evidence-backed opportunity review and seven-step action tracking."""
from __future__ import annotations

from fastapi import HTTPException

from ..db import dumps, loads, one, utc_now
from ..engine.metrics import DEPTH_RANK
from ..security import audit
from .measurement import load_run_samples
from .state import transition


def generate_opportunities(conn, wave: dict, actor: int) -> list[dict]:
    if not wave["official_run_id"]:
        raise HTTPException(409, "请先由管理员指定正式 run")
    run = one(conn, "SELECT * FROM runs WHERE id=? AND wave_id=?", (wave["official_run_id"], wave["id"]))
    samples, context = load_run_samples(conn, run)
    primary_id = context["primary_id"]
    by_prompt = {}
    for sample in samples:
        if sample["status"] != "succeeded":
            continue
        by_prompt.setdefault(sample["prompt_item_id"], []).append(sample)
    created = []
    for prompt_id, answers in by_prompt.items():
        primary_observations = []
        competitors = {}
        evidence = []
        wrong_entity = False
        for sample in answers:
            for observation in sample["observations"]:
                if int(observation["brand_entity_id"]) == int(primary_id):
                    primary_observations.append(observation)
                    wrong_entity = wrong_entity or observation["entity_status"] == "wrong_entity"
                elif observation.get("role") == "competitor" and observation["entity_status"] == "confirmed" and observation["mentioned"]:
                    competitors[observation["name"]] = observation
                    if observation.get("evidence"):
                        evidence.append({"answer_id": sample["id"], "brand": observation["name"],
                                         "depth": observation["depth"], "evidence": observation["evidence"]})
        primary_best = max((DEPTH_RANK.get(obs["depth"], 0) for obs in primary_observations
                            if obs["entity_status"] == "confirmed" and obs["mentioned"]), default=0)
        competitor_best = max((DEPTH_RANK.get(obs["depth"], 0) for obs in competitors.values()), default=0)
        negative = any(obs["entity_status"] == "confirmed" and obs["mentioned"] and obs["sentiment"] == "negative"
                       for obs in primary_observations)
        if not (wrong_entity or negative or competitor_best > primary_best):
            continue
        gap = "实体歧义" if wrong_entity else "被贬" if negative else "缺席" if primary_best == 0 else "深度落后"
        payload = {"primary": primary_observations[:10], "competitors": list(competitors.values()),
                   "evidence": evidence[:20], "answer_ids": [sample["id"] for sample in answers]}
        now = utc_now()
        conn.execute("INSERT INTO opportunities(client_id,project_id,wave_id,prompt_item_id,evidence_json,gap_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(wave_id,prompt_item_id) DO UPDATE SET evidence_json=excluded.evidence_json,gap_type=excluded.gap_type,updated_at=excluded.updated_at WHERE opportunities.status IN ('candidate','eligibility_pending')",
                     (wave["client_id"], wave["project_id"], wave["id"], prompt_id, dumps(payload), gap, now, now))
        row = one(conn, "SELECT * FROM opportunities WHERE wave_id=? AND prompt_item_id=?", (wave["id"], prompt_id))
        created.append(row)
    audit(conn, actor, wave, "wave", wave["id"], "generate_opportunities", None, {"count": len(created)})
    return created


def review_opportunity(conn, opportunity: dict, actor: int, payload: dict, project: dict) -> dict:
    decision = payload["decision"]
    if decision == "eligibility_pending":
        if opportunity["status"] == "candidate":
            opportunity = transition(conn, "opportunities", opportunity, "eligibility_pending", actor)
        return opportunity
    if opportunity["status"] == "candidate":
        opportunity = transition(conn, "opportunities", opportunity, "eligibility_pending", actor)
    if opportunity["status"] != "eligibility_pending":
        raise HTTPException(409, "当前状态不能进行适用性审核")
    if decision == "rejected":
        conn.execute("UPDATE opportunities SET eligibility='not_eligible',score=NULL WHERE id=?", (opportunity["id"],))
        return transition(conn, "opportunities", opportunity, "rejected", actor, payload.get("reason") or "不适用")
    if decision != "confirmed":
        raise HTTPException(400, "无效审核决定")
    eligibility = payload.get("eligibility") or "client_confirmed"
    if eligibility not in ("eligible", "client_confirmed"):
        raise HTTPException(400, "确认机会前必须明确 eligible 或 client_confirmed")
    business = float(payload.get("business_value", 3))
    executable = float(payload.get("executability", 3))
    if not 1 <= business <= 5 or not 1 <= executable <= 5:
        raise HTTPException(400, "商业价值和可执行性必须为 1–5")
    evidence = loads(opportunity["evidence_json"], {})
    answer_ids = evidence.get("answer_ids") or []
    competitive = {"缺席": 1.0, "深度落后": 0.7, "被贬": 0.9, "实体歧义": 0.85}.get(opportunity["gap_type"], 0.5)
    reliability = min(1.0, len(answer_ids) / 3) * (1.0 if evidence.get("evidence") else 0.4)
    factors = {"business_value": business / 5, "eligibility_confidence": 1.0 if eligibility == "client_confirmed" else 0.8,
               "competitive_gap": competitive, "evidence_reliability": reliability,
               "executability": executable / 5}
    wave = one(conn, "SELECT stats_json FROM waves WHERE id=? AND project_id=?",
               (opportunity["wave_id"], project["id"]))
    weights = ((loads(wave["stats_json"], {}) if wave else {}).get("score_weights")
               or loads(project["settings_json"], {}).get("score_weights") or {})
    weighted = [(factors[key], float(weights.get(key, 1))) for key in factors]
    total_weight = sum(weight for _, weight in weighted)
    if total_weight <= 0:
        raise HTTPException(400, "Wave 冻结的评分权重总和必须大于 0")
    score = 100 * __import__("math").prod(max(0.0001, value) ** (weight / total_weight) for value, weight in weighted)
    conn.execute("UPDATE opportunities SET eligibility=?,score=?,score_json=? WHERE id=?",
                 (eligibility, round(score, 2), dumps({"factors": factors, "weights": weights,
                                                       "reason": payload.get("reason") or ""}), opportunity["id"]))
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (opportunity["id"],))
    return transition(conn, "opportunities", opportunity, "confirmed", actor, payload.get("reason") or "")


def create_action(conn, opportunity: dict, actor: int, payload: dict) -> dict:
    if opportunity["status"] != "confirmed" or opportunity["eligibility"] not in ("eligible", "client_confirmed"):
        raise HTTPException(409, "只有已确认适用的机会可以生成 Action")
    default_step = {"实体歧义": 7, "缺席": 3, "深度落后": 6, "被贬": 2}.get(opportunity["gap_type"], 3)
    step = int(payload.get("geo_step") or default_step)
    if not 1 <= step <= 7:
        raise HTTPException(400, "geo_step 必须为 1–7")
    target_wave_id = payload.get("target_wave_id")
    if target_wave_id:
        target = one(conn, "SELECT id FROM waves WHERE id=? AND project_id=? AND client_id=?",
                     (target_wave_id, opportunity["project_id"], opportunity["client_id"]))
        if not target:
            raise HTTPException(404, "目标 Wave 不存在或不属于当前项目")
    now = utc_now()
    action_id = conn.execute(
        "INSERT INTO actions(client_id,project_id,opportunity_id,geo_step,title,owner,reviewer,"
        "target_url,artifact_version,target_wave_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (opportunity["client_id"], opportunity["project_id"], opportunity["id"], step,
         payload["title"].strip(), payload.get("owner") or "", payload.get("reviewer") or "",
         payload.get("target_url") or "", payload.get("artifact_version") or "v1", target_wave_id, now, now)
    ).lastrowid
    row = one(conn, "SELECT * FROM actions WHERE id=?", (action_id,))
    from .interventions import initialize_action
    initialize_action(conn, row, actor)
    transition(conn, "opportunities", opportunity, "actioned", actor)
    audit(conn, actor, opportunity, "action", action_id, "create", None, row)
    return row


def transition_action(conn, action: dict, new_status: str, actor: int, payload: dict) -> dict:
    from . import interventions, remeasurements

    if new_status == "review":
        interventions.validate_action_package(conn, action)
    elif new_status == "approved":
        interventions.approve_action_package(conn, action, actor)
    elif new_status == "published":
        interventions.publish_legacy(conn, action, actor, payload)
        return one(conn, "SELECT * FROM actions WHERE id=?", (action["id"],))
    elif new_status == "remeasure_due":
        target_wave_id = payload.get("target_wave_id") or action.get("target_wave_id")
        if not target_wave_id:
            raise HTTPException(400, "进入复测前必须选择目标 wave")
        remeasurements.create_rounds(conn, action, actor, [{
            "target_wave_id": target_wave_id, "offset_days": int(payload.get("remeasure_days") or 14),
        }], allow_baseline=True)
        return one(conn, "SELECT * FROM actions WHERE id=?", (action["id"],))
    elif new_status in ("verified", "not_effective"):
        target_wave_id = payload.get("target_wave_id") or action.get("target_wave_id")
        round_row = one(conn, """SELECT * FROM action_remeasurement_rounds WHERE action_id=? AND target_wave_id=?
            ORDER BY round_no DESC LIMIT 1""", (action["id"], target_wave_id))
        if not round_row:
            raise HTTPException(409, "该目标 Wave 没有对应的 cohort 复测轮次")
        if round_row["status"] == "pending_measurement":
            round_row = remeasurements.assess_round(conn, round_row, actor, payload.get("reason") or "")
        if round_row["status"] != "measured":
            raise HTTPException(409, "该轮证据不足或不可比，不能记录改善/未改善结论")
        expected = "improved" if new_status == "verified" else "not_improved"
        if round_row["observed_change"] != expected:
            message = "同口径正式 Run 未显示对应指标改善；可记录为无效并补充说明" if new_status == "verified" else "该轮已观察到改善，不能记录为未见改善"
            raise HTTPException(409, message)
        after = transition(conn, "actions", action, new_status, actor, payload.get("reason") or "")
        comparison = loads(round_row["comparison_json"], {})
        audit(conn, actor, action, "action", action["id"], "remeasurement_verified", None,
              {"round_id": round_row["id"], "target_wave_id": target_wave_id,
               "official_run_id": round_row["target_run_id"], "delta": comparison.get("delta"),
               "interpretation": comparison.get("interpretation"), "attribution_status": "not_attributable"})
        return after
    return transition(conn, "actions", action, new_status, actor, payload.get("reason") or "")
