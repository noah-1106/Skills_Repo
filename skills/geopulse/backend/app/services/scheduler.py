"""Wave scheduler and conservative two-wave alert evaluation."""
from __future__ import annotations

import threading
import logging
from datetime import datetime, timezone

from ..db import all_rows, connect, loads, one, transaction, utc_now
from ..engine.metrics import calculate_metrics
from .measurement import create_run, load_run_samples

logger = logging.getLogger(__name__)


def _alert(conn, project: dict, wave_id: int | None, kind: str, message: str, severity: str = "warning") -> None:
    exists = one(conn, "SELECT id FROM alerts WHERE project_id=? AND kind=? AND status='open' AND message=?",
                 (project["id"], kind, message))
    if not exists:
        conn.execute("INSERT INTO alerts(client_id,project_id,wave_id,kind,severity,message,created_at) VALUES(?,?,?,?,?,?,?)",
                     (project["client_id"], project["id"], wave_id, kind, severity, message, utc_now()))


def evaluate_project_alerts(conn, project: dict) -> None:
    waves = all_rows(conn, "SELECT * FROM waves WHERE project_id=? AND official_run_id IS NOT NULL ORDER BY id DESC LIMIT 2", (project["id"],))
    metrics = []
    for wave in waves:
        run = one(conn, "SELECT * FROM runs WHERE id=?", (wave["official_run_id"],))
        samples, context = load_run_samples(conn, run)
        value = calculate_metrics(samples, context["primary_id"], loads(wave["stats_json"], {}))
        metrics.append((wave, value))
        quality = value["quality"]
        if quality["valid_sample_rate"]["value"] < 90:
            _alert(conn, project, wave["id"], "sample_completeness", f"Wave {wave['label']} 有效样本率低于 90%，请检查失败样本")
        if quality["judge_fallback_rate"]["value"] > 20:
            _alert(conn, project, wave["id"], "judge_fallback", f"Wave {wave['label']} judge 降级率超过 20%，请复核判定质量")
    if len(metrics) < 2:
        return
    (current_wave, current), (baseline_wave, baseline) = metrics
    threshold = float(loads(project["settings_json"], {}).get("alert_delta_pp", 20))
    negative_delta = current["negative_risk_rate"]["value"] - baseline["negative_risk_rate"]["value"]
    if negative_delta >= threshold:
        _alert(conn, project, current_wave["id"], "negative_change",
               f"主品牌负面率连续两个 wave 对比上升 {negative_delta:.1f}pp，请人工核查原文")
    before = {item["brand_entity_id"]: item["sov"] for item in baseline["competitors"]}
    for competitor in current["competitors"]:
        delta = competitor["sov"] - before.get(competitor["brand_entity_id"], 0)
        if competitor["role"] == "competitor" and delta >= threshold:
            _alert(conn, project, current_wave["id"], "competitor_change",
                   f"{competitor['name']} SoV 连续两个 wave 对比上升 {delta:.1f}pp，仅作观察提醒")


def run_due_schedules() -> int:
    created = 0
    with connect() as conn:
        due = all_rows(conn, "SELECT s.*,p.client_id AS project_client_id FROM schedules s JOIN projects p ON p.id=s.project_id WHERE s.status='pending' AND s.scheduled_at<=? ORDER BY s.id", (utc_now(),))
    for schedule in due:
        project = {"id": schedule["project_id"], "client_id": schedule["project_client_id"]}
        try:
            with transaction() as conn:
                active = one(conn, "SELECT id FROM runs WHERE wave_id=? AND status IN ('queued','running')", (schedule["wave_id"],))
                if active:
                    continue
                claimed = conn.execute("UPDATE schedules SET status='running' WHERE id=? AND status='pending'", (schedule["id"],))
                if not claimed.rowcount:
                    continue
                wave = one(conn, "SELECT * FROM waves WHERE id=?", (schedule["wave_id"],))
                project = one(conn, "SELECT * FROM projects WHERE id=?", (schedule["project_id"],))
            run = create_run(project, wave, None)
            with transaction() as conn:
                conn.execute("UPDATE schedules SET status='done',last_run_id=? WHERE id=?", (run["id"], schedule["id"]))
            created += 1
        except Exception:
            logger.exception("Scheduled run failed", extra={"schedule_id": schedule["id"], "project_id": schedule["project_id"]})
            with transaction() as conn:
                conn.execute("UPDATE schedules SET status='pending' WHERE id=? AND status='running'", (schedule["id"],))
                _alert(conn, project, schedule["wave_id"], "schedule_failed", f"调度 {schedule['id']} 创建 run 失败，将自动重试")
    return created


class Scheduler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread:
            return
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
                with transaction() as conn:
                    for project in all_rows(conn, "SELECT * FROM projects WHERE status='active'"):
                        evaluate_project_alerts(conn, project)
            except Exception:
                logger.exception("Scheduler cycle failed")
            self.stop_event.wait(15)
