from __future__ import annotations

import json

import pytest

from backend.app.db import connect, loads, one
from backend.app.engine.compare import protocol_check
from backend.app.providers.base import ProviderError
from backend.app.providers.openai_compat import OpenAICompatProvider
from backend.app.services.budgets import estimate_health
from backend.app.services.execution import answer_execution_for, resolve_execution, validate_engine_execution
from conftest import api, execute_run


def engine_payload(name="执行参数引擎", **changes):
    payload = {
        "name": name, "vendor": "Test", "kind": "openai_compat", "model": "model-v1",
        "base_url": "https://example.test/v1", "api_key": "test-only-secret", "mode": "memory",
        "cost_rule": {"currency": "CNY", "input_per_million": 1, "output_per_million": 1},
    }
    payload.update(changes)
    return payload


def create_demo(client, name):
    return api(client, "POST", f"/api/projects/{client.project_id}/engines", json={
        "name": name, "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2", "mode": "memory",
    })


def test_duplicate_engine_names_return_409_for_create_and_update(client):
    original = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"][0]
    duplicate = create_demo(client, "另一个 Demo")
    error = api(client, "POST", f"/api/projects/{client.project_id}/engines", expected=409, json={
        "name": f"  {original['name']}  ", "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2",
    })
    assert error["detail"]["code"] == "engine_name_conflict"
    error = api(client, "PUT", f"/api/projects/{client.project_id}/engines/{duplicate['id']}", expected=409,
                json={"name": original["name"], "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2"})
    assert error["detail"]["code"] == "engine_name_conflict"
    updated = api(client, "PUT", f"/api/projects/{client.project_id}/engines/{duplicate['id']}",
                  json={"name": duplicate["name"], "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2"})
    assert updated["id"] == duplicate["id"]
    create_demo(client, "跨项目同名")
    other = api(client, "POST", "/api/projects", json={"client_name": "另一客户", "name": "另一项目"})
    created = api(client, "POST", f"/api/projects/{other['id']}/engines", json={
        "name": "跨项目同名", "vendor": "GeoPulse", "kind": "demo", "model": "demo-v2"})
    assert created["name"] == "跨项目同名"


def test_engine_defaults_wave_override_and_null_are_frozen(client):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload(
        answer_defaults={"temperature": 0.7, "max_tokens": 500, "system_prompt": "引擎默认"},
        judge_defaults={"temperature": 0.1, "max_tokens": 900},
        health_defaults={"temperature": None, "max_tokens": 12, "system_prompt": None},
        capabilities={"allowed_temperatures": [0, 0.1, 0.2, 0.7, 0.8]},
    ))
    prompt_set = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set["id"], "label": "冻结执行参数", "engine_ids": [engine["id"]],
        "repeats": 1, "answer_overrides": {str(engine["id"]): {"temperature": 0.8, "system_prompt": None}},
        "judge_overrides": {"max_tokens": 1000},
    })
    answer = wave["protocol"]["answer_execution"][str(engine["id"])]
    judge = wave["protocol"]["judge_execution"][str(engine["id"])]
    assert answer == {"temperature": 0.8, "max_tokens": 500, "system_prompt": None, "json_mode": False}
    assert judge["temperature"] == 0.1 and judge["max_tokens"] == 1000 and judge["json_mode"] is True
    assert wave["protocol"]["system_prompt"] is None
    api(client, "PUT", f"/api/projects/{client.project_id}/engines/{engine['id']}", json=engine_payload(
        answer_defaults={"temperature": 0.2, "max_tokens": 200, "system_prompt": "修改后"},
        api_key="__KEEP__",
    ))
    frozen = api(client, "GET", f"/api/projects/{client.project_id}/waves/{wave['id']}")
    assert frozen["protocol"]["answer_execution"][str(engine["id"])] == answer


def test_model_capabilities_reject_unsupported_temperature_and_output_limit(client):
    error = api(client, "POST", f"/api/projects/{client.project_id}/engines", expected=422,
                json=engine_payload(capabilities={"supports_temperature": False}))
    assert error["detail"]["code"] == "invalid_model_parameters"
    api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload(
        name="不支持温度", capabilities={"supports_temperature": False},
        answer_defaults={"temperature": None}, judge_defaults={"temperature": None},
        health_defaults={"temperature": None},
    ))
    error = api(client, "POST", f"/api/projects/{client.project_id}/engines", expected=422,
                json=engine_payload(name="输出超限", capabilities={"max_output_tokens": 600},
                                    answer_defaults={"max_tokens": 500}, judge_defaults={"max_tokens": 700}))
    assert "最大输出" in error["detail"]["message"]


