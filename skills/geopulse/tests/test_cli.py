from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

import pytest

from backend.app.db import connect, one
from backend.app.main import app
from backend.app.services.measurement import Worker
from scripts.geopulse_cli.cli import build_parser
from scripts.geopulse_cli.client import Client, CliError
from scripts.geopulse_cli.registry import OPERATIONS

ROOT = Path(__file__).resolve().parent.parent
CTL = ROOT / "scripts" / "geopulse_ctl.py"
PASSWORD = "test-cli-admin-password"


def test_registry_covers_every_business_route():
    expected = {(method.upper(), path) for path, methods in app.openapi()["paths"].items()
                for method in methods if method in {"get", "post", "put", "delete", "patch"} and path != "/"}
    registered = {(item.method, item.path) for item in OPERATIONS}
    assert registered == expected
    assert len(OPERATIONS) == len({item.command for item in OPERATIONS})
    assert ("run", "wait") in {item.command for item in OPERATIONS}


def test_real_run_confirmation_is_checked_before_http_write(tmp_path):
    args = build_parser().parse_args(["wave", "run", "--project", "1", "--wave", "9"])
    class FakeClient:
        def __init__(self):
            self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append((method, path))
            class Response:
                def json(self):
                    return {"id": 9, "protocol": {"engine_signature": [{"kind": "openai_compat"}]},
                            "estimate": {"max_estimated_cost": 1}}
            return Response()
    client = FakeClient()
    with pytest.raises(CliError) as error:
        from scripts.geopulse_cli.cli import execute
        execute(client, args, args.operation)
    assert error.value.code == "run_confirmation_required"
    assert client.calls == [("GET", "/api/projects/1/waves/9")]


def test_network_errors_are_not_retried():
    client = Client("http://127.0.0.1:8701", "token")
    calls = []
    class FailingOpener:
        def open(self, request, timeout):
            calls.append(request)
            raise urllib.error.URLError("offline")
    client.opener = FailingOpener()
    with pytest.raises(CliError) as error:
        client.request("POST", "/api/projects/1/waves/2/runs", json_body={})
    assert error.value.code == "network_error"
    assert len(calls) == 1


def test_spec_preserves_explicit_null_and_rejects_secrets(tmp_path):
    spec = tmp_path / "schedule.json"
    spec.write_text('{"scheduled_at":null,"recurrence_days":null,"status":"paused"}', encoding="utf-8")
    args = build_parser().parse_args(["schedule", "update", "--project", "1", "--schedule", "3", "--spec", str(spec)])
    from scripts.geopulse_cli.cli import build_body
    assert build_body(args, args.operation) == {"scheduled_at": None, "recurrence_days": None, "status": "paused"}
    spec.write_text('{"name":"engine","api_key":"must-not-be-here"}', encoding="utf-8")
    args = build_parser().parse_args(["engine", "create", "--project", "1", "--spec", str(spec)])
    with pytest.raises(CliError) as error:
        build_body(args, args.operation)
    assert error.value.code == "secret_in_spec"
    spec.write_text('{"name":"manual","kind":"manual_web"}', encoding="utf-8")
    args = build_parser().parse_args(["engine", "create", "--project", "1", "--spec", str(spec), "--secret-fd", "0"])
    with pytest.raises(CliError) as error:
        build_body(args, args.operation)
    assert error.value.code == "secret_not_allowed"
    args = build_parser().parse_args(["engine", "create", "--project", "1", "--spec", str(spec)])
    assert build_body(args, args.operation)["api_key"] == ""


