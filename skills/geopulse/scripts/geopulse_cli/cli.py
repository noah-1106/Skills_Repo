"""Argument parsing and orchestration for the HTTP-only business CLI."""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .client import (CLI_CONTRACT, Client, CliError, clear_session, load_session,
                     save_session, session_path, verify_project_export)
from .output import emit, emit_error
from .registry import OPERATIONS, PATH_ARGUMENTS, REGISTRY

SIMPLE_OPTIONS = {
    ("project", "create"): ("name",),
    ("prompt-set", "create"): ("name",),
    ("prompt-set", "review"): ("status", "eligibility"),
    ("prompt-set", "status"): ("status", "reason"),
    ("entity", "create"): ("name", "role"),
    ("entity", "review"): ("decision", "reason", "role"),
    ("entity", "version"): ("name", "role"),
    ("wave", "status"): ("status", "reason"),
    ("opportunity", "review"): ("decision", "eligibility", "reason"),
    ("opportunity", "status"): ("status", "reason"),
    ("action", "status"): ("status", "reason"),
    ("report", "status"): ("status", "reason"),
    ("member", "assign"): ("user", "role"),
    ("schedule", "update"): ("status",),
}
SECRET_FIELDS = {"password", "current_password", "new_password", "api_key", "access_token", "authorization"}
TERMINAL_RUN_STATES = {"done", "partial", "failed", "cancelled"}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(message, code="invalid_arguments", exit_code=2)


def common_parser():
    common = Parser(add_help=False)
    default = argparse.SUPPRESS
    common.add_argument("--base-url", default=default)
    common.add_argument("--project", type=int, default=default)
    common.add_argument("--session", default=default)
    common.add_argument("--timeout", type=float, default=default)
    common.add_argument("--format", dest="output_format", choices=("json", "table"), default=default)
    common.add_argument("--json", action="store_true", default=default)
    common.add_argument("--out", type=Path, default=default)
    common.add_argument("--overwrite", action="store_true", default=default)
    return common


def build_parser():
    common = common_parser()
    parser = Parser(prog="geopulse", parents=[common], description=(
        "GeoPulse 薄业务 CLI。远程命令只调用 HTTP API；本机 init/migrate/backup/restore/"
        "set-admin-password/run-worker/golden-eval/export/delete-project 保持原语义。"
    ))
    root_sub = parser.add_subparsers(dest="command", required=True)
    groups = {(): root_sub}
    for item in [*OPERATIONS]:
        parts = item.command
        for depth in range(1, len(parts)):
            prefix = parts[:depth]
            if prefix not in groups:
                parent = groups[prefix[:-1]]
                group = parent.add_parser(parts[depth - 1], help=f"{parts[depth - 1]} 命令域")
                groups[prefix] = group.add_subparsers(dest="_".join(prefix), required=True)
        leaf = groups[parts[:-1]].add_parser(parts[-1], parents=[common], help=item.description,
                                             description=item.description)
        leaf.set_defaults(operation=item)
        add_operation_arguments(leaf, item)
    for command, description in (("capabilities", "查看服务、身份和命令能力"),
                                 ("measure run", "创建 Wave，确认后创建 Run，可选等待与指标"),
                                 ("schema", "从服务 OpenAPI 查看请求 schema"),
                                 ("example", "生成不含秘密的可填写请求示例")):
        parts = tuple(command.split())
        for depth in range(1, len(parts)):
            prefix = parts[:depth]
            if prefix not in groups:
                group = groups[prefix[:-1]].add_parser(parts[depth - 1])
                groups[prefix] = group.add_subparsers(dest="_".join(prefix), required=True)
        leaf = groups[parts[:-1]].add_parser(parts[-1], parents=[common], help=description)
        leaf.set_defaults(custom=command)
        if command == "measure run":
            leaf.add_argument("--spec", required=True)
            leaf.add_argument("--confirm", action="store_true")
            leaf.add_argument("--budget-reason")
            leaf.add_argument("--wait", action="store_true")
            leaf.add_argument("--interval", type=float, default=2)
            leaf.add_argument("--wait-timeout", type=float, default=600)
        if command == "schema":
            leaf.add_argument("model", choices=("engine", "wave", "collection-draft"))
        if command == "example":
            leaf.add_argument("model", choices=("engine", "wave", "manual-web-wave", "collection-draft"))
    return parser