def test_new_answer_default_is_64k_without_rewriting_legacy_default():
    assert resolve_execution({}, "answer")["max_tokens"] == 65536
    assert resolve_execution({}, "judge")["max_tokens"] == 1800
    assert answer_execution_for({}, 1)["max_tokens"] == 700


@pytest.mark.parametrize("tokens", [65536, 131072, 393216, 1048576])
def test_large_output_budgets_are_accepted_and_frozen(client, tokens):
    engine = api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload(
        name=f"长输出 {tokens}", capabilities={"max_output_tokens": tokens},
        answer_defaults={"max_tokens": tokens},
    ))
    assert engine["answer_defaults"]["max_tokens"] == tokens
    prompt_set = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set["id"], "label": f"长输出 Wave {tokens}", "engine_ids": [engine["id"]],
        "repeats": 1, "use_judge": False,
        "answer_overrides": {str(engine["id"]): {"max_tokens": tokens}},
    })
    execution = wave["protocol"]["answer_execution"][str(engine["id"])]
    assert execution["max_tokens"] == tokens


def test_declared_output_limit_still_rejects_larger_request(client):
    error = api(client, "POST", f"/api/projects/{client.project_id}/engines", expected=422,
                json=engine_payload(name="声明上限仍生效", capabilities={"max_output_tokens": 65536},
                                    answer_defaults={"max_tokens": 65537}))
    assert error["detail"]["code"] == "invalid_model_parameters"
    assert "最大输出" in error["detail"]["message"]


def test_openai_request_omits_explicit_null_and_json_response_format(monkeypatch):
    requests = []

    class Response:
        headers = {"x-request-id": "request-id"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: requests.append(request) or Response())
    provider = OpenAICompatProvider("https://example.test/v1", "secret", "model",
                                    capabilities={"supports_json_mode": False})
    provider.ask_json("question", {"temperature": None, "max_tokens": None, "system_prompt": None})
    payload = json.loads(requests[0].data)
    assert payload == {"model": "model", "messages": [{"role": "user", "content": "question"}]}


def test_empty_health_defaults_use_provider_defaults_without_inheriting_answer(monkeypatch):
    engine = {
        "name": "只允许 temperature=1 的模型",
        "capabilities": {"allowed_temperatures": [1]},
        "answer_defaults": {"temperature": 1, "max_tokens": 8000},
        "judge_defaults": {"temperature": 1},
        "health_defaults": {},
    }
    validate_engine_execution(engine)
    health = resolve_execution(engine, "health")
    assert health["temperature"] is None and health["max_tokens"] is None
    assert resolve_execution(engine, "answer")["max_tokens"] == 8000

    requests = []

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "健康检查通过"}}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: requests.append(request) or Response())
    provider = OpenAICompatProvider("https://example.test/v1", "secret", "model")
    provider.ask("只回答：健康检查通过", health)
    payload = json.loads(requests[0].data)
    assert "temperature" not in payload and "max_tokens" not in payload
    assert payload["messages"][-1] == {"role": "user", "content": "只回答：健康检查通过"}

    engine["health_defaults"] = {"temperature": 1, "max_tokens": 32}
    explicit = resolve_execution(engine, "health")
    assert explicit["temperature"] == 1 and explicit["max_tokens"] == 32


def test_health_estimate_without_output_limit_uses_configured_token_estimate():
    estimate = estimate_health({
        "name": "健康检查预估", "kind": "openai_compat", "health_defaults": {},
        "answer_defaults": {"max_tokens": 8000},
        "cost_rule": {"currency": "CNY", "input_per_million": 2, "output_per_million": 3,
                      "estimated_output_tokens": 640},
    })
    expected = round((40 * 2 + 640 * 3) / 1_000_000, 6)
    assert estimate["estimated_cost"] == expected
    assert estimate["max_estimated_cost"] == expected


def test_complete_think_block_is_separated_without_retaining_reasoning():
    provider = OpenAICompatProvider("https://example.test/v1", "secret", "model")
    provider._post = lambda *args: ({"choices": [{"finish_reason": "stop", "message": {
        "content": "<think>private chain</think>\n可见回答"}}]}, 1, "id")
    result = provider.ask("question", {})
    assert result.text == "可见回答"
    operation = result.operations[0]
    assert operation["response_meta"] == {"reasoning_present": True, "reasoning_format": "think_tag"}
    assert "private chain" not in str(operation)


