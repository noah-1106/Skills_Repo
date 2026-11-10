"""Read-only pre-run checks derived from frozen protocol and observed history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..db import all_rows, loads, one
from .costs import estimate_wave, frozen_engines
from .execution import answer_execution_for, capabilities_for, judge_execution_for


def _health(conn, engines: list[dict]) -> list[dict]:
    result = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for engine in engines:
        current = one(conn, "SELECT health_status FROM engine_configs WHERE id=?", (engine["id"],)) or {}
        status, _, detail = str(current.get("health_status") or "unknown").partition(":")
        latest = one(conn, """SELECT created_at FROM call_attempts
            WHERE engine_config_id=? AND kind='health' ORDER BY id DESC LIMIT 1""", (engine["id"],))
        stale = True
        if latest:
            try:
                stale = datetime.fromisoformat(latest["created_at"]) < cutoff
            except ValueError:
                pass
        result.append({"engine_id": engine["id"], "name": engine.get("name"), "status": status or "unknown",
                       "last_checked_at": latest["created_at"] if latest else None,
                       "stale": stale, "detail": detail if status == "unhealthy" else "",
                       "note": "仅为历史探测，不代替本次冻结参数校验；打开准备单不会发起健康检查。"})
    return result


def _latency(conn, engine_id: int, kind: str) -> list[float]:
    rows = all_rows(conn, """SELECT latency_ms FROM call_attempts
        WHERE engine_config_id=? AND kind=? AND operation=? AND status='succeeded' AND latency_ms IS NOT NULL
        ORDER BY id DESC LIMIT 50""", (engine_id, kind, "search" if kind == "search" else "answer" if kind == "answer" else "judge"))
    return sorted(float(row["latency_ms"]) for row in rows)


def _duration(conn, wave: dict, protocol: dict, engines: list[dict]) -> dict:
    if protocol.get("measurement_target") == "consumer_web":
        return {"status": "unknown", "reason": "人工/浏览器采集时长取决于人工处理与网页状态，不承诺固定分钟数。"}
    if all(engine["kind"] == "demo" for engine in engines):
        return {"status": "not_applicable", "reason": "离线 Demo 不用于预估真实模型耗时。"}
    prompts = len(protocol.get("prompt_item_ids") or [])
    repeats = int(protocol.get("repeats") or 1)
    per_engine = []
    samples = 0
    independent = loads(wave.get("judge_snapshot_json"), {}) or None
    for engine in engines:
        calls = {"answer": prompts * repeats, "search": prompts * repeats if protocol.get("mode") == "search" else 0,
                 "judge": prompts * repeats if protocol.get("use_judge") and not independent else 0}
        low = high = 0.0
        for kind, count in calls.items():
            if not count:
                continue
            observed = _latency(conn, int(engine["id"]), kind)
            if len(observed) < 3:
                return {"status": "unknown", "reason": f"引擎 {engine.get('name')} 的 {kind} 历史成功样本不足 3 条。",
                        "samples": len(observed)}
            samples += len(observed)
            median = observed[len(observed) // 2]
            p90 = observed[min(len(observed) - 1, int(len(observed) * 0.9))]
            low += median * count
            high += p90 * count
        per_engine.append((low, high))
    if independent and protocol.get("use_judge"):
        observed = _latency(conn, int(independent["id"]), "judge")
        if len(observed) < 3:
            return {"status": "unknown", "reason": "独立 Judge 历史成功样本不足 3 条。", "samples": len(observed)}
        count = prompts * repeats * len(engines)
        samples += len(observed)
        per_engine.append((observed[len(observed) // 2] * count,
                           observed[min(len(observed) - 1, int(len(observed) * 0.9))] * count))
    return {"status": "estimated", "min_seconds": round(max(item[0] for item in per_engine) / 1000, 1),
            "max_seconds": round(max(item[1] for item in per_engine) / 1000, 1), "samples": samples,
            "note": "按各引擎历史延迟中位数/P90与逐引擎串行估算，不含排队、网页人工处理或新增限流；不是时长承诺。"}


def wave_readiness(conn, wave: dict) -> dict:
    protocol = loads(wave["protocol_json"], {})
    engines = frozen_engines(conn, wave)
    judge = loads(wave.get("judge_snapshot_json"), {}) or None
    checked = [*engines, *([judge] if judge else [])]
    health = _health(conn, checked)
    risks = []
    for engine in engines:
        execution = answer_execution_for(protocol, int(engine["id"]))
        capabilities = capabilities_for(engine)
        truncated = one(conn, """SELECT COUNT(*) AS count FROM call_attempts
            WHERE engine_config_id=? AND kind='answer' AND error_type='truncated_answer'""", (engine["id"],))["count"]
        context = capabilities.get("context_window")
        prompt_rows = all_rows(conn,
            f"SELECT text FROM prompt_items WHERE id IN ({','.join('?' * len(protocol.get('prompt_item_ids') or []))})",
            protocol.get("prompt_item_ids") or []) if protocol.get("prompt_item_ids") else []
        max_prompt_chars = max((len(item["text"]) for item in prompt_rows), default=0)
        estimated_prompt_tokens = max_prompt_chars // 2 + 200
        near_context = bool(context and execution.get("max_tokens") is not None
                            and estimated_prompt_tokens + int(execution["max_tokens"]) > int(context))
        if truncated or near_context:
            risks.append({"engine_id": engine["id"], "name": engine.get("name"),
                          "historical_truncated_calls": truncated, "context_window": context,
                          "max_tokens": execution.get("max_tokens"),
                          "reason": "历史出现截断" if truncated else "冻结输出预算与粗略输入估算接近声明上下文上限"})
    disabled = []
    for engine in checked:
        current = one(conn, "SELECT enabled FROM engine_configs WHERE id=?", (engine["id"],))
        if not current or not current["enabled"]:
            disabled.append(engine.get("name"))
    real = any(engine.get("kind") not in ("demo", "manual_web") for engine in checked)
    judge_confirmation = bool(real and protocol.get("judge_mode") == "disabled")
    warnings = []
    if any(item["status"] == "unhealthy" for item in health):
        warnings.append("存在历史健康检查失败；请先核对配置，准备单不会自动重试付费探测")
    elif any(item["status"] == "unknown" or item["stale"] for item in health):
        warnings.append("健康状态未知或已超过 7 天；本次仍以冻结参数与模型能力校验为准")
    estimate = estimate_wave(conn, wave)
    if estimate.get("cost_unknown"):
        warnings.append("部分价格未知，不会按零成本处理")
    if risks:
        warnings.append("存在历史截断或上下文预算风险")
    return {
        "status": "blocked" if disabled else "ready_with_warnings" if warnings or judge_confirmation else "ready",
        "blocking_reasons": [f"引擎已停用或不存在：{', '.join(disabled)}"] if disabled else [],
        "requires_judge_disabled_confirmation": judge_confirmation,
        "judge": {"mode": protocol.get("judge_mode"),
                  "engine": protocol.get("judge_signature"),
                  "execution": protocol.get("judge_execution")},
        "estimate": estimate, "duration": _duration(conn, wave, protocol, engines),
        "health": health, "truncation_risks": risks, "warnings": warnings,
        "note": "不自动执行健康检查、不发起外部调用；历史耗时、健康和截断只作为准备风险。",
    }
