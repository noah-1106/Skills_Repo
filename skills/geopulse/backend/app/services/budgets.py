"""Transactional pre-execution budget checks and in-flight reservations."""
from __future__ import annotations

import copy
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .. import config
from ..db import all_rows, dumps, loads, one, utc_now
from .costs import quote, rule_for
from .execution import resolve_execution


def project_day(project: dict) -> tuple[str, str, str]:
    zone = ZoneInfo(project.get("timezone") or "Asia/Shanghai")
    now = datetime.now(zone)
    start = datetime.combine(now.date(), time.min, zone)
    end = start + timedelta(days=1)
    return (now.date().isoformat(), start.astimezone(timezone.utc).isoformat(timespec="seconds"),
            end.astimezone(timezone.utc).isoformat(timespec="seconds"))


def scale_estimate(estimate: dict, factor: float) -> dict:
    result = copy.deepcopy(estimate)
    for key in ("answer_calls", "judge_calls", "search_calls", "collection_tasks", "total_external_calls", "max_external_calls",
                "estimated_input_tokens", "estimated_output_tokens", "max_estimated_input_tokens",
                "max_estimated_output_tokens"):
        if key in result:
            result[key] = int(result[key] * factor)
    for key in ("estimated_cost", "max_estimated_cost", "known_cost"):
        if result.get(key) is not None:
            result[key] = result[key] * factor
    return result


def estimate_health(engine: dict) -> dict:
    rule = rule_for(engine)
    health = resolve_execution(engine, "health")
    output_tokens = health.get("max_tokens") or rule.get("estimated_output_tokens") or 700
    operations = [("answer", {"prompt_tokens": 40, "completion_tokens": output_tokens})]
    if engine.get("mode") == "search":
        operations.insert(0, ("search", {"search_calls": 1}))
    total = 0.0
    unknown = []
    currencies = set()
    for operation, usage in operations:
        amount, currency, missing = quote(rule, operation, usage)
        currencies.add(currency)
        unknown.extend(f"{engine.get('name', engine.get('id'))}:{item}" for item in missing)
        total += amount or 0
    complete = not unknown and len(currencies) == 1
    return {"estimated_cost": round(total, 6) if complete else None,
            "max_estimated_cost": round(total, 6) if complete else None,
            "known_cost": round(total, 6), "currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "cost_unknown": bool(unknown), "unknown_components": sorted(set(unknown)),
            "mixed_currencies": len(currencies) > 1, "total_external_calls": len(operations),
            "max_external_calls": len(operations)}


def _usage(conn, project: dict, scope: str, currency: str, wave_id: int | None,
           day_range: tuple[str, str] | None, exclude_run_id: int | None) -> dict:
    actual_clauses, actual_args = ["project_id=?"], [project["id"]]
    reservation_clauses, reservation_args = ["project_id=?", "status='active'"], [project["id"]]
    if scope == "wave":
        actual_clauses.append("run_id IN (SELECT id FROM runs WHERE wave_id=?)")
        actual_args.append(wave_id)
        reservation_clauses.append("wave_id=?")
        reservation_args.append(wave_id)
    elif scope == "daily":
        actual_clauses.extend(("created_at>=?", "created_at<?"))
        actual_args.extend(day_range[1:])
        reservation_clauses.append("budget_date=?")
        reservation_args.append(day_range[0])
    if exclude_run_id:
        reservation_clauses.append("(run_id IS NULL OR run_id!=?)")
        reservation_args.append(exclude_run_id)
    actual = all_rows(conn, f"SELECT currency,SUM(cost) AS known,SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown FROM call_attempts WHERE {' AND '.join(actual_clauses)} GROUP BY currency", actual_args)
    reserved = one(conn, f"SELECT COALESCE(SUM(amount),0) AS amount FROM budget_reservations WHERE {' AND '.join(reservation_clauses)} AND currency=?", [*reservation_args, currency])
    other_currency = any((row["known"] or 0) != 0 and (row["currency"] or "") != currency for row in actual)
    unknown = sum(int(row["unknown"] or 0) for row in actual)
    known = next((float(row["known"] or 0) for row in actual if (row["currency"] or "") == currency), 0.0)
    return {"actual": round(known, 6), "reserved": round(float(reserved["amount"]), 6),
            "used": round(known + float(reserved["amount"]), 6), "unknown_costs": unknown,
            "mixed_currencies": other_currency}


def _alert(conn, project: dict, kind: str, message: str, dedupe_key: str) -> None:
    existing = one(conn, "SELECT id FROM alerts WHERE project_id=? AND dedupe_key=? AND status='open'",
                   (project["id"], dedupe_key))
    if existing:
        conn.execute("UPDATE alerts SET message=?,updated_at=? WHERE id=?", (message, utc_now(), existing["id"]))
        return
    conn.execute("INSERT INTO alerts(client_id,project_id,kind,severity,message,dedupe_key,created_at,updated_at) VALUES(?,?,?,'warning',?,?,?,?)",
                 (project["client_id"], project["id"], kind, message, dedupe_key, utc_now(), utc_now()))


