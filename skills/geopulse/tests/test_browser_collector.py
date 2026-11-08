from __future__ import annotations

import base64
import copy

import pytest

from backend.app.collectors.base import BrowserCapture, CollectorError
from backend.app.db import connect, one
from backend.app.services import browser_worker
from backend.app.services.browser_worker import BrowserWorker
from backend.app.services.measurement import Worker
from conftest import api, execute_run
from test_manual_web import COLLECTION_PROTOCOL, PRODUCT_URL, manual_run, single_prompt_set, upload

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class DummyContext:
    def __init__(self):
        self.pages = [object()]

    def new_page(self):
        return object()

    def close(self):
        pass


class DummyPlaywright:
    def stop(self):
        pass


class FakeDriver:
    version = "fixture-1"
    origins = frozenset({"consumer.example.test"})
    prompts = []
    resumes = []
    failure = ""
    on_submit = None

    def __init__(self, page, product_url, protocol, timezone, timeout=180):
        self.protocol = protocol
        self.product_url = product_url
        self.timezone = timezone
        self.heartbeat = lambda: None

    def open_product(self):
        pass

    def check_session(self):
        if self.failure == "login":
            raise CollectorError("login_expired", "请重新登录测试账号", user_action=True)
        if self.failure == "captcha":
            raise CollectorError("captcha", "请完成安全验证", user_action=True)

    def prepare_new_chat(self):
        self.check_session()

    def apply_frozen_mode(self):
        pass

    def submit_prompt(self, prompt):
        if self.failure == "crash":
            raise RuntimeError("simulated crash")
        self.prompts.append(prompt)
        if self.on_submit:
            self.on_submit()

    def wait_for_completion(self):
        pass

    def resume_conversation(self, url):
        self.resumes.append(url)

    def conversation_url(self):
        return PRODUCT_URL + "/conversation/123"

    def extract_result(self):
        if self.failure == "empty":
            raise CollectorError("empty", "fixture empty")
        context = {key: value for key, value in self.protocol.items()
                   if key not in {"product_url", "platform", "protocol_version", "collection_method", "browser_driver"}}
        payload = {
            "draft_text": "这是授权浏览器夹具采集的完整回答。",
            "actual_url": self.conversation_url(), "observed_mode": "default",
            "observed_at": "2026-11-08T10:00:00+08:00", "timezone": "Asia/Shanghai",
            "session_context": context, "retrieval_status": "off", "notes": "离线 fixture",
            "citations": [{"url": "https://docs.example.test/evidence", "title": "网页引用", "text": "证据"}],
            "status": "review_pending",
        }
        return BrowserCapture(payload, PNG, b"x" * (10 * 1024 * 1024 + 1) if self.failure == "oversize" else b"<div>fixture answer</div>")


@pytest.fixture
def fake_browser(monkeypatch):
    FakeDriver.prompts = []
    FakeDriver.resumes = []
    FakeDriver.failure = ""
    FakeDriver.on_submit = None
    monkeypatch.setattr(browser_worker, "get_driver", lambda key: FakeDriver)
    monkeypatch.setattr(BrowserWorker, "_launch", lambda self, session: (DummyPlaywright(), DummyContext()))
    monkeypatch.setattr(BrowserWorker, "configure_context", lambda self, context, driver: None)
    return FakeDriver


def browser_wave(client, driver="deepseek_web"):
    project = client.project_id
    existing = api(client, "GET", f"/api/projects/{project}/engines")["items"]
    target = api(client, "POST", f"/api/projects/{project}/engines", json={
        "name": f"授权浏览器 Consumer Web 夹具 {driver}", "vendor": "Browser fixture", "kind": "manual_web",
        "base_url": PRODUCT_URL, "measurement_target": "consumer_web", "mode": "memory"})
    judge = next(item for item in existing if item["kind"] == "demo")
    protocol = copy.deepcopy(COLLECTION_PROTOCOL) | {
        "collection_method": "browser_assisted", "browser_driver": driver,
        "protocol_version": "browser-web-v1", "login_state": "logged_in",
    }
    wave = api(client, "POST", f"/api/projects/{project}/waves", json={
        "prompt_set_id": single_prompt_set(client), "label": "授权浏览器 Wave",
        "engine_ids": [target["id"]], "judge_engine_id": judge["id"], "repeats": 1,
        "use_judge": True, "collection_protocol": protocol})
    return target, wave