@pytest.fixture
def cli_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "GEOPULSE_DB": str(tmp_path / "cli.db"),
           "GEOPULSE_SECRETS": str(tmp_path / "secrets.json"),
           "GEOPULSE_CONFIG": str(tmp_path / "missing.json"),
           "GEOPULSE_BACKUP_DIR": str(tmp_path / "backups"),
           "GEOPULSE_EXPORT_DIR": str(tmp_path / "exports"),
           "GEOPULSE_ADMIN_EMAIL": "admin@cli.local", "GEOPULSE_ADMIN_PASSWORD": PASSWORD,
           "GEOPULSE_DISABLE_WORKER": "1", "GEOPULSE_PORT": str(port),
           "GEOPULSE_BASE_URL": f"http://127.0.0.1:{port}",
           "GEOPULSE_SESSION": str(tmp_path / "session.json")}
    for key in list(env):
        if key.startswith("GEOPULSE_") and key not in {"GEOPULSE_DB", "GEOPULSE_SECRETS", "GEOPULSE_CONFIG",
                "GEOPULSE_BACKUP_DIR", "GEOPULSE_EXPORT_DIR", "GEOPULSE_ADMIN_EMAIL", "GEOPULSE_ADMIN_PASSWORD",
                "GEOPULSE_DISABLE_WORKER", "GEOPULSE_PORT", "GEOPULSE_BASE_URL", "GEOPULSE_SESSION"}:
            env.pop(key)
    log = (tmp_path / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(ROOT / "run_test_server.py")], cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT)
    os.environ.update({key: value for key, value in env.items() if key.startswith("GEOPULSE_")})
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                Client(env["GEOPULSE_BASE_URL"], timeout=0.3).request("GET", "/api/health")
                break
            except CliError:
                if process.poll() is not None:
                    raise AssertionError((tmp_path / "server.log").read_text())
                time.sleep(0.05)
        else:
            raise AssertionError("CLI test server did not start")

        def run(*arguments, expected=0, secret=None, session=None):
            command = [sys.executable, str(CTL), *map(str, arguments)]
            passthrough = {}
            if secret is not None:
                read_fd, write_fd = os.pipe()
                os.write(write_fd, secret.encode())
                os.close(write_fd)
                command += ["--secret-fd", str(read_fd)]
                passthrough = {"pass_fds": (read_fd,)}
            completed = subprocess.run(command, cwd=ROOT, env={**env, "GEOPULSE_SESSION": str(session or env["GEOPULSE_SESSION"])},
                                       capture_output=True, text=True, timeout=45, **passthrough)
            if secret is not None:
                os.close(read_fd)
            output = completed.stdout if completed.stdout.strip() else completed.stderr
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as error:
                raise AssertionError(f"non-JSON CLI output: {completed.stdout}\n{completed.stderr}") from error
            assert completed.returncode == expected, json.dumps(payload, ensure_ascii=False)
            assert PASSWORD not in completed.stdout + completed.stderr
            return payload
        run.env = env
        run.tmp_path = tmp_path
        yield run
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        log.close()


