"""Recoverable wave scheduling and evidence-qualified alert evaluation."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ..db import all_rows, connect, loads, one, transaction, utc_now
from ..engine.compare import compare_metrics
from ..engine.metrics import calculate_metrics
from .measurement import create_run, load_run_samples
from .retention import run_due_retention

logger = logging.getLogger(__name__)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _alert(conn, project: dict, wave_id: int | None, kind: str, message: str,
           severity: str = "warning", dedupe_key: str | None = None) -> None:
    key = dedupe_key or f"{kind}:{wave_id or 0}:{message}"
    exists = one(conn, "SELECT id FROM alerts WHERE project_id=? AND dedupe_key=? AND status='open'",
                 (project["id"], key))
    now = utc_now()
    if exists:
        conn.execute("UPDATE alerts SET message=?,severity=?,updated_at=? WHERE id=?",
                     (message, severity, now, exists["id"]))
        return
    conn.execute("INSERT INTO alerts(client_id,project_id,wave_id,kind,severity,message,dedupe_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (project["client_id"], project["id"], wave_id, kind, severity, message, key, now, now))


def evaluate_project_alerts(conn, project: dict) -> None:
    settings = loads(project["settings_json"], {})
    waves = all_rows(conn, "SELECT * FROM waves WHERE project_id=? AND official_run_id IS NOT NULL ORDER BY id DESC LIMIT 2", (project["id"],))
    metrics = []
    for wave in waves:
        run = one(conn, "SELECT * FROM runs WHERE id=?", (wave["official_run_id"],))
        samples, context = load_run_samples(conn, run)
        value = calculate_metrics(samples, context["primary_id"], loads(wave["stats_json"], {}))
        metrics.append((wave, value))
        quality = value["quality"]
        if quality["valid_sample_rate"]["value"] < 90:
            _alert(conn, project, wave["id"], "sample_completeness",
                   f"Wave {wave['label']} 有效样本率低于 90%，请检查失败样本",
                   dedupe_key=f"sample-completeness:{wave['id']}")
        if quality["valid_samples"] < int(settings.get("small_sample_n", 30)):
            _alert(conn, project, wave["id"], "sample_size",
                   f"Wave {wave['label']} 仅有 {quality['valid_samples']} 个有效样本，只展示计数与方向",
                   dedupe_key=f"sample-size:{wave['id']}")
        if quality["judge_fallback_rate"]["value"] > 20:
            _alert(conn, project, wave["id"], "judge_fallback",
                   f"Wave {wave['label']} Judge 降级率超过 20%，请复核判定质量",
                   dedupe_key=f"judge-fallback:{wave['id']}")
    for engine in all_rows(conn, "SELECT id,name FROM engine_configs WHERE project_id=?", (project["id"],)):
        attempts = all_rows(conn, "SELECT status FROM call_attempts WHERE project_id=? AND engine_config_id=? ORDER BY id DESC LIMIT 3",
                            (project["id"], engine["id"]))
        key = f"engine-failure:{engine['id']}"
        if len(attempts) == 3 and all(row["status"] == "failed" for row in attempts):
            _alert(conn, project, None, "engine_failure", f"引擎 {engine['name']} 最近连续 3 次调用失败，请检查配置与账号状态",
                   dedupe_key=key)
        elif attempts and attempts[0]["status"] == "succeeded":
            conn.execute("UPDATE alerts SET status='resolved',resolved_at=?,updated_at=? WHERE project_id=? AND dedupe_key=? AND status='open'",
                         (utc_now(), utc_now(), project["id"], key))
    if len(metrics) < 2:
        return
    (current_wave, current), (baseline_wave, baseline) = metrics
    threshold = float(loads(current_wave["stats_json"], {}).get("min_pair_completeness", 0.9))
    comparison = compare_metrics(baseline, current, loads(baseline_wave["protocol_json"], {}),
                                 loads(current_wave["protocol_json"], {}), threshold)
    minimum = int(settings.get("small_sample_n", 30))
    if not comparison.get("comparable") or min(current["quality"]["valid_samples"],
                                               baseline["quality"]["valid_samples"]) < minimum:
        return
    delta_limit = float(settings.get("alert_delta_pp", 20))
    negative_delta = current["negative_risk_rate"]["value"] - baseline["negative_risk_rate"]["value"]
    if negative_delta >= delta_limit:
        _alert(conn, project, current_wave["id"], "negative_change",
               f"主品牌负面率同口径对比上升 {negative_delta:.1f}pp，请人工核查原文",
               dedupe_key=f"negative-change:{baseline_wave['id']}:{current_wave['id']}")
    before = {item["brand_entity_id"]: item["sov"] for item in baseline["competitors"]}
    for competitor in current["competitors"]:
        delta = competitor["sov"] - before.get(competitor["brand_entity_id"], 0)
        if competitor["role"] == "competitor" and delta >= delta_limit:
            _alert(conn, project, current_wave["id"], "competitor_change",
                   f"{competitor['name']} SoV 同口径对比上升 {delta:.1f}pp，仅作观察提醒",
                   dedupe_key=f"competitor-change:{baseline_wave['id']}:{current_wave['id']}:{competitor['brand_entity_id']}")


def _advance(schedule: dict, now: datetime) -> tuple[str, str]:
    planned = parse_time(schedule.get("next_run_at") or schedule["scheduled_at"])
    days = schedule.get("recurrence_days")
    if not days:
        return "done", iso(planned)
    while planned <= now:
        planned += timedelta(days=int(days))
    return "pending", iso(planned)


def _schedule_failed(schedule: dict, error: Exception) -> None:
    with transaction() as conn:
        current = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule["id"],))
        if not current:
            return
        project = one(conn, "SELECT * FROM projects WHERE id=?", (current["project_id"],))
        detail = error.detail if isinstance(error, HTTPException) else None
        code = detail.get("code") if isinstance(detail, dict) else ""
        message = (detail.get("message") if isinstance(detail, dict) else str(detail or error))[:1000]
        attempts = int(current["attempt_count"] or 0) + 1
        budget_blocked = code in ("budget_exceeded", "budget_cost_unknown", "budget_confirmation_required")
        status = "blocked" if budget_blocked else "pending"
        retry_at = None if budget_blocked else iso(datetime.now(timezone.utc) + timedelta(seconds=min(3600, 60 * 2 ** min(attempts, 6))))
        conn.execute("UPDATE schedules SET status=?,last_error=?,attempt_count=?,next_retry_at=?,updated_at=? WHERE id=?",
                     (status, message, attempts, retry_at, utc_now(), current["id"]))
        _alert(conn, project, current["wave_id"], "schedule_failed" if not budget_blocked else "budget",
               f"调度 {current['id']}：{message}", dedupe_key=f"schedule-error:{current['id']}:{code or type(error).__name__}")


def run_due_schedules() -> int:
    created = 0
    now = datetime.now(timezone.utc)
    with connect() as conn:
        due = all_rows(conn, """SELECT id FROM schedules WHERE status='pending'
            AND COALESCE(next_run_at,scheduled_at)<=? AND (next_retry_at IS NULL OR next_retry_at<=?) ORDER BY id""",
                       (iso(now), iso(now)))
    for item in due:
        schedule = None
        try:
            with transaction() as conn:
                schedule = one(conn, "SELECT * FROM schedules WHERE id=? AND status='pending'", (item["id"],))
                if not schedule:
                    continue
                claimed = conn.execute("UPDATE schedules SET status='running',updated_at=? WHERE id=? AND status='pending'",
                                       (utc_now(), schedule["id"]))
                if not claimed.rowcount:
                    continue
                active = one(conn, "SELECT id FROM runs WHERE wave_id=? AND status IN ('queued','running')",
                             (schedule["wave_id"],))
                if active:
                    conn.execute("UPDATE schedules SET status='pending',next_retry_at=?,updated_at=? WHERE id=?",
                                 (iso(now + timedelta(minutes=1)), utc_now(), schedule["id"]))
                    continue
                project = one(conn, "SELECT * FROM projects WHERE id=?", (schedule["project_id"],))
                wave = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=?", (schedule["wave_id"], project["id"]))
                run = create_run(project, wave, None, conn=conn)
                status, next_run = _advance(schedule, now)
                conn.execute("UPDATE schedules SET status=?,last_run_id=?,next_run_at=?,next_retry_at=NULL,last_error='',attempt_count=0,updated_at=? WHERE id=?",
                             (status, run["id"], next_run, utc_now(), schedule["id"]))
                created += 1
        except Exception as error:
            logger.error("Scheduled run failed", exc_info=True,
                         extra={"schedule_id": item["id"], "error_type": type(error).__name__})
            _schedule_failed(schedule or item, error)
    return created


class Scheduler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread:
            return
        with transaction() as conn:
            conn.execute("UPDATE schedules SET status='pending',next_retry_at=?,updated_at=? WHERE status='running'",
                         (utc_now(), utc_now()))
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="geopulse-scheduler", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.thread = None

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                run_due_schedules()
                run_due_retention()
                with transaction() as conn:
                    for project in all_rows(conn, "SELECT * FROM projects WHERE status='active'"):
                        evaluate_project_alerts(conn, project)
            except Exception:
                logger.exception("Scheduler cycle failed")
            self.stop_event.wait(15)