def add_operation_arguments(parser, item):
    for name in re.findall(r"{([a-z_]+)}", item.path):
        if name == "project_id":
            continue
        argument = PATH_ARGUMENTS.get(name, name.removesuffix("_id"))
        parser.add_argument(f"--{argument.replace('_', '-')}", dest=f"path_{name}", type=int, required=True)
    if item.method in ("POST", "PUT") and item.command != ("evidence", "upload"):
        parser.add_argument("--spec", help="JSON 请求对象文件；- 表示 stdin")
    for option in SIMPLE_OPTIONS.get(item.command, ()):
        parser.add_argument(f"--{option.replace('_', '-')}")
    for parameter in item.query:
        if parameter in ("format", "confirm", "variant"):
            continue
        name = parameter.replace("_", "-")
        kwargs = {"dest": f"query_{parameter}"}
        if parameter in ("limit", "offset", "baseline_wave", "current_wave"):
            kwargs["type"] = int
        elif parameter in ("history", "include_history"):
            kwargs["action"] = argparse.BooleanOptionalAction
            kwargs["default"] = None
        if item.command == ("evidence", "upload"):
            kwargs["required"] = True
        parser.add_argument(f"--{name}", **kwargs)
    if item.command == ("evidence", "upload"):
        parser.add_argument("--file", type=Path, required=True, help="原始证据文件，最大 10MB")
    if item.confirmation:
        if item.confirmation == "delete":
            parser.add_argument("--confirm-name", required=True, help="必须与完整项目名一致")
        else:
            parser.add_argument("--confirm", action="store_true")
    if item.confirmation in ("run", "health"):
        parser.add_argument("--budget-reason")
    if item.confirmation == "health":
        parser.add_argument("--estimate", type=Path, help="上一次 409 返回的 estimate JSON 文件")
    if item.command == ("wave", "official"):
        parser.add_argument("--run", dest="body_run_id", type=int, required=True)
    if item.command == ("report", "create"):
        parser.add_argument("--wave-id", action="append", type=int)
    if item.command == ("prompt-set", "import"):
        parser.add_argument("--file", type=Path)
        parser.add_argument("--redact", action=argparse.BooleanOptionalAction, default=None)
    if item.command in (("auth", "login"), ("user", "create")):
        parser.add_argument("--email", required=True)
        parser.add_argument("--secret-fd", type=int)
    if item.command == ("auth", "password"):
        parser.add_argument("--current-secret-fd", type=int)
        parser.add_argument("--new-secret-fd", type=int)
    if item.command in (("engine", "create"), ("engine", "update")):
        parser.add_argument("--secret-fd", type=int)
    if item.download == "prompt":
        parser.add_argument("--file-format", choices=("json", "csv"))
    if item.download == "report":
        parser.add_argument("--file-format", choices=("html", "pdf"))
        parser.add_argument("--variant", choices=("client", "internal"))
    if item.command == ("run", "wait"):
        parser.add_argument("--interval", type=float, default=2)
        parser.add_argument("--wait-timeout", type=float, default=600)


def apply_defaults(args):
    for key, value in {"base_url": None, "project": None, "session": None, "timeout": 30,
                       "output_format": "json", "json": False, "out": None, "overwrite": False}.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    if args.json:
        args.output_format = "json"
    if args.timeout <= 0:
        raise CliError("--timeout 必须为正数", code="invalid_arguments", exit_code=2)