def test_cli_demo_delivery_chain(cli_server, tmp_path):
    run = cli_server
    login = run("auth", "login", "--email", "admin@cli.local", secret=PASSWORD)
    assert login["token_saved"] and not login["token_displayed"]
    assert "access_token" not in json.dumps(login)
    assert oct(Path(run.env["GEOPULSE_SESSION"]).stat().st_mode & 0o777) == "0o600"
    projects = run("project", "list")
    project_id = projects["items"][0]["id"]
    assert run("capabilities")["authenticated"]
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"settings": {"prompt_quotas": {"brand": 0, "scene": 0, "compare": 0, "choice": 0}}}), encoding="utf-8")
    run("project", "settings", "--project", project_id, "--spec", settings)

    prompt_set = run("prompt-set", "create", "--project", project_id, "--name", "CLI 问题集")
    source = tmp_path / "items.csv"
    source.write_text('text,dimension,query_type,priority\n"有哪些 GEO 工具？",choice,discovery,5\n', encoding="utf-8")
    imported = run("prompt-set", "import", "--project", project_id, "--set", prompt_set["id"], "--file", source, "--redact")
    item_id = imported["items"][0]["id"]
    run("prompt-set", "review", "--project", project_id, "--set", prompt_set["id"], "--item", item_id,
        "--status", "reviewed", "--confirm")
    run("prompt-set", "status", "--project", project_id, "--set", prompt_set["id"],
        "--status", "reviewing", "--reason", "CLI 提交审核")
    frozen = run("prompt-set", "status", "--project", project_id, "--set", prompt_set["id"],
                 "--status", "frozen", "--reason", "CLI 验收冻结")
    assert frozen["status"] == "frozen"

    entity_spec = tmp_path / "entity.json"
    entity_spec.write_text(json.dumps({"name": "CLI Competitor", "role": "competitor",
                                       "entity_card": {"aliases": ["CLI Competitor"], "category": "软件"}}), encoding="utf-8")
    entity = run("entity", "create", "--project", project_id, "--spec", entity_spec)
    run("entity", "review", "--project", project_id, "--entity", entity["id"], "--decision", "confirmed",
        "--role", "competitor", "--reason", "CLI 人工审核", "--confirm")
    engine = run("engine", "list", "--project", project_id)["items"][0]
    wave_spec = tmp_path / "wave.json"
    wave_spec.write_text(json.dumps({"prompt_set_id": prompt_set["id"], "label": "CLI Demo Wave",
                                     "engine_ids": [engine["id"]], "repeats": 1, "use_judge": True}), encoding="utf-8")
    wave = run("wave", "create", "--project", project_id, "--spec", wave_spec)
    created = run("wave", "run", "--project", project_id, "--wave", wave["id"])
    run_id = created["run"]["id"]
    worker = Worker(1)
    worker.start()
    try:
        final = run("run", "wait", "--project", project_id, "--run", run_id,
                    "--interval", "0.05", "--wait-timeout", "20")
    finally:
        worker.stop()
    assert final["status"] == "done"
    assert run("run", "metrics", "--project", project_id, "--run", run_id)["quality"]["valid_samples"] == 1
    answers = run("run", "answers", "--project", project_id, "--run", run_id)["items"]
    answer = run("answer", "get", "--project", project_id, "--answer", answers[0]["id"])
    for observation in answer["observations"]:
        revision = {key: observation[key] for key in ("entity_status", "mentioned", "depth", "sentiment", "top_choice")}
        revision.update({"evidence": answer["raw_text"], "reason": "CLI 全文人工仲裁", "arbitrate": True})
        path = tmp_path / f"revision-{observation['id']}.json"
        path.write_text(json.dumps(revision), encoding="utf-8")
        run("answer", "revise", "--project", project_id, "--answer", answer["id"],
            "--observation", observation["id"], "--spec", path, "--confirm")
    run("wave", "official", "--project", project_id, "--wave", wave["id"], "--run", run_id, "--confirm")

    opportunities = run("opportunity", "generate", "--project", project_id, "--wave", wave["id"])["items"]
    for opportunity in opportunities:
        review = tmp_path / f"opportunity-{opportunity['id']}.json"
        review.write_text(json.dumps({"decision": "confirmed", "eligibility": "client_confirmed",
                                      "business_value": 3, "executability": 3, "reason": "CLI 确认适用"}), encoding="utf-8")
        run("opportunity", "review", "--project", project_id, "--opportunity", opportunity["id"], "--spec", review, "--confirm")
    report = run("report", "create", "--project", project_id, "--wave-id", wave["id"])
    for status in ("data_checked", "strategy_reviewed", "client_approved"):
        run("report", "status", "--project", project_id, "--report", report["id"],
            "--status", status, "--reason", f"CLI {status}", "--confirm")
    html = run("report", "export", "--project", project_id, "--report", report["id"],
               "--file-format", "html", "--variant", "client", "--out", tmp_path / "client.html")
    assert html["download"]["response_sha256_verified"]
    assert (tmp_path / "client.html").stat().st_mode & 0o777 == 0o600
    pdf = run("report", "export", "--project", project_id, "--report", report["id"],
              "--file-format", "pdf", "--variant", "client", "--out", tmp_path / "client.pdf")
    assert pdf["download"]["response_sha256_verified"]
    assert (tmp_path / "client.pdf").read_bytes().startswith(b"%PDF-")
    assert (tmp_path / "client.pdf").stat().st_mode & 0o777 == 0o600
    exported = run("project", "export", "--project", project_id, "--out", tmp_path / "project.json")
    assert exported["download"]["project_export_sha256_verified"]
    backup = run("admin", "backup", "--project", project_id, "--out", tmp_path / "backup-manifest.json")
    assert backup["delivery"] == "server_side" and "未下载" in backup["note"]
    assert run("retention", "preview", "--project", project_id)["enabled"] is False
    assert run("operations", "--project", project_id)["cost_summary"]["unknown"] is False
    from backend.app.migrations import SCHEMA_VERSION
    assert run("capabilities")["health"]["schema_version"] == SCHEMA_VERSION


