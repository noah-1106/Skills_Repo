"""Provider usage pricing, wave estimates and the shared call ledger."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..db import all_rows, dumps, loads, one, utc_now

JUDGE_INPUT_TOKENS = 2500
JUDGE_OUTPUT_TOKENS = 1800


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
        calls = int(usage.get("search_calls") or 1)
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
    signatures = protocol.get("engine_signature") or []
    repeats = int(protocol.get("repeats") or 1)
    retries = int(protocol.get("max_safe_retries") or 0)
    answer_calls = prompts * len(engines or signatures) * repeats
    judge_calls = answer_calls if protocol.get("use_judge") else 0
    search_calls = answer_calls if protocol.get("mode") == "search" else 0
    multiplier = 1 + retries
    by_engine = []
    totals = {"base": 0.0, "max": 0.0}
    currencies = set()
    unknown_components = []
    estimated_input = 0
    estimated_output = 0
    for index, engine in enumerate(engines):
        rule = rule_for(engine)
        signature = signatures[index] if index < len(signatures) else engine
        calls = prompts * repeats
        parts = []
        for scale, key in ((1, "base"), (multiplier, "max")):
            answer_usage = {
                "prompt_tokens": calls * scale * int(rule.get("estimated_input_tokens", 1200)),
                "completion_tokens": calls * scale * int(rule.get("estimated_output_tokens", protocol.get("max_tokens", 700))),
            }
            operations = [("answer", answer_usage)]
            if protocol.get("use_judge"):
                operations.append(("judge", {
                    "prompt_tokens": calls * scale * JUDGE_INPUT_TOKENS,
                    "completion_tokens": calls * scale * JUDGE_OUTPUT_TOKENS,
                }))
            if protocol.get("mode") == "search":
                operations.append(("search", {"search_calls": calls * scale}))
            for operation, usage in operations:
                amount, currency, missing = quote(rule, operation, usage)
                currencies.add(currency)
                if missing:
                    unknown_components.extend(f"{signature.get('name', engine.get('name'))}:{item}" for item in missing)
                else:
                    totals[key] += amount or 0
                parts.append({"operation": operation, "bucket": key, "amount": amount, "currency": currency, "missing": missing})
        base_parts = [part for part in parts if part["bucket"] == "base"]
        max_parts = [part for part in parts if part["bucket"] == "max"]
        by_engine.append({
            "engine": signature.get("name", engine.get("name")),
            "estimated_cost": round(sum(part["amount"] for part in base_parts if part["amount"] is not None), 6)
                if all(part["amount"] is not None for part in base_parts) else None,
            "max_estimated_cost": round(sum(part["amount"] for part in max_parts if part["amount"] is not None), 6)
                if all(part["amount"] is not None for part in max_parts) else None,
            "known_cost": round(sum(part["amount"] or 0 for part in base_parts), 6),
            "currency": rule_for(engine).get("currency", "CNY"),
            "unknown_components": sorted({item for part in parts for item in part["missing"]}),
        })
        estimated_input += calls * int(rule.get("estimated_input_tokens", 1200))
        estimated_output += calls * int(rule.get("estimated_output_tokens", protocol.get("max_tokens", 700)))
        if protocol.get("use_judge"):
            estimated_input += calls * JUDGE_INPUT_TOKENS
            estimated_output += calls * JUDGE_OUTPUT_TOKENS
    complete = not unknown_components and len(currencies) <= 1
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return {
        "prompt_items": prompts,
        "engines": len(engines or signatures),
        "repeats": repeats,
        "answer_calls": answer_calls,
        "judge_calls": judge_calls,
        "search_calls": search_calls,
        "total_external_calls": answer_calls + judge_calls + search_calls,
        "max_external_calls": (answer_calls + judge_calls + search_calls) * multiplier,
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "max_estimated_input_tokens": estimated_input * multiplier,
        "max_estimated_output_tokens": estimated_output * multiplier,
        "estimated_cost": round(totals["base"], 6) if complete else None,
        "max_estimated_cost": round(totals["max"], 6) if complete else None,
        "known_cost": round(totals["base"], 6),
        "currency": currency,
        "cost_unknown": bool(unknown_components),
        "unknown_components": sorted(set(unknown_components)),
        "mixed_currencies": len(currencies) > 1,
        "by_engine": by_engine,
        "blocking": False,
        "note": "调用次数区分基础预估与安全重试上限；token 和金额为启发式预估，不是厂商账单或绝对费用上限。",
    }


def record_attempt(conn, *, project: dict, engine: dict, operation: dict,
                   answer: dict | None = None, group: str | None = None) -> int:
    billing_operation = operation.get("operation") or operation["kind"]
    kind = group or operation["kind"]
    rule = rule_for(engine)
    usage = operation.get("usage") or {}
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
            request_id,model,latency_ms,usage_json,cost,currency,cost_rule_json,error_type,error_detail,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            answer_id,
            (answer or project)["client_id"], (answer or project)["project_id"] if answer else project["id"],
            (answer or {}).get("run_id"), engine.get("id"), kind, billing_operation, attempt_no,
            operation.get("status") or "failed", operation.get("request_id"), operation.get("model"),
            operation.get("latency_ms"), dumps(usage), cost, currency, dumps(rule),
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