def activate_session(client, target_id, driver="deepseek_web"):
    project = client.project_id
    session = api(client, "POST", f"/api/projects/{project}/engines/{target_id}/browser-sessions",
                  json={"driver": driver})
    assert "profile_ref" not in session and session["status"] == "pending"
    with connect() as conn:
        conn.execute("UPDATE browser_sessions SET status='active',last_verified_at=updated_at WHERE id=?", (session["id"],))
        conn.commit()
    return session


def browser_run(client, target, wave):
    project = client.project_id
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/runs",
        json={"confirm_browser": False}, expected=409)
    run = api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/runs",
              json={"confirm_browser": True})["run"]
    answer = api(client, "GET", f"/api/projects/{project}/runs/{run['id']}/answers")["items"][0]
    return run, answer


def run_one_job(worker, answer_id):
    claimed = worker._claim()
    assert claimed and claimed["answer_id"] == answer_id
    worker._run_job(answer_id, claimed["lease_owner"])


def test_browser_claim_is_exclusive_across_workers(client, fake_browser):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    first = BrowserWorker()
    second = BrowserWorker()
    job = first._claim()
    assert job and job["answer_id"] == answer["id"]
    assert second._claim() is None
    with connect() as conn:
        claimed = one(conn, """SELECT browser_lease_owner,browser_attempt_count,browser_phase
                              FROM web_collections WHERE answer_id=?""", (answer["id"],))
    assert claimed == {"browser_lease_owner": job["lease_owner"],
                       "browser_attempt_count": 1, "browser_phase": "preparing"}
    first._run_job(answer["id"], job["lease_owner"])
    assert FakeDriver.prompts == ["哪些 GEO 工具适合证据审计？"]
    assert execute_run(client, run["id"]) == "done"


def test_browser_profile_lock_contention_requeues_claim(client, fake_browser, monkeypatch):
    class BusyLock:
        def __init__(self, profile):
            pass
        def __enter__(self):
            return False
        def __exit__(self, *_):
            pass

    monkeypatch.setattr(browser_worker, "ProfileLock", BusyLock)
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    _run, answer = browser_run(client, target, wave)
    worker = BrowserWorker()
    job = worker._claim()
    worker._run_job(answer["id"], job["lease_owner"])
    with connect() as conn:
        queued = one(conn, """SELECT browser_lease_owner,browser_phase,browser_attempt_count
                             FROM web_collections WHERE answer_id=?""", (answer["id"],))
    assert queued == {"browser_lease_owner": "", "browser_phase": "queued", "browser_attempt_count": 1}
    assert worker._claim()["answer_id"] == answer["id"]
    assert FakeDriver.prompts == []