def authorize_budget(conn, project: dict, estimate: dict, *, wave: dict | None = None,
                     actor: int | None = None, confirmation_reason: str = "",
                     exclude_run_id: int | None = None) -> dict:
    settings = {**config.DEFAULT_PROJECT_SETTINGS, **loads(project.get("settings_json"), {})}
    budget = {**config.DEFAULT_PROJECT_SETTINGS["budget"], **(settings.get("budget") or {})}
    decision = {"enabled": bool(budget.get("enabled")), "hard_limit": bool(budget.get("hard_limit")),
                "currency": str(budget.get("currency") or "CNY").upper(), "estimate": estimate,
                "override_reason": "", "limits": []}
    if not decision["enabled"]:
        return decision
    currency = decision["currency"]
    date, start, end = project_day(project)
    wave_budget = budget
    if wave:
        wave_settings = loads(wave.get("stats_json"), {})
        wave_budget = {**budget, **(wave_settings.get("budget") or {})}
    limits = [("project", "项目累计额度", budget.get("amount"), None),
              ("daily", "每日额度", budget.get("daily_amount"), (date, start, end))]
    if wave:
        limits.append(("wave", "Wave 冻结额度", wave_budget.get("wave_amount"), None))
    unknown_estimate = bool(estimate.get("cost_unknown") or estimate.get("mixed_currencies")
                            or estimate.get("max_estimated_cost") is None or estimate.get("currency") != currency)
    unknown_reasons = list(estimate.get("unknown_components") or [])
    if estimate.get("currency") != currency:
        unknown_reasons.append(f"预估币种 {estimate.get('currency') or '混合/未知'} 与预算币种 {currency} 不一致")
    for scope, label, amount, day_range in limits:
        if amount is None:
            continue
        usage = _usage(conn, project, scope, currency, wave.get("id") if wave else None,
                       day_range, exclude_run_id)
        item = {"scope": scope, "label": label, "limit": float(amount), **usage}
        item["projected"] = (round(usage["used"] + float(estimate["max_estimated_cost"]), 6)
                             if not unknown_estimate else None)
        item["exceeded"] = item["projected"] is not None and item["projected"] > float(amount) + 1e-9
        if usage["unknown_costs"]:
            unknown_reasons.append(f"{label}有 {usage['unknown_costs']} 笔未知历史成本")
        if usage["mixed_currencies"]:
            unknown_reasons.append(f"{label}包含其他币种历史成本")
        decision["limits"].append(item)
    unknown_reasons = sorted(set(unknown_reasons))
    has_limit = bool(decision["limits"])
    exceeded = [item for item in decision["limits"] if item["exceeded"]]
    decision.update({"budget_date": date, "unknown_reasons": unknown_reasons,
                     "requires_confirmation": bool(exceeded) and not decision["hard_limit"]})
    if decision["hard_limit"] and has_limit and (unknown_estimate or any(
            item["unknown_costs"] or item["mixed_currencies"] for item in decision["limits"])):
        raise HTTPException(409, detail={"code": "budget_cost_unknown", "message": "硬限额下无法确认完整成本，请补齐价格规则和历史台账后再执行", **decision})
    if exceeded and decision["hard_limit"]:
        raise HTTPException(409, detail={"code": "budget_exceeded", "message": "本次执行会超过硬预算，未创建调用", **decision})
    if exceeded and not confirmation_reason.strip():
        raise HTTPException(409, detail={"code": "budget_confirmation_required",
                                        "message": "本次执行会超过软预算，需要管理员填写本次确认理由", **decision})
    if exceeded:
        if actor is None:
            raise HTTPException(409, detail={"code": "budget_confirmation_required",
                                            "message": "自动调度不能代替管理员确认软预算超限", **decision})
        if len(confirmation_reason.strip()) < 4:
            raise HTTPException(400, detail={"code": "budget_confirmation_required", "message": "预算确认理由至少 4 个字符", **decision})
        decision["override_reason"] = confirmation_reason.strip()
    if unknown_reasons and not exceeded:
        _alert(conn, project, "budget_cost_unknown", "存在未知价格或币种，成本看板不会将未知金额按零计算", f"budget-unknown:{project['id']}")
    return decision


def reserve(conn, project: dict, decision: dict, *, wave: dict | None = None, run_id: int | None = None,
            operation_id: str | None = None, actor: int | None = None) -> int | None:
    if not decision.get("enabled"):
        return None
    estimate = decision["estimate"]
    amount = float(estimate.get("max_estimated_cost") or 0)
    return int(conn.execute("INSERT INTO budget_reservations(client_id,project_id,wave_id,run_id,operation_id,amount,currency,estimate_json,budget_date,confirmed_reason,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (project["client_id"], project["id"], wave.get("id") if wave else None, run_id,
                             operation_id, amount, decision["currency"], dumps(estimate), decision["budget_date"],
                             decision.get("override_reason") or "", actor, utc_now())).lastrowid)


def release(*, run_id: int | None = None, operation_id: str | None = None, conn=None) -> None:
    if run_id is None and operation_id is None:
        return
    clause, value = ("run_id=?", run_id) if run_id is not None else ("operation_id=?", operation_id)
    conn.execute(f"UPDATE budget_reservations SET status='released',released_at=? WHERE {clause} AND status='active'",
                 (utc_now(), value))
