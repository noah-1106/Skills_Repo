"""Resolve and freeze non-secret model execution parameters."""
from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException

from ..db import loads

DEFAULT_SYSTEM_PROMPT = "客观、准确地回答用户问题。不要为了迎合监测而刻意添加或回避品牌；不确定时明确说明。"
BUILTIN_DEFAULTS = {
    "answer": {"temperature": 0.2, "max_tokens": 700, "system_prompt": DEFAULT_SYSTEM_PROMPT},
    "judge": {"temperature": 0, "max_tokens": 1800, "system_prompt": DEFAULT_SYSTEM_PROMPT},
    "health": {"temperature": 0, "max_tokens": 8, "system_prompt": DEFAULT_SYSTEM_PROMPT},
}
PARAMETER_KEYS = ("temperature", "max_tokens", "system_prompt")


def _invalid(message: str) -> None:
    raise HTTPException(422, detail={"code": "invalid_model_parameters", "message": message})


def capabilities_for(engine: dict) -> dict:
    value = engine.get("capabilities")
    if value is None:
        value = loads(engine.get("capabilities_json"), {})
    return dict(value or {})


def defaults_for(engine: dict, role: str) -> dict:
    value = engine.get(f"{role}_defaults")
    if value is None:
        value = loads(engine.get(f"{role}_defaults_json"), {})
    return dict(value or {})


def validate_capabilities(capabilities: dict) -> None:
    allowed = capabilities.get("allowed_temperatures")
    if allowed is not None and not allowed:
        _invalid("allowed_temperatures 为空时必须使用 null 表示未声明枚举限制")
    for key in ("context_window", "max_output_tokens"):
        value = capabilities.get(key)
        if value is not None and int(value) <= 0:
            _invalid(f"{key} 必须为正整数或 null")
    context = capabilities.get("context_window")
    output = capabilities.get("max_output_tokens")
    if context is not None and output is not None and int(output) > int(context):
        _invalid("max_output_tokens 不能大于 context_window")


def resolve_execution(engine: dict, role: str, override: dict | None = None,
                      legacy: dict | None = None) -> dict:
    if role not in BUILTIN_DEFAULTS:
        raise ValueError(f"未知执行角色 {role}")
    capabilities = capabilities_for(engine)
    defaults = defaults_for(engine, role)
    result = {}
    for key in PARAMETER_KEYS:
        if override and key in override:
            value = override[key]
        elif legacy and key in legacy:
            value = legacy[key]
        elif key in defaults:
            value = defaults[key]
        else:
            value = BUILTIN_DEFAULTS[role][key]
        result[key] = value
    temperature = result["temperature"]
    if temperature is not None:
        if capabilities.get("supports_temperature") is False:
            _invalid(f"引擎 {engine.get('name', engine.get('id'))} 不支持 temperature；请显式设为 null")
        allowed = capabilities.get("allowed_temperatures")
        if allowed is not None and float(temperature) not in {float(item) for item in allowed}:
            _invalid(f"引擎 {engine.get('name', engine.get('id'))} 的 {role} temperature 必须为 {allowed} 之一或 null")
    maximum = capabilities.get("max_output_tokens")
    if role != "health" and result["max_tokens"] is not None and int(result["max_tokens"]) < 100:
        _invalid(f"{role} max_tokens 不能小于 100")
    if result["max_tokens"] is not None and maximum is not None and int(result["max_tokens"]) > int(maximum):
        _invalid(f"{role} max_tokens={result['max_tokens']} 超过模型已声明的最大输出 {maximum}")
    result["json_mode"] = role == "judge"
    return result


def validate_engine_execution(engine: dict) -> None:
    capabilities = capabilities_for(engine)
    validate_capabilities(capabilities)
    for role in BUILTIN_DEFAULTS:
        resolve_execution(engine, role)


def answer_execution_for(protocol: dict, engine_id: int) -> dict:
    executions = protocol.get("answer_execution")
    if isinstance(executions, dict) and isinstance(executions.get(str(engine_id)), dict):
        return dict(executions[str(engine_id)])
    return {
        "temperature": protocol.get("temperature", 0.2),
        "max_tokens": protocol.get("max_tokens", 700),
        "system_prompt": protocol.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "json_mode": False,
    }


def judge_execution_for(protocol: dict, engine_id: int) -> dict:
    executions = protocol.get("judge_execution")
    if isinstance(executions, dict) and isinstance(executions.get(str(engine_id)), dict):
        return dict(executions[str(engine_id)])
    if isinstance(executions, dict) and any(key in executions for key in PARAMETER_KEYS):
        return {**executions, "json_mode": True}
    return {
        "temperature": 0,
        "max_tokens": 1800,
        "system_prompt": protocol.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "json_mode": True,
    }


def execution_maps(engines: list[dict], judge_engine: dict | None, payload: dict,
                   *, manual_web: bool) -> tuple[dict, dict]:
    answer_map = {}
    judge_map = {}
    answer_overrides = payload.get("answer_overrides") or {}
    judge_override = payload.get("judge_overrides") or {}
    legacy_answer = {key: payload[key] for key in PARAMETER_KEYS if key in payload}
    for engine in engines:
        engine_id = str(engine["id"])
        if not manual_web:
            override = answer_overrides.get(engine_id) or answer_overrides.get(int(engine["id"])) or {}
            answer_map[engine_id] = resolve_execution(engine, "answer", override, legacy_answer)
        if payload.get("use_judge", True):
            selected = judge_engine or engine
            legacy_judge = legacy_answer if manual_web else None
            judge_map[engine_id] = resolve_execution(selected, "judge", judge_override, legacy_judge)
    return answer_map, judge_map


def _common(executions: dict, key: str) -> Any:
    values = [value.get(key) for value in executions.values()]
    return values[0] if values and all(value == values[0] for value in values) else None


def legacy_execution_fields(answer_map: dict, judge_map: dict, *, manual_web: bool) -> dict:
    source = judge_map if manual_web else answer_map
    return {key: _common(source, key) for key in PARAMETER_KEYS}


def canonical_protocol(protocol: dict) -> dict:
    """Normalize old and new snapshots to effective per-answer-engine requests."""
    result = copy.deepcopy(protocol)
    engine_ids = [int(value) for value in protocol.get("engine_ids") or []]
    manual = protocol.get("measurement_target") == "consumer_web"
    result["answer_execution"] = {} if manual else {
        str(engine_id): answer_execution_for(protocol, engine_id) for engine_id in engine_ids
    }
    result["judge_mode"] = protocol.get("judge_mode") or (
        "disabled" if not protocol.get("use_judge")
        else "independent" if protocol.get("judge_signature") else "answer_engine"
    )
    result["judge_execution"] = {
        str(engine_id): judge_execution_for(protocol, engine_id) for engine_id in engine_ids
    } if protocol.get("use_judge") else {}
    return result