def test_browser_collection_submits_evidence_without_provider_answer_calls(client, fake_browser):
    target, wave = browser_wave(client)
    assert wave["estimate"]["note"].startswith("授权浏览器不产生 Provider")
    project = client.project_id
    api(client, "POST", f"/api/projects/{project}/waves/{wave['id']}/runs",
        json={"confirm_browser": True}, expected=409)
    session = activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    collection = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "queued" and collection["collection_method"] == "browser_assisted"
    assert "browser_session_id" not in collection and "browser_lease_owner" not in collection
    api(client, "PUT", f"/api/projects/{project}/answers/{answer['id']}/collection/draft", json={}, expected=409)
    upload(client, answer["id"], expected=409)

    worker = BrowserWorker()
    run_one_job(worker, answer["id"])
    assert FakeDriver.prompts == ["哪些 GEO 工具适合证据审计？"]
    assert execute_run(client, run["id"]) == "done"
    detail = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}")
    assert detail["raw_text"] == "这是授权浏览器夹具采集的完整回答。"
    assert [item["kind"] for item in detail["call_attempts"]] == ["judge"]
    assert all(item["origin"] == "browser_page" for item in detail["citations"])
    collection = api(client, "GET", f"/api/projects/{project}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "completed"
    assert {item["kind"] for item in collection["attachments"]} == {"screenshot", "raw_html"}
    exported = api(client, "GET", f"/api/projects/{project}/export")
    assert "browser_sessions" not in exported["tables"]
    exported_collection = exported["tables"]["web_collections"][0]
    assert "profile_ref" not in exported_collection and "browser_session_id" not in exported_collection
    revoked = api(client, "POST", f"/api/projects/{project}/browser-sessions/{session['id']}/revoke")
    assert revoked["status"] == "revoked" and "profile_ref" not in revoked


def test_crash_after_send_pauses_and_resume_never_resends(client, fake_browser):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    with connect() as conn:
        conn.execute("""UPDATE web_collections SET browser_phase='submitting',browser_send_started_at=updated_at,
                        prompt_submitted_at=updated_at,conversation_url=?,browser_lease_expires_at='2000-01-01T00:00:00+00:00'
                        WHERE answer_id=?""", (PRODUCT_URL + "/conversation/123", answer["id"]))
        conn.commit()
    worker = BrowserWorker()
    worker.recover()
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "paused_unknown"
    resumed = api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/resume",
                  json={"action": "resume"})
    assert resumed["browser_phase"] == "queued"
    run_one_job(worker, answer["id"])
    assert FakeDriver.prompts == [] and FakeDriver.resumes == [PRODUCT_URL + "/conversation/123"]
    assert execute_run(client, run["id"]) == "done"


def test_unknown_without_conversation_can_only_fail_and_login_pauses(client, fake_browser):
    target, wave = browser_wave(client)
    session = activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    with connect() as conn:
        conn.execute("""UPDATE web_collections SET browser_phase='paused_unknown',browser_send_started_at=updated_at,
                        conversation_url='' WHERE answer_id=?""", (answer["id"],))
        conn.commit()
    api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/resume",
        json={"action": "resume"}, expected=409)
    failed = api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/resume",
                 json={"action": "fail", "detail": "无法确认是否发送"})
    assert failed["answer_status"] == "failed"
    with connect() as conn:
        assert one(conn, "SELECT valid_sample FROM answers WHERE id=?", (answer["id"],))["valid_sample"] == 0

    target2, wave2 = browser_wave(client, driver="kimi_web")
    session2 = activate_session(client, target2["id"], driver="kimi_web")
    run2, answer2 = browser_run(client, target2, wave2)
    FakeDriver.failure = "login"
    worker = BrowserWorker()
    run_one_job(worker, answer2["id"])
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer2['id']}/collection")
    assert collection["browser_phase"] == "awaiting_user"
    sessions = api(client, "GET", f"/api/projects/{client.project_id}/engines/{target2['id']}/browser-sessions")["items"]
    assert sessions[0]["status"] == "expired"
    FakeDriver.failure = ""
    api(client, "POST", f"/api/projects/{client.project_id}/browser-sessions/{session2['id']}/verify", json={})
    assert worker._next_login()["id"] == session2["id"]
    worker._manage_login(session2["id"])
    sessions = api(client, "GET", f"/api/projects/{client.project_id}/engines/{target2['id']}/browser-sessions")["items"]
    assert sessions[0]["status"] == "active"
    api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer2['id']}/collection/resume",
        json={"action": "resume"})
    run_one_job(worker, answer2["id"])
    assert execute_run(client, run2["id"]) == "done"


def test_captcha_pauses_session_and_requires_verification_before_more_jobs(client, fake_browser):
    target, wave = browser_wave(client)
    session = activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    browser_run(client, target, wave)
    FakeDriver.failure = "captcha"
    worker = BrowserWorker()
    run_one_job(worker, answer["id"])
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "awaiting_user"
    sessions = api(client, "GET", f"/api/projects/{client.project_id}/engines/{target['id']}/browser-sessions")["items"]
    assert sessions[0]["status"] == "expired"
    assert worker._claim() is None