@pytest.mark.parametrize("content,kind", [
    ("<think>unclosed private chain", "reasoning_incomplete"),
    ("<think>private chain</think>  ", "empty_answer"),
])
def test_incomplete_or_reasoning_only_think_block_is_invalid(content, kind):
    provider = OpenAICompatProvider("https://example.test/v1", "secret", "model")
    provider._post = lambda *args: ({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}, 1, "id")
    with pytest.raises(ProviderError) as caught:
        provider.ask("question", {})
    assert caught.value.kind == kind


def test_provider_wave_uses_one_independent_demo_judge(client):
    answer = api(client, "GET", f"/api/projects/{client.project_id}/engines")["items"][0]
    judge = create_demo(client, "独立 Demo Judge")
    prompt_set = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set["id"], "label": "独立 Judge", "engine_ids": [answer["id"]],
        "judge_engine_id": judge["id"], "repeats": 1,
        "judge_overrides": {"max_tokens": 1200},
    })
    assert wave["protocol"]["judge_mode"] == "independent"
    assert wave["estimate"]["answer_calls"] == 8 and wave["estimate"]["judge_calls"] == 8
    assert [entry["role"] for entry in wave["estimate"]["by_engine"]] == ["answer", "judge"]
    run = api(client, "POST", f"/api/projects/{client.project_id}/waves/{wave['id']}/runs")["run"]
    assert execute_run(client, run["id"]) == "done"
    with connect() as conn:
        attempts = conn.execute("SELECT kind,engine_config_id,COUNT(*) AS count FROM call_attempts WHERE run_id=? GROUP BY kind,engine_config_id",
                                (run["id"],)).fetchall()
        assert {(row["kind"], row["engine_config_id"], row["count"]) for row in attempts} == {
            ("answer", answer["id"], 8), ("judge", judge["id"], 8)}
        judge_attempt = one(conn, "SELECT * FROM call_attempts WHERE run_id=? AND kind='judge' LIMIT 1", (run["id"],))
        assert loads(judge_attempt["request_params_json"])["max_tokens"] == 1200


def test_independent_judge_estimate_uses_judge_engine_and_effective_tokens(client):
    first = api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload("回答 A"))
    second = api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload("回答 B"))
    judge = api(client, "POST", f"/api/projects/{client.project_id}/engines", json=engine_payload(
        "独立计费 Judge", judge_defaults={"max_tokens": 200}))
    prompt_set = api(client, "GET", f"/api/projects/{client.project_id}/prompt-sets")["items"][0]
    wave = api(client, "POST", f"/api/projects/{client.project_id}/waves", json={
        "prompt_set_id": prompt_set["id"], "label": "多引擎独立 Judge", "engine_ids": [first["id"], second["id"]],
        "judge_engine_id": judge["id"], "repeats": 1,
        "answer_overrides": {str(first["id"]): {"max_tokens": 100}, str(second["id"]): {"max_tokens": 100}},
    })
    estimate = wave["estimate"]
    assert estimate["answer_calls"] == 16 and estimate["judge_calls"] == 16 and estimate["search_calls"] == 0
    judge_entry = next(entry for entry in estimate["by_engine"] if entry["role"] == "judge")
    assert judge_entry["engine"] == "独立计费 Judge"
    assert len([entry for entry in estimate["by_engine"] if entry["role"] == "judge"]) == 1
    assert estimate["estimated_output_tokens"] == 16 * 100 + 16 * 200


def test_old_and_new_effective_protocols_compare_equal():
    common = {
        "prompt_set_hash": "p", "entity_version": "e", "competitor_pool_hash": "c",
        "engine_signature": [{"id": 1}], "engine_ids": [1], "repeats": 1, "language": "zh-CN",
        "market": "CN", "judge_version": "j", "mode": "memory", "measurement_target": "provider_api",
        "valid_sample_definition": "v", "stratum_weights": {}, "use_judge": True,
        "collection_protocol": None, "judge_signature": None,
    }
    old = {**common, "temperature": 0.2, "max_tokens": 700, "system_prompt": "system",
           "judge_execution": {"temperature": 0, "max_tokens": 1800, "system_prompt": "system"}}
    new = {**common, "temperature": None, "max_tokens": None, "system_prompt": None,
           "judge_mode": "answer_engine",
           "answer_execution": {"1": {"temperature": 0.2, "max_tokens": 700, "system_prompt": "system", "json_mode": False}},
           "judge_execution": {"1": {"temperature": 0, "max_tokens": 1800, "system_prompt": "system", "json_mode": True}}}
    assert protocol_check(old, new)["comparable"]
    new["answer_execution"]["1"]["max_tokens"] = 701
    assert "answer_execution" in protocol_check(old, new)["mismatches"]
