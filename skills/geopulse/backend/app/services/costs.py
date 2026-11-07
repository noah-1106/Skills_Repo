"""Provider usage pricing, wave estimates and the shared call ledger."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..db import all_rows, dumps, loads, one, utc_now
from .execution import answer_execution_for, judge_execution_for

JUDGE_INPUT_TOKENS = 2500


def rule_for(engine: dict) -> dict:
    if "cost_rule" in engine:
        rule = dict(engine.get("cost_rule") or {})
    else:
        rule = loads(engine.get("cost_rule_json"), {})
    if engine.get("kind") == "demo":
        return {"free": True, "currency": rule.get("currency", "CNY")}
    rule["currency"] = str(rule.get("currency") or "CNY").upper()
    return rule


def quote(rule: dict, operation: str, usage: dict) -> tuple[float | None, str, list[str]]:
    """Return known amount, currency and missing price/usage components."""
    currency = str(rule.get("currency") or "CNY").upper()
    if rule.get("free"):
        return 0.0, currency, []
    missing = []
    if operation == "search":
        if "search_per_call" not in rule:
            missing.append("search_per_call")
        calls = int(usage["search_calls"]) if "search_calls" in usage else 1
        if calls == 0:
            return 0.0, currency, []
        if missing:
            return None, currency, missing
        return float(rule["search_per_call"]) * calls, currency, []
    if "prompt_tokens" not in usage and "completion_tokens" not in usage:
        missing.append("usage")
    input_rate = rule.get("input_per_million")
    output_rate = rule.get("output_per_million")
    if operation == "judge":
        input_rate = rule.get("judge_input_per_million", input_rate)
        output_rate = rule.get("judge_output_per_million", output_rate)
    if input_rate is None:
        missing.append(f"{operation}_input_per_million")
    if output_rate is None:
        missing.append(f"{operation}_output_per_million")
    if missing:
        return None, currency, missing
    amount = (
        int(usage.get("prompt_tokens") or 0) / 1_000_000 * float(input_rate)
        + int(usage.get("completion_tokens") or 0) / 1_000_000 * float(output_rate)
    )
    return amount, currency, []


def frozen_engines(conn, wave: dict) -> list[dict]:
    engines = loads(wave.get("engine_snapshot_json"), [])
    if engines:
        return engines
    protocol = loads(wave["protocol_json"], {})
    ids = protocol.get("engine_ids") or []
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = all_rows(conn, f"SELECT * FROM engine_configs WHERE id IN ({marks})", ids)
    return [{**row, "cost_rule": rule_for(row)} for row in rows]


def estimate_wave(conn, wave: dict) -> dict:
    protocol = loads(wave["protocol_json"], {})
    prompts = len(protocol.get("prompt_item_ids") or [])
    engines = frozen_engines(conn, wave)
    signatures = {int(item["id"]): item for item in protocol.get("engine_signature") or []}
    manual_web = protocol.get("measurement_target") == "consumer_web"
    repeats = int(protocol.get("repeats") or 1)
    retries = int(protocol.get("max_safe_retries") or 0)
    multiplier = 1 + retries
    collection_tasks = prompts * repeats if manual_web else 0
    answer_calls = 0 if manual_web else prompts * len(engines) * repeats
    judge_calls = (collection_tasks if manual_web else answer_calls) if protocol.get("use_judge") else 0
    search_calls = answer_calls if not manual_web and protocol.get("mode") == "search" else 0
    independent = loads(wave.get("judge_snapshot_json"), {}) or None
    entries = []
    if not manual_web:
        for engine in engines:
            engine_id = int(engine["id"])
            answer = answer_execution_for(protocol, engine_id)
            operations = [("answer", answer, "answer")]
            if protocol.get("mode") == "search":
                operations.append(("search", {}, "search"))
            if protocol.get("use_judge") and not independent:
                operations.append(("judge", judge_execution_for(protocol, engine_id), "judge"))
            entries.append((engine, signatures.get(engine_id, engine), prompts * repeats, operations))
    if protocol.get("use_judge") and independent:
        engine_ids = protocol.get("engine_ids") or []
        execution = judge_execution_for(protocol, int(engine_ids[0])) if engine_ids else {}
        entries.append((independent, protocol.get("judge_signature") or independent,
                        collection_tasks if manual_web else answer_calls, [("judge", execution, "judge")]))
    unknown_components = []
    if protocol.get("use_judge") and protocol.get("judge_signature") and not independent:
        unknown_components.append("judge:execution_snapshot")
    by_engine = []
    totals = {"base": 0.0, "max": 0.0}
    currencies = set()
    estimated_input = 0
    estimated_output = 0
    for engine, signature, calls, operations in entries:
        rule = rule_for(engine)
        parts = []
        for scale, bucket in ((1, "base"), (multiplier, "max")):
            for operation, execution, role in operations:
                if operation == "search":
                    usage = {"search_calls": calls * scale}
                else:
                    default_output = 1800 if role == "judge" else 700
                    usage = {
                        "prompt_tokens": calls * scale * (JUDGE_INPUT_TOKENS if role == "judge" else int(rule.get("estimated_input_tokens", 1200))),
                        "completion_tokens": calls * scale * int(execution.get("max_tokens") or rule.get("estimated_output_tokens") or default_output),
                    }
                    if scale == 1:
                        estimated_input += usage["prompt_tokens"]
                        estimated_output += usage["completion_tokens"]
                amount, currency, missing = quote(rule, operation, usage)
                currencies.add(currency)
                if missing:
                    unknown_components.extend(f"{signature.get('name', engine.get('name'))}:{item}" for item in missing)
                else:
                    totals[bucket] += amount or 0
                parts.append({"operation": operation, "bucket": bucket, "amount": amount,
                              "currency": currency, "missing": missing})
        base_parts = [part for part in parts if part["bucket"] == "base"]
        max_parts = [part for part in parts if part["bucket"] == "max"]
        by_engine.append({
            "engine": signature.get("name", engine.get("name")),
            "role": "judge" if operations[0][0] == "judge" else "answer",
            "estimated_cost": round(sum(part["amount"] for part in base_parts if part["amount"] is not None), 6)
                if all(part["amount"] is not None for part in base_parts) else None,
            "max_estimated_cost": round(sum(part["amount"] for part in max_parts if part["amount"] is not None), 6)
                if all(part["amount"] is not None for part in max_parts) else None,
            "known_cost": round(sum(part["amount"] or 0 for part in base_parts), 6),
            "currency": rule.get("currency", "CNY"),
            "unknown_components": sorted({item for part in parts for item in part["missing"]}),
        })
    complete = not unknown_components and len(currencies) <= 1
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return {
        "prompt_items": prompts, "engines": len(engines), "repeats": repeats,
        "collection_tasks": collection_tasks, "answer_calls": answer_calls,
        "judge_calls": judge_calls, "search_calls": search_calls,
        "total_external_calls": answer_calls + judge_calls + search_calls,
        "max_external_calls": (answer_calls + judge_calls + search_calls) * multiplier,
        "estimated_input_tokens": estimated_input, "estimated_output_tokens": estimated_output,
        "max_estimated_input_tokens": estimated_input * multiplier,
        "max_estimated_output_tokens": estimated_output * multiplier,
        "estimated_cost": round(totals["base"], 6) if complete else None,
        "max_estimated_cost": round(totals["max"], 6) if complete else None,
        "known_cost": round(totals["base"], 6), "currency": currency,
        "cost_unknown": bool(unknown_components), "unknown_components": sorted(set(unknown_components)),
        "mixed_currencies": len(currencies) > 1, "by_engine": by_engine, "blocking": False,
        "note": ("人工采集不产生 Provider 回答或 Search 调用；仅独立 Judge 计入外部调用与费用。token 和金额为启发式预估，不是厂商账单。"
                 if manual_web else "回答、Search 与 Judge 分引擎预估；调用次数区分基础与安全重试上限，金额不是厂商账单或绝对费用上限。"),
    }


def record_attempt(conn, *, project: dict, engine: dict, operation: dict,
                   answer: dict | None = None, group: str | None = None) -> int:
    billing_operation = operation.get("operation") or operation["kind"]
    kind = group or operation["kind"]
    rule = rule_for(engine)
    usage = operation.get("usage") or {}
    if operation.get("billable") is False:
        cost, currency = 0.0, str(rule.get("currency") or "CNY").upper()
    else:
        cost, currency, _ = quote(rule, billing_operation, usage)
    answer_id = answer.get("id") if answer else None
    if answer_id:
        attempt_no = operation.get("attempt_no")
        if not attempt_no:
            row = one(conn, "SELECT MAX(attempt_no) AS value FROM call_attempts WHERE answer_id=? AND kind=?",
                      (answer_id, kind))
            attempt_no = int(row["value"] or 0) + 1
    else:
        attempt_no = int(operation.get("attempt_no") or 1)
    cursor = conn.execute(
        """INSERT OR IGNORE INTO call_attempts(
            answer_id,client_id,project_id,run_id,engine_config_id,kind,operation,attempt_no,status,
            request_id,model,latency_ms,usage_json,request_params_json,response_meta_json,cost,currency,cost_rule_json,error_type,error_detail,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            answer_id,
            (answer or project)["client_id"], (answer or project)["project_id"] if answer else project["id"],
            (answer or {}).get("run_id"), engine.get("id"), kind, billing_operation, attempt_no,
            operation.get("status") or "failed", operation.get("request_id"), operation.get("model"),
            operation.get("latency_ms"), dumps(usage), dumps(operation.get("request_params") or {}),
            dumps(operation.get("response_meta") or {}), cost, currency, dumps(rule),
            operation.get("error_type"), str(operation.get("error_detail") or "")[:1000] or None,
            operation.get("created_at") or utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def summarize_costs(conn, project_id: int, run_ids: list[int] | None = None) -> dict:
    args: list[Any] = [project_id]
    condition = "project_id=?"
    if run_ids is not None:
        if not run_ids:
            return {"items": [], "by_currency": {}, "unknown": False, "tokens": {}}
        marks = ",".join("?" for _ in run_ids)
        condition += f" AND run_id IN ({marks})"
        args.extend(run_ids)
    rows = all_rows(conn, f"""SELECT kind,operation,currency,COUNT(*) AS calls,SUM(cost) AS cost,
        SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown,
        SUM(CASE WHEN attempt_no>1 THEN 1 ELSE 0 END) AS retry_calls,
        SUM(CASE WHEN attempt_no>1 THEN cost ELSE 0 END) AS retry_cost
        FROM call_attempts WHERE {condition} GROUP BY kind,operation,currency ORDER BY kind,operation,currency""", args)
    by_currency: dict[str, dict] = defaultdict(lambda: {"known_cost": 0.0, "unknown": 0, "calls": 0})
    tokens: dict[str, dict] = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    usage_rows = all_rows(conn, f"SELECT kind,usage_json FROM call_attempts WHERE {condition}", args)
    for row in usage_rows:
        usage = loads(row["usage_json"], {})
        for key in ("prompt_tokens", "completion_tokens"):
            tokens[row["kind"]][key] += int(usage.get(key) or 0)
    for row in rows:
        currency = row["currency"] or "历史未标币种"
        row["known_cost"] = row.pop("cost")
        by_currency[currency]["known_cost"] += row["known_cost"] or 0
        by_currency[currency]["unknown"] += row["unknown"] or 0
        by_currency[currency]["calls"] += row["calls"]
    for value in by_currency.values():
        value["known_cost"] = round(value["known_cost"], 6)
    return {"items": rows, "by_currency": dict(by_currency),
            "unknown": any(row["unknown"] for row in rows), "tokens": dict(tokens)}