def test_real_engine_preflight_never_dispatches_unconfirmed_run(cli_server, tmp_path):
    run = cli_server
    run("auth", "login", "--email", "admin@cli.local", secret=PASSWORD)
    engine_spec = tmp_path / "real-engine.json"
    engine_spec.write_text(json.dumps({"name": "Offline real contract", "vendor": "Test", "kind": "openai_compat",
                                       "model": "offline", "base_url": "https://example.test/v1", "mode": "memory"}), encoding="utf-8")
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"not-a-real-credential")
    os.close(write_fd)
    completed = subprocess.run([sys.executable, str(CTL), "engine", "create", "--project", "1", "--spec", str(engine_spec),
                                "--secret-fd", str(read_fd)], cwd=ROOT, env=run.env, pass_fds=(read_fd,), capture_output=True, text=True)
    os.close(read_fd)
    assert completed.returncode == 0, completed.stderr
    engine = json.loads(completed.stdout)
    wave_spec = tmp_path / "real-wave.json"
    prompt_set = run("prompt-set", "list", "--project", "1")["items"][0]
    wave_spec.write_text(json.dumps({"prompt_set_id": prompt_set["id"], "label": "Unconfirmed real Wave",
                                     "engine_ids": [engine["id"]], "repeats": 1}), encoding="utf-8")
    wave = run("wave", "create", "--project", "1", "--spec", wave_spec)
    result = run("wave", "run", "--project", "1", "--wave", wave["id"], expected=4)
    assert result["error"]["code"] == "run_confirmation_required"
    with connect() as conn:
        assert one(conn, "SELECT COUNT(*) AS count FROM runs WHERE wave_id=?", (wave["id"],))["count"] == 0
    first = run("engine", "health", "--project", "1", "--engine", engine["id"], expected=4)
    assert first["error"]["code"] == "health_confirmation_required"
    second = run("engine", "health", "--project", "1", "--engine", engine["id"], "--confirm", expected=2)
    assert second["error"]["code"] == "estimate_required"