def read_json(path: str | Path) -> Any:
    try:
        if str(path) == "-":
            raw = sys.stdin.read()
        else:
            source = Path(path)
            if source.stat().st_size > 10 * 1024 * 1024:
                raise CliError("JSON 输入不能超过 10MB", code="input_too_large", exit_code=2)
            raw = source.read_text(encoding="utf-8")
        return json.loads(raw)
    except CliError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CliError(f"无法读取 JSON：{error}", code="invalid_json", exit_code=2) from error


def load_spec(args) -> dict:
    if not getattr(args, "spec", None):
        return {}
    value = read_json(args.spec)
    if not isinstance(value, dict):
        raise CliError("--spec 顶层必须是 JSON 对象", code="invalid_spec", exit_code=2)
    if SECRET_FIELDS.intersection(value):
        raise CliError("密码、Token 和 API Key 不能放入 spec；请使用安全 FD 或交互输入",
                       code="secret_in_spec", exit_code=2)
    return value


def merge(payload: dict, key: str, value: Any):
    if value is None:
        return
    if key in payload:
        raise CliError(f"{key} 同时出现在 --spec 和简单参数中", code="duplicate_field", exit_code=2)
    payload[key] = value


def read_secret(fd: int | None, prompt: str) -> str:
    if fd is not None:
        try:
            value = os.read(fd, 65536).decode("utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError) as error:
            raise CliError(f"无法读取 secret FD：{error}", code="secret_input_error", exit_code=2) from error
    elif sys.stdin.isatty():
        value = getpass.getpass(prompt)
    else:
        raise CliError("非交互环境必须通过 --secret-fd 提供秘密值", code="secret_input_required", exit_code=2)
    if not value:
        raise CliError("秘密值不能为空", code="secret_input_error", exit_code=2)
    return value


def parse_items(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise CliError(f"无法读取导入文件：{error}", code="invalid_import", exit_code=2) from error
    if raw.lstrip().startswith("["):
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as error:
            raise CliError(f"导入 JSON 无效：{error}", code="invalid_import", exit_code=2) from error
    else:
        reader = csv.DictReader(io.StringIO(raw, newline=""))
        if not reader.fieldnames or not {"text", "dimension"}.issubset(reader.fieldnames):
            raise CliError("CSV 至少需要 text、dimension 两列", code="invalid_import", exit_code=2)
        items = list(reader)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise CliError("导入顶层必须是对象数组", code="invalid_import", exit_code=2)
    return items


def query_values(args, item) -> dict:
    result = {}
    for parameter in item.query:
        if parameter == "confirm":
            result[parameter] = args.confirm_name
        elif parameter == "variant":
            continue
        elif parameter == "format":
            result[parameter] = getattr(args, "file_format", None) or "json"
        else:
            value = getattr(args, f"query_{parameter}", None)
            if isinstance(value, bool):
                value = str(value).lower()
            result[parameter] = value
    if item.download == "report":
        result["format"] = args.file_format or "html"
        result["variant"] = args.variant or "client"
    return result


def format_path(args, item) -> str:
    values = {}
    for name in re.findall(r"{([a-z_]+)}", item.path):
        if name == "project_id":
            if not args.project:
                raise CliError("该命令需要显式 --project ID", code="project_required", exit_code=2)
            values[name] = args.project
        else:
            values[name] = getattr(args, f"path_{name}")
    return item.path.format(**values)


def require_confirmation(args, item, payload):
    if not item.confirmation or item.confirmation in ("run", "health", "delete"):
        return
    if not args.confirm:
        raise CliError("该操作需要另一次显式 --confirm；未发送写请求", code="confirmation_required",
                       detail={"command": " ".join(item.command)}, exit_code=4)
    if item.command == ("report", "status") and not (payload.get("reason") or "").strip():
        raise CliError("报告审批必须填写 --reason", code="reason_required", exit_code=2)


def wave_for_run(client, args, item, path):
    if item.command == ("wave", "run"):
        wave_id = args.path_wave_id
    else:
        run = client.request("GET", f"/api/projects/{args.project}/runs/{args.path_run_id}").json()
        wave_id = run["wave_id"]
    return client.request("GET", f"/api/projects/{args.project}/waves/{wave_id}").json()


def requires_real_confirmation(wave: dict) -> bool:
    protocol = wave["protocol"]
    engines = list(protocol.get("engine_signature") or [])
    judge = protocol.get("judge_signature")
    if judge:
        engines.append(judge)
    return any(engine.get("kind") not in ("demo", "manual_web") for engine in engines)


def build_body(args, item):
    payload = load_spec(args)
    for option in SIMPLE_OPTIONS.get(item.command, ()):
        merge(payload, option, getattr(args, option))
    if item.command == ("wave", "official"):
        merge(payload, "run_id", args.body_run_id)
    if item.command == ("report", "create") and args.wave_id:
        merge(payload, "wave_ids", args.wave_id)
    if item.command == ("member", "assign"):
        merge(payload, "user_id", int(args.user) if args.user is not None else None)
    if item.command == ("prompt-set", "import"):
        if args.file:
            merge(payload, "items", parse_items(args.file))
        merge(payload, "redact", args.redact)
    if item.confirmation == "retention":
        payload["confirm"] = True
    if item.confirmation in ("run", "health"):
        merge(payload, "budget_confirmation_reason", args.budget_reason)
    if item.confirmation == "health":
        payload["confirm"] = bool(args.confirm)
    if item.command in (("engine", "create"), ("engine", "update")):
        if item.command == ("engine", "create") and payload.get("kind") == "manual_web":
            if args.secret_fd is not None:
                raise CliError("人工 Web 目标不接收 API Key", code="secret_not_allowed", exit_code=2)
            payload["api_key"] = ""
        elif args.secret_fd is not None:
            payload["api_key"] = read_secret(args.secret_fd, "API Key：")
        elif item.command == ("engine", "update"):
            payload["api_key"] = "__KEEP__"
        elif payload.get("kind") not in (None, "demo", "manual_web") and sys.stdin.isatty():
            payload["api_key"] = read_secret(None, "API Key：")
    return payload


def default_filename(item, args) -> Path:
    if item.download == "report":
        extension = args.file_format or "html"
        return Path.cwd() / f"geopulse-report-{args.path_report_id}.{extension}"
    if item.download == "prompt":
        extension = args.file_format or "json"
        return Path.cwd() / f"geopulse-prompt-set-{args.path_set_id}.{extension}"
    if item.download == "evidence":
        return Path.cwd() / f"geopulse-evidence-{args.path_attachment_id}.bin"
    return Path.cwd() / f"geopulse-project-{args.project}.json"


def execute(client, args, item):
    path = format_path(args, item)
    query = query_values(args, item)
    if item.command == ("evidence", "upload"):
        try:
            if not 0 < args.file.stat().st_size <= 10 * 1024 * 1024:
                raise CliError("证据文件必须非空且不超过 10MB", code="invalid_evidence", exit_code=2)
            content = args.file.read_bytes()
        except OSError as error:
            raise CliError(f"无法读取证据文件：{error}", code="invalid_evidence", exit_code=2) from error
        response = client.request(item.method, path, query=query, data=content, headers={
            "Content-Type": "application/octet-stream",
            "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
        })
        return response.json()
    body = build_body(args, item) if item.method in ("POST", "PUT") else None
    if item.command == ("report", "create") and not body.get("wave_ids"):
        raise CliError("report create 需要 --wave-id（可重复）或 --spec，不会默认选择 Wave",
                       code="wave_required", exit_code=2)
    require_confirmation(args, item, body or {})
    if item.confirmation == "run":
        wave = wave_for_run(client, args, item, path)
        real = requires_real_confirmation(wave)
        if real and not args.confirm:
            raise CliError("真实引擎调用未执行；请核对预估后另一次显式 --confirm",
                           code="run_confirmation_required", detail={"wave_id": wave["id"], "estimate": wave["estimate"]},
                           exit_code=4)
    if item.confirmation == "health" and args.confirm:
        if not args.estimate:
            raise CliError("真实健康检查确认必须同时提供上一次 409 的 --estimate JSON 文件；未发送第二次请求",
                           code="estimate_required", exit_code=2)
        estimate = read_json(args.estimate)
        if isinstance(estimate, dict) and "estimate" in estimate:
            estimate = estimate["estimate"]
        if not isinstance(estimate, dict) or "max_estimated_cost" not in estimate:
            raise CliError("--estimate 必须是上一次响应中的 estimate 对象", code="invalid_estimate", exit_code=2)
    if item.command == ("run", "wait"):
        return wait_for_run(client, args, path)
    if item.download:
        target = args.out or default_filename(item, args)
        validator = None
        if item.download == "project":
            def validator(source):
                try:
                    payload = json.loads(source.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise CliError(f"项目导出不是有效 JSON：{error}", code="invalid_export", exit_code=5) from error
                return {"project_export_sha256_verified": verify_project_export(payload) == payload["sha256"]}
        result = client.download(item.method, path, target, query=query, overwrite=args.overwrite,
                                 validator=validator)
        return {"download": result}
    response = client.request(item.method, path, query=query, json_body=body)
    result = response.json()
    if item.command == ("admin", "backup"):
        note = "备份数据库位于服务器备份目录；CLI 未下载数据库字节，也未声称本地校验该数据库。"
        if args.out:
            write_json_atomic(args.out, result, args.overwrite)
            return {"backup_manifest": result, "manifest_path": str(args.out), "delivery": "server_side", "note": note}
        return {"backup_manifest": result, "delivery": "server_side", "note": note}
    if item.command == ("collection", "submit"):
        return {**result, "worker_required": True,
                "next_step": "回答已进入 judging；启动 run-worker 完成 Judge 和 Run，再用 run wait 查询。"}
    return result


def write_json_atomic(path: Path, value: Any, overwrite=False):
    path = path.expanduser().resolve()
    if path.exists() and not overwrite:
        raise CliError(f"输出文件已存在：{path}", code="output_exists", exit_code=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def wait_for_run(client, args, path):
    if args.interval <= 0 or args.wait_timeout <= 0:
        raise CliError("轮询间隔和等待超时必须为正数", code="invalid_arguments", exit_code=2)
    deadline = time.monotonic() + args.wait_timeout
    latest = None
    while True:
        latest = client.request("GET", path).json()
        if latest.get("status") in TERMINAL_RUN_STATES:
            return latest
        if time.monotonic() >= deadline:
            raise CliError("等待超时，不代表 Run 失败；可稍后再次 run wait", code="wait_timeout",
                           detail={"run": latest}, exit_code=4)
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))


def auth_command(client, args, item):
    if item.command == ("auth", "login"):
        password = read_secret(args.secret_fd, "密码：")
        result = client.request("POST", item.path, json_body={"email": args.email, "password": password}).json()
        token = result.pop("access_token")
        result.pop("csrf_token", None)
        save_session(session_path(args.session), client.base_url, token, result)
        return {"authenticated": True, "base_url": client.base_url, "user": result,
                "session": str(session_path(args.session)), "token_saved": True, "token_displayed": False}
    if item.command == ("auth", "password"):
        current = read_secret(args.current_secret_fd, "当前密码：")
        new = read_secret(args.new_secret_fd, "新密码（至少 10 位）：")
        result = client.request("POST", item.path, json_body={"current_password": current, "new_password": new}).json()
        return result
    if item.command == ("user", "create"):
        password = read_secret(args.secret_fd, "新用户密码（至少 10 位）：")
        return client.request("POST", item.path, json_body={"email": args.email, "password": password}).json()
    if item.command == ("auth", "logout"):
        result = client.request("POST", item.path, json_body={}).json()
        clear_session(session_path(args.session))
        return {**result, "local_session_removed": True}
    return None


def schema_command(client, args):
    document = client.request("GET", "/openapi.json").json()
    model = {"engine": "EngineIn", "wave": "WaveIn", "collection-draft": "CollectionDraftIn"}[args.model]
    definitions = (document.get("components") or {}).get("schemas") or {}
    if model not in definitions:
        raise CliError(f"服务 OpenAPI 未提供 {model}", code="schema_unavailable", exit_code=5)

    def resolve(value):
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            name = value["$ref"].removeprefix("#/components/schemas/")
            if name not in definitions:
                raise CliError(f"OpenAPI 引用无法解析：{value['$ref']}", code="schema_unavailable", exit_code=5)
            return resolve(definitions[name])
        return {key: resolve(item) for key, item in value.items()}

    return {"model": model, "source": "/openapi.json", "schema": resolve(definitions[model])}


def example_command(args):
    protocol = {
        "product_url": "https://consumer.example.com/chat", "platform": "example-product",
        "surface": "desktop_web", "page_mode": "default", "networking": False,
        "deep_thinking": False, "deep_research": False, "session_mode": "new",
        "login_state": "anonymous", "account_type": "", "region": "CN", "language": "zh-CN",
        "context_clearing": "new_session", "follow_up_policy": "none", "protocol_version": "manual-web-v1",
    }
    examples = {
        "engine": {
            "name": "DeepSeek Search", "vendor": "DeepSeek", "kind": "deepseek_search",
            "model": "按账号可用模型填写", "base_url": "https://api.deepseek.com/v1", "mode": "search",
            "measurement_target": "provider_api", "cost_rule": {"currency": "CNY"},
            "capabilities": {"supports_json_mode": None, "max_output_tokens": None},
            "answer_defaults": {"temperature": 0.2, "max_tokens": 700},
            "judge_defaults": {"temperature": 0, "max_tokens": 1800},
            "health_defaults": {"max_tokens": 8},
        },
        "wave": {
            "prompt_set_id": 1, "label": "Provider 独立 Judge 测量", "engine_ids": [1], "repeats": 1,
            "use_judge": True, "judge_engine_id": 2,
            "answer_overrides": {"1": {"temperature": 0.2, "max_tokens": 700}},
            "judge_overrides": {"temperature": 0, "max_tokens": 1800},
        },
        "manual-web-wave": {
            "prompt_set_id": 1, "label": "人工 Consumer Web 测量", "engine_ids": [1],
            "judge_engine_id": 2, "repeats": 1, "use_judge": True, "collection_protocol": protocol,
        },
        "collection-draft": {
            "draft_text": "粘贴实际页面中的完整回答", "actual_url": protocol["product_url"],
            "observed_mode": "default", "observed_at": "2026-11-07T10:00:00+08:00",
            "timezone": "Asia/Shanghai", "retrieval_status": "off", "notes": "不要填写账号、Cookie 或 Token",
            "session_context": {key: value for key, value in protocol.items()
                                if key not in ("product_url", "platform", "protocol_version")},
            "citations": [{"url": "https://example.com/source", "title": "实际看到的来源", "text": "实际看到的卡片文本"}],
            "status": "review_pending",
        },
    }
    commands = {
        "engine": "geopulse engine create --project <ID> --spec engine.json --secret-fd <FD>",
        "wave": "geopulse wave create --project <ID> --spec wave.json",
        "manual-web-wave": "geopulse wave create --project <ID> --spec manual-web-wave.json",
        "collection-draft": "geopulse collection save --project <ID> --answer <ID> --spec collection-draft.json",
    }
    notes = ["示例中的 ID、模型、入口和观察事实必须替换为实际值；示例不包含 API Key。"]
    if args.model == "collection-draft":
        notes.append("正式 collection submit --confirm 后 answer 进入 judging；必须启动 run-worker 才会完成 Judge 和 Run。")
    if args.model == "manual-web-wave":
        notes.append("创建 Run 后只产生人工采集任务；系统不会自动操作网页或保存登录会话。")
        notes.append("collection submit --confirm 后必须启动 run-worker，完整测量才会从 judging 继续。")
    return {"spec": examples[args.model], "usage": commands[args.model], "notes": notes}


def capabilities(args):
    client = Client.authenticated(args, required=False)
    health = client.request("GET", "/api/health").json()
    identity = {"authenticated": False, "user": None}
    if client.token:
        try:
            identity = {"authenticated": True, "user": client.request("GET", "/api/auth/me").json()}
        except CliError as error:
            if error.status != 401:
                raise
            identity = {"authenticated": False, "user": None, "reason": "session_expired"}
    commands = [{"command": " ".join(item.command), "method": item.method, "path": item.path,
                 "query": list(item.query), "confirmation": item.confirmation or None,
                 "download": item.download or None} for item in OPERATIONS]
    commands += [{"command": "capabilities", "custom": True}, {"command": "measure run", "custom": True},
                 {"command": "schema engine|wave|collection-draft", "custom": True},
                 {"command": "example engine|wave|manual-web-wave|collection-draft", "custom": True}]
    return {"cli_contract": CLI_CONTRACT, "health": health, **identity, "commands": commands,
            "live_provider_verified": False,
            "note": "命令覆盖不代表真实 Provider、Consumer Web 或授权 Collector 已完成 live 验收。"}


def measure_run(client, args):
    wave = client.request("POST", f"/api/projects/{args.project}/waves", json_body=load_spec(args)).json()
    real = requires_real_confirmation(wave)
    if real and not args.confirm:
        raise CliError("Wave 已创建，但真实 Run 未创建；请核对预估后用 wave run --confirm",
                       code="waiting_for_decision", detail={"status": "waiting_for_decision", "wave": wave}, exit_code=4)
    body = {"budget_confirmation_reason": args.budget_reason} if args.budget_reason else {}
    run = client.request("POST", f"/api/projects/{args.project}/waves/{wave['id']}/runs", json_body=body).json()
    result = {"wave": wave, "run": run}
    if args.wait:
        final = wait_for_run(client, args, f"/api/projects/{args.project}/runs/{run['run']['id']}")
        result["final_run"] = final
        result["metrics"] = client.request("GET", f"/api/projects/{args.project}/runs/{run['run']['id']}/metrics").json()
    return result


def main(argv=None):
    args = None
    try:
        args = build_parser().parse_args(argv)
        apply_defaults(args)
        if getattr(args, "custom", None) == "capabilities":
            result = capabilities(args)
        elif getattr(args, "custom", None) == "example":
            result = example_command(args)
        elif getattr(args, "custom", None) == "schema":
            client = Client.authenticated(args, required=False)
            result = schema_command(client, args)
        else:
            item = getattr(args, "operation", None)
            required = item not in (REGISTRY[("auth", "login")], REGISTRY[("health",)])
            client = Client.authenticated(args, required=required)
            if not required:
                client.token = ""
            if getattr(args, "custom", None) == "measure run":
                if not args.project:
                    raise CliError("measure run 需要显式 --project ID", code="project_required", exit_code=2)
                result = measure_run(client, args)
            else:
                item = args.operation
                special = auth_command(client, args, item) if item.command[0] == "auth" or item.command == ("user", "create") else None
                result = special if special is not None else execute(client, args, item)
        emit(result, args.output_format)
        return 0
    except CliError as error:
        emit_error(error.payload())
        return error.exit_code
    except KeyboardInterrupt:
        emit_error(CliError("操作已中断；不会自动重试写请求", code="interrupted", exit_code=130).payload())
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