def test_cancel_during_browser_action_preserves_no_valid_sample(client, fake_browser):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    FakeDriver.on_submit = staticmethod(lambda: api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/cancel", json={}))
    run_one_job(BrowserWorker(), answer["id"])
    detail = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}")
    assert detail["status"] == "cancelled" and detail["valid_sample"] == 0 and detail["raw_text"] is None
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["status"] == "failed" and collection["failure_type"] == "cancelled"
    assert collection["attachments"] == []


def test_evidence_submission_rolls_back_all_attachments_and_raw_text(client, fake_browser, monkeypatch):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    original = browser_worker.web_collection.upload_attachment

    def fail_html(*args, **kwargs):
        if args[3] == "raw_html":
            raise RuntimeError("simulated evidence write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(browser_worker.web_collection, "upload_attachment", fail_html)
    run_one_job(BrowserWorker(), answer["id"])
    with connect() as conn:
        row = one(conn, "SELECT raw_text,valid_sample FROM answers WHERE id=?", (answer["id"],))
        assert row["raw_text"] is None and row["valid_sample"] is None
        assert one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=?", (answer["id"],))["count"] == 0
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "paused_unknown" and collection["citations"] == []


def test_oversize_evidence_fails_explicitly_without_submission(client, fake_browser):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    FakeDriver.failure = "oversize"
    run_one_job(BrowserWorker(), answer["id"])
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "failed" and "10MB" in collection["failure_detail"]
    assert collection["answer_status"] == "failed" and collection["attachments"] == []
    with connect() as conn:
        assert one(conn, "SELECT valid_sample FROM answers WHERE id=?", (answer["id"],))["valid_sample"] == 0


def test_pre_submit_expired_lease_requeues_but_post_submit_pauses(client, fake_browser):
    target, wave = browser_wave(client)
    activate_session(client, target["id"])
    run, answer = browser_run(client, target, wave)
    with connect() as conn:
        conn.execute("""UPDATE web_collections SET browser_phase='preparing',browser_lease_expires_at='2000-01-01T00:00:00+00:00'
                        WHERE answer_id=?""", (answer["id"],))
        conn.commit()
    worker = BrowserWorker()
    worker.recover()
    collection = api(client, "GET", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection")
    assert collection["browser_phase"] == "queued"
    run_one_job(worker, answer["id"])
    assert FakeDriver.prompts == ["哪些 GEO 工具适合证据审计？"]
    assert execute_run(client, run["id"]) == "done"


def test_post_submission_retry_preserves_raw_answer_and_evidence(client):
    target, judge, wave, run, answer = manual_run(client)
    upload(client, answer["id"])
    submitted = api(client, "POST", f"/api/projects/{client.project_id}/answers/{answer['id']}/collection/submit",
                    json={
                        "draft_text": "不可覆盖的原始回答", "actual_url": PRODUCT_URL + "/conversation/123",
                        "observed_mode": "default", "observed_at": "2026-11-07T10:00:00+08:00",
                        "timezone": "Asia/Shanghai", "session_context": {
                            key: value for key, value in COLLECTION_PROTOCOL.items()
                            if key not in {"product_url", "platform", "protocol_version"}},
                        "retrieval_status": "off", "citations": [], "status": "review_pending"})
    with connect() as conn:
        before = one(conn, "SELECT raw_text,raw_text_sha256 FROM answers WHERE id=?", (answer["id"],))
        conn.execute("UPDATE answers SET status='failed',valid_sample=0,error_type='judge_failed' WHERE id=?", (answer["id"],))
        conn.execute("UPDATE runs SET status='failed' WHERE id=?", (run["id"],))
        conn.commit()
    api(client, "POST", f"/api/projects/{client.project_id}/runs/{run['id']}/retry", json={})
    with connect() as conn:
        after = one(conn, "SELECT status,raw_text,raw_text_sha256 FROM answers WHERE id=?", (answer["id"],))
        assert after["status"] == "judging" and after["raw_text"] == before["raw_text"]
        assert after["raw_text_sha256"] == before["raw_text_sha256"]
        assert one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=?", (answer["id"],))["count"] == 1
        assert one(conn, "SELECT status FROM web_collections WHERE answer_id=?", (answer["id"],))["status"] == "completed"
    assert execute_run(client, run["id"]) == "done"