def test_cli_manual_collection_and_evidence_chain(cli_server, tmp_path):
    run = cli_server
    run("auth", "login", "--email", "admin@cli.local", secret=PASSWORD)
    project_id = run("project", "list")["items"][0]["id"]
    judge = run("engine", "list", "--project", project_id)["items"][0]
    target_spec = tmp_path / "manual-target.json"
    target_spec.write_text(json.dumps({"name": "CLI 人工 Web", "vendor": "Manual fixture", "kind": "manual_web",
                                       "base_url": "https://consumer.example.test/chat",
                                       "measurement_target": "consumer_web", "mode": "memory"}), encoding="utf-8")
    target = run("engine", "create", "--project", project_id, "--spec", target_spec)
    prompt_set = run("prompt-set", "list", "--project", project_id)["items"][0]
    protocol = {"product_url": "https://consumer.example.test/chat", "platform": "fixture",
                "surface": "desktop_web", "page_mode": "default", "networking": False,
                "deep_thinking": False, "deep_research": False, "session_mode": "new",
                "login_state": "anonymous", "account_type": "", "region": "CN", "language": "zh-CN",
                "context_clearing": "new_session", "follow_up_policy": "none",
                "protocol_version": "manual-web-v1"}
    wave_spec = tmp_path / "manual-wave.json"
    wave_spec.write_text(json.dumps({"prompt_set_id": prompt_set["id"], "label": "CLI 人工 Wave",
                                     "engine_ids": [target["id"]], "judge_engine_id": judge["id"],
                                     "repeats": 1, "use_judge": True, "collection_protocol": protocol}), encoding="utf-8")
    wave = run("wave", "create", "--project", project_id, "--spec", wave_spec)
    created = run("wave", "run", "--project", project_id, "--wave", wave["id"])
    run_id = created["run"]["id"]
    answers = run("run", "answers", "--project", project_id, "--run", run_id)["items"]
    answer_id = answers[0]["id"]
    context = {key: value for key, value in protocol.items()
               if key not in {"product_url", "platform", "protocol_version"}}
    draft = tmp_path / "collection.json"
    draft.write_text(json.dumps({"draft_text": "GeoPulse 适合证据审计。", "actual_url": protocol["product_url"],
                                 "observed_mode": "default", "observed_at": "2026-11-07T10:00:00+08:00",
                                 "timezone": "Asia/Shanghai", "session_context": context,
                                 "retrieval_status": "off", "notes": "CLI 离线夹具", "citations": [],
                                 "status": "review_pending"}), encoding="utf-8")
    saved = run("collection", "save", "--project", project_id, "--answer", answer_id, "--spec", draft)
    assert saved["status"] == "review_pending"
    png = tmp_path / "evidence.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    attachment = run("evidence", "upload", "--project", project_id, "--answer", answer_id,
                     "--kind", "screenshot", "--filename", "evidence.png", "--media-type", "image/png", "--file", png)
    downloaded = run("evidence", "download", "--project", project_id, "--attachment", attachment["id"],
                     "--out", tmp_path / "downloaded.png")
    assert downloaded["download"]["response_sha256_verified"]
    assert (tmp_path / "downloaded.png").read_bytes() == png.read_bytes()
    run("evidence", "delete", "--project", project_id, "--attachment", attachment["id"], "--confirm")
    attachment = run("evidence", "upload", "--project", project_id, "--answer", answer_id,
                     "--kind", "screenshot", "--filename", "evidence.png", "--media-type", "image/png", "--file", png)
    blocked = run("collection", "submit", "--project", project_id, "--answer", answer_id,
                  "--spec", draft, expected=4)
    assert blocked["error"]["code"] == "confirmation_required"
    submitted = run("collection", "submit", "--project", project_id, "--answer", answer_id,
                    "--spec", draft, "--confirm")
    assert submitted["answer_status"] == "judging"
    worker = Worker(1)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            detail = run("answer", "get", "--project", project_id, "--answer", answer_id)
            if detail["status"] == "succeeded":
                break
            time.sleep(0.05)
        assert detail["status"] == "succeeded" and detail["usage"] == {}
    finally:
        worker.stop()
    collection = run("collection", "get", "--project", project_id, "--answer", answer_id)
    assert collection["status"] == "completed" and collection["attachments"][0]["sha256"] == attachment["sha256"]
    waiting = run("run", "wait", "--project", project_id, "--run", run_id,
                  "--interval", "0.01", "--wait-timeout", "0.05", expected=4)
    assert waiting["error"]["code"] == "wait_timeout"
    failure = tmp_path / "failure.json"
    failure.write_text(json.dumps({"failure_type": "captcha", "failure_detail": "CLI 登记失败"}), encoding="utf-8")
    other_id = answers[1]["id"]
    run("collection", "fail", "--project", project_id, "--answer", other_id, "--spec", failure, expected=4)
    failed = run("collection", "fail", "--project", project_id, "--answer", other_id, "--spec", failure, "--confirm")
    assert failed["answer_status"] == "failed"
    with connect() as conn:
        assert one(conn, "SELECT valid_sample FROM answers WHERE id=?", (other_id,))["valid_sample"] == 0
