"""Single-node authorized browser queue, leases and recovery."""
from __future__ import annotations

import fcntl
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from ..collectors import CollectorError, get_driver
from ..db import all_rows, one, transaction, utc_now
from . import browser_sessions, web_collection
from .measurement import _answer_context, _finalize_run


class ProfileLock:
    def __init__(self, profile: Path):
        self.path = profile / ".geopulse.lock"
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        self.path.chmod(0o600)
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def __exit__(self, *_):
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


class CollectorCancelled(RuntimeError):
    pass


class BrowserWorker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread:
            return
        self.stop_event.clear()
        self.recover()
        self.thread = threading.Thread(target=self._loop, name="geopulse-browser-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.thread = None

    @staticmethod
    def _expiry(seconds: int = 30) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def recover(self) -> None:
        now = utc_now()
        with transaction() as conn:
            rows = all_rows(conn, """SELECT id,browser_phase,browser_send_started_at FROM web_collections
                                     WHERE collection_method='browser_assisted' AND status='collecting'
                                       AND browser_phase NOT IN ('queued','awaiting_user','paused_unknown','completed')
                                       AND (browser_lease_expires_at IS NULL OR browser_lease_expires_at<?)""",
                            (now,))
            for row in rows:
                unknown = bool(row["browser_send_started_at"]) or row["browser_phase"] in (
                    "submitting", "waiting", "extracting", "uploading")
                conn.execute("""UPDATE web_collections SET browser_phase=?,browser_phase_detail=?,
                                browser_lease_owner='',browser_lease_expires_at=NULL,browser_heartbeat_at=NULL,updated_at=?
                                WHERE id=?""",
                             ("paused_unknown" if unknown else "queued",
                              "进程恢复后结果不明；请核对原会话，系统不会自动重发" if unknown else "发送前任务已重新排队",
                              now, row["id"]))

    def _loop(self) -> None:
        next_recovery = time.monotonic() + 15
        while not self.stop_event.is_set():
            try:
                if time.monotonic() >= next_recovery:
                    self.recover()
                    next_recovery = time.monotonic() + 15
                self._cleanup_revoked()
                session = self._next_login()
                if session:
                    self._manage_login(session["id"])
                    continue
                claimed = self._claim()
                if not claimed:
                    self.stop_event.wait(0.25)
                    continue
                self._run_job(claimed["answer_id"], claimed["lease_owner"])
            except Exception:
                # Individual job handlers persist safe states; never print browser/page contents.
                self.stop_event.wait(0.5)

    def _next_login(self) -> dict | None:
        with transaction() as conn:
            return one(conn, """SELECT * FROM browser_sessions
                                WHERE (status='pending' AND (worker_heartbeat_at IS NULL OR verification_requested=1))
                                   OR (status='expired' AND verification_requested=1)
                                ORDER BY id LIMIT 1""")

    def _cleanup_revoked(self) -> None:
        with transaction() as conn:
            rows = all_rows(conn, "SELECT profile_ref FROM browser_sessions WHERE status='revoked'")
        for row in rows:
            path = browser_sessions.profile_path(row["profile_ref"])
            if not path.exists():
                continue
            lock = ProfileLock(path)
            if lock.__enter__():
                try:
                    shutil.rmtree(path)
                finally:
                    lock.__exit__(None, None, None)

    def _launch(self, session: dict):
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        options = {"headless": os.environ.get("GEOPULSE_BROWSER_HEADLESS") == "1",
                   "viewport": {"width": 1280, "height": 900}, "accept_downloads": False}
        if os.environ.get("CHROME_PATH"):
            options["executable_path"] = os.environ["CHROME_PATH"]
        try:
            context = playwright.chromium.launch_persistent_context(
                str(browser_sessions.profile_path(session["profile_ref"])), **options)
        except Exception:
            playwright.stop()
            raise
        context.set_default_timeout(10000)
        return playwright, context

    def configure_context(self, context, driver_class) -> None:
        def guard(request):
            if request.resource_type == "document":
                from urllib.parse import urlparse
                parsed = urlparse(request.url)
                if parsed.scheme != "https" or (parsed.hostname or "").lower() not in driver_class.origins:
                    request.abort()
                    return
            request.continue_()
        context.route("**/*", guard)

    def _manage_login(self, session_id: int) -> None:
        with transaction() as conn:
            session = one(conn, "SELECT * FROM browser_sessions WHERE id=? AND status IN ('pending','expired')", (session_id,))
        if not session:
            return
        profile = browser_sessions.profile_path(session["profile_ref"])
        lock = ProfileLock(profile)
        if not lock.__enter__():
            with transaction() as conn:
                conn.execute("UPDATE browser_sessions SET worker_heartbeat_at=?,last_error=? WHERE id=?",
                             (utc_now(), "会话正由另一个本机采集器使用", session_id))
            lock.__exit__(None, None, None)
            self.stop_event.wait(1)
            return
        playwright = context = None
        try:
            driver_class = get_driver(session["driver"])
            playwright, context = self._launch(session)
            self.configure_context(context, driver_class)
            page = context.pages[0] if context.pages else context.new_page()
            engine = self._engine(session["engine_config_id"])
            driver = driver_class(page, engine["base_url"], {}, engine.get("timezone") or "Asia/Shanghai")
            try:
                driver.open_product()
            except CollectorError as error:
                self._session_error(session_id, error.detail)
                return
            deadline = datetime.now(timezone.utc) + timedelta(minutes=30)
            while not self.stop_event.is_set() and datetime.now(timezone.utc) < deadline:
                with transaction() as conn:
                    current = one(conn, "SELECT * FROM browser_sessions WHERE id=?", (session_id,))
                    if not current or current["status"] == "revoked":
                        return
                    conn.execute("UPDATE browser_sessions SET worker_heartbeat_at=?,updated_at=? WHERE id=?",
                                 (utc_now(), utc_now(), session_id))
                    verify = bool(current["verification_requested"])
                if verify:
                    try:
                        driver.check_session()
                    except CollectorError as error:
                        self._session_error(session_id, error.detail)
                    else:
                        with transaction() as conn:
                            now = utc_now()
                            conn.execute("""UPDATE browser_sessions SET status='active',verification_requested=0,
                                            last_verified_at=?,worker_heartbeat_at=?,last_error='',updated_at=? WHERE id=?""",
                                         (now, now, now, session_id))
                        return
                self.stop_event.wait(1)
            if datetime.now(timezone.utc) >= deadline:
                self._session_error(session_id, "登录验证等待已结束；完成登录后请重新点击验证")
        finally:
            if context:
                context.close()
            if playwright:
                playwright.stop()
            lock.__exit__(None, None, None)

    def _engine(self, engine_id: int) -> dict:
        with transaction() as conn:
            return one(conn, """SELECT e.*,p.timezone FROM engine_configs e
                               JOIN projects p ON p.id=e.project_id WHERE e.id=?""", (engine_id,)) or {}

    def _session_error(self, session_id: int, detail: str) -> None:
        with transaction() as conn:
            conn.execute("""UPDATE browser_sessions SET verification_requested=0,last_error=?,worker_heartbeat_at=?,updated_at=?
                            WHERE id=?""", (detail[:300], utc_now(), utc_now(), session_id))

    def _claim(self) -> dict | None:
        owner = uuid.uuid4().hex
        with transaction() as conn:
            now = utc_now()
            claimable = "(browser_lease_owner='' OR browser_lease_expires_at IS NULL OR browser_lease_expires_at<=?)"
            row = one(conn, f"""SELECT c.id,c.answer_id FROM web_collections c
                               JOIN answers a ON a.id=c.answer_id JOIN runs r ON r.id=a.run_id
                               JOIN browser_sessions s ON s.id=c.browser_session_id
                               WHERE c.collection_method='browser_assisted' AND c.status='collecting'
                                 AND c.browser_phase='queued' AND a.status='awaiting_collection'
                                 AND r.cancel_requested=0 AND r.status IN ('queued','running') AND s.status='active'
                                 AND {claimable}
                               ORDER BY c.answer_id LIMIT 1""", (now,))
            if not row:
                return None
            updated = conn.execute(f"""UPDATE web_collections SET browser_lease_owner=?,browser_lease_expires_at=?,
                            browser_heartbeat_at=?,browser_attempt_count=browser_attempt_count+1,
                            browser_phase='preparing',browser_phase_detail='',updated_at=?
                            WHERE id=? AND browser_phase='queued' AND {claimable}""",
                         (owner, self._expiry(), now, now, row["id"], now)).rowcount
            if not updated:
                return None
            return {"answer_id": row["answer_id"], "lease_owner": owner}

    def _heartbeat(self, answer_id: int, owner: str) -> None:
        with transaction() as conn:
            updated = conn.execute("""UPDATE web_collections SET browser_heartbeat_at=?,browser_lease_expires_at=?,updated_at=?
                                      WHERE answer_id=? AND browser_lease_owner=? AND status='collecting'""",
                                   (utc_now(), self._expiry(), utc_now(), answer_id, owner)).rowcount
        if not updated:
            raise CollectorCancelled()

    def _phase(self, answer_id: int, owner: str, phase: str, detail: str = "") -> None:
        with transaction() as conn:
            state = one(conn, """SELECT a.status,r.cancel_requested,s.status AS session_status
                                 FROM answers a JOIN runs r ON r.id=a.run_id
                                 JOIN web_collections c ON c.answer_id=a.id
                                 LEFT JOIN browser_sessions s ON s.id=c.browser_session_id WHERE a.id=?""",
                        (answer_id,))
            if (not state or state["status"] != "awaiting_collection" or state["cancel_requested"]
                    or state["session_status"] != "active"):
                raise CollectorCancelled()
            updated = conn.execute("""UPDATE web_collections SET browser_phase=?,browser_phase_detail=?,
                                      browser_heartbeat_at=?,browser_lease_expires_at=?,updated_at=?
                                      WHERE answer_id=? AND browser_lease_owner=?""",
                                   (phase, detail, utc_now(), self._expiry(), utc_now(), answer_id, owner)).rowcount
            if not updated:
                raise CollectorCancelled()

    def _run_job(self, answer_id: int, owner: str) -> None:
        with transaction() as conn:
            collection = one(conn, "SELECT * FROM web_collections WHERE answer_id=?", (answer_id,))
            session = one(conn, "SELECT * FROM browser_sessions WHERE id=?", (collection["browser_session_id"],))
        context_data = _answer_context_from_worker(answer_id)
        profile = browser_sessions.profile_path(session["profile_ref"])
        lock = ProfileLock(profile)
        if not lock.__enter__():
            with transaction() as conn:
                conn.execute("""UPDATE web_collections SET browser_lease_owner='',browser_lease_expires_at=NULL,
                                browser_phase='queued',browser_phase_detail='会话正由另一个采集器使用，稍后重试'
                                WHERE answer_id=? AND browser_lease_owner=?""", (answer_id, owner))
            lock.__exit__(None, None, None)
            self.stop_event.wait(1)
            return
        playwright = context = None
        sent = bool(collection.get("browser_send_started_at"))
        try:
            driver_class = get_driver(collection["browser_driver"])
            playwright, context = self._launch(session)
            self.configure_context(context, driver_class)
            page = context.pages[0] if context.pages else context.new_page()
            protocol = context_data["protocol"].get("collection_protocol") or {}
            driver = driver_class(page, context_data["engine"]["base_url"], protocol,
                                  context_data.get("project_timezone") or "Asia/Shanghai",
                                  int(context_data["engine"].get("timeout") or 180))
            driver.heartbeat = lambda: self._heartbeat(answer_id, owner)
            if sent:
                self._phase(answer_id, owner, "waiting", "仅恢复已发送的原会话，不重发问题")
                driver.resume_conversation(collection["conversation_url"])
                driver.check_session()
            else:
                self._phase(answer_id, owner, "session_check")
                driver.prepare_new_chat()
                self._phase(answer_id, owner, "preparing")
                driver.apply_frozen_mode()
                self._phase(answer_id, owner, "submitting", "冻结问题即将发送；此阶段崩溃不会自动重发")
                with transaction() as conn:
                    conn.execute("UPDATE web_collections SET browser_send_started_at=?,updated_at=? WHERE answer_id=?",
                                 (utc_now(), utc_now(), answer_id))
                sent = True
                driver.submit_prompt(context_data["prompt"]["text"])
                with transaction() as conn:
                    conn.execute("""UPDATE web_collections SET prompt_submitted_at=?,conversation_url=?,updated_at=?
                                    WHERE answer_id=?""",
                                 (utc_now(), driver.conversation_url(), utc_now(), answer_id))
            self._phase(answer_id, owner, "waiting")
            driver.wait_for_completion()
            self._phase(answer_id, owner, "extracting")
            capture = driver.extract_result()
            with transaction() as conn:
                conn.execute("UPDATE web_collections SET conversation_url=?,updated_at=? WHERE answer_id=?",
                             (driver.conversation_url(), utc_now(), answer_id))
            self._phase(answer_id, owner, "uploading")
            actor = collection.get("browser_requested_by") or session["authorized_by"]
            attempt = collection["browser_attempt_count"]
            if any(not content or len(content) > web_collection.MAX_ATTACHMENT_BYTES
                   for content in (capture.screenshot, capture.html)):
                raise CollectorError("evidence_too_large", "回答区域截图或 HTML 为空，或超过 10MB 证据上限；未提交回答")
            with transaction() as conn:
                project = {"id": context_data["project_id"], "client_id": context_data["client_id"]}
                web_collection.upload_attachment(conn, project, answer_id, "screenshot",
                    f"run-{context_data['run_id']}-answer-{answer_id}-attempt-{attempt}.png",
                    "image/png", capture.screenshot, "", actor, allow_browser=True)
                web_collection.upload_attachment(conn, project, answer_id, "raw_html",
                    f"run-{context_data['run_id']}-answer-{answer_id}-attempt-{attempt}.html",
                    "text/html", capture.html, "", actor, allow_browser=True)
                web_collection.submit_collection(conn, project, answer_id, capture.payload, actor,
                                                 allow_browser=True)
                conn.execute("""UPDATE web_collections SET browser_phase='completed',browser_phase_detail='',
                                browser_lease_owner='',browser_lease_expires_at=NULL,browser_heartbeat_at=?,updated_at=?
                                WHERE answer_id=?""", (utc_now(), utc_now(), answer_id))
        except CollectorCancelled:
            with transaction() as conn:
                conn.execute("""UPDATE web_collections SET browser_lease_owner='',browser_lease_expires_at=NULL
                                WHERE answer_id=? AND browser_lease_owner=?""", (answer_id, owner))
        except CollectorError as error:
            self._job_error(answer_id, owner, error, sent)
        except Exception:
            self._job_error(answer_id, owner, CollectorError("other", "浏览器采集进程异常，未形成有效样本"), sent)
        finally:
            if context:
                context.close()
            if playwright:
                playwright.stop()
            lock.__exit__(None, None, None)

    def _job_error(self, answer_id: int, owner: str, error: CollectorError, sent: bool) -> None:
        with transaction() as conn:
            answer = one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,))
            collection = one(conn, "SELECT * FROM web_collections WHERE answer_id=?", (answer_id,))
            if not answer or answer["status"] != "awaiting_collection" or not collection:
                return
            if error.user_action:
                conn.execute("""UPDATE web_collections SET browser_phase='awaiting_user',browser_phase_detail=?,
                                browser_lease_owner='',browser_lease_expires_at=NULL,browser_heartbeat_at=?,updated_at=?
                                WHERE answer_id=?""", (error.detail[:500], utc_now(), utc_now(), answer_id))
                if error.kind in ("login_expired", "captcha"):
                    conn.execute("UPDATE browser_sessions SET status='expired',last_error=?,updated_at=? WHERE id=?",
                                 (error.detail[:300], utc_now(), collection["browser_session_id"]))
                return
            if sent and error.kind in ("stream_interrupted", "other"):
                conn.execute("""UPDATE web_collections SET browser_phase='paused_unknown',browser_phase_detail=?,
                                browser_lease_owner='',browser_lease_expires_at=NULL,browser_heartbeat_at=?,updated_at=?
                                WHERE answer_id=?""", (error.detail[:500], utc_now(), utc_now(), answer_id))
                return
            failure_type = error.kind if error.kind in (
                "captcha", "login_expired", "empty", "truncated", "error_page", "stream_interrupted") else "other"
            project = {"id": answer["project_id"], "client_id": answer["client_id"]}
            web_collection.fail_collection(conn, project, answer_id, {
                "failure_type": failure_type, "failure_detail": error.detail[:1000],
                "notes": "授权浏览器采集失败；未自动重发问题",
            }, collection.get("browser_requested_by"))
            conn.execute("""UPDATE web_collections SET browser_phase='failed',browser_lease_owner='',
                            browser_lease_expires_at=NULL,browser_heartbeat_at=?,updated_at=? WHERE answer_id=?""",
                         (utc_now(), utc_now(), answer_id))


def _answer_context_from_worker(answer_id: int) -> dict:
    with transaction() as conn:
        context = _answer_context(conn, answer_id)
        if context:
            project = one(conn, "SELECT timezone FROM projects WHERE id=?", (context["project_id"],))
            context["project_timezone"] = project["timezone"] if project else "Asia/Shanghai"
        return context
