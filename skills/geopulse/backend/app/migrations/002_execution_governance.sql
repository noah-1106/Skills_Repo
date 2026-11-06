ALTER TABLE waves ADD COLUMN engine_snapshot_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE answers ADD COLUMN valid_sample INTEGER;
ALTER TABLE answers ADD COLUMN content_retained INTEGER NOT NULL DEFAULT 1;
ALTER TABLE answers ADD COLUMN content_purged_at TEXT;

ALTER TABLE call_attempts RENAME TO call_attempts_v1;
CREATE TABLE call_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER REFERENCES answers(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    engine_config_id INTEGER REFERENCES engine_configs(id),
    kind TEXT NOT NULL CHECK(kind IN ('answer','judge','search','health')),
    operation TEXT NOT NULL DEFAULT '',
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    request_id TEXT,
    model TEXT,
    latency_ms INTEGER,
    usage_json TEXT NOT NULL DEFAULT '{}',
    cost REAL,
    currency TEXT NOT NULL DEFAULT '',
    cost_rule_json TEXT NOT NULL DEFAULT '{}',
    error_type TEXT,
    error_detail TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(answer_id, kind, attempt_no)
);
INSERT INTO call_attempts(
    id,answer_id,client_id,project_id,run_id,engine_config_id,kind,operation,attempt_no,status,
    request_id,model,latency_ms,usage_json,cost,currency,cost_rule_json,error_type,error_detail,created_at
)
SELECT c.id,c.answer_id,a.client_id,a.project_id,a.run_id,a.engine_config_id,c.kind,c.kind,c.attempt_no,c.status,
       c.request_id,c.model,c.latency_ms,c.usage_json,c.cost,'', '{}',c.error_type,c.error_detail,c.created_at
FROM call_attempts_v1 c JOIN answers a ON a.id=c.answer_id;
DROP TABLE call_attempts_v1;

UPDATE answers SET valid_sample=CASE
    WHEN status='succeeded' AND raw_text IS NOT NULL AND trim(raw_text)!='' THEN 1
    WHEN status IN ('failed','cancelled') THEN 0
    ELSE NULL END;

ALTER TABLE reports ADD COLUMN client_html_sha256 TEXT;
ALTER TABLE reports ADD COLUMN internal_html_sha256 TEXT;

ALTER TABLE schedules ADD COLUMN recurrence_days INTEGER;
ALTER TABLE schedules ADD COLUMN next_run_at TEXT;
ALTER TABLE schedules ADD COLUMN anchor_at TEXT;
ALTER TABLE schedules ADD COLUMN action_id INTEGER REFERENCES actions(id) ON DELETE SET NULL;
ALTER TABLE schedules ADD COLUMN last_error TEXT NOT NULL DEFAULT '';
ALTER TABLE schedules ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE schedules ADD COLUMN next_retry_at TEXT;
ALTER TABLE schedules ADD COLUMN updated_at TEXT;
UPDATE schedules SET next_run_at=scheduled_at,anchor_at=scheduled_at,updated_at=created_at;

ALTER TABLE alerts ADD COLUMN dedupe_key TEXT;
ALTER TABLE alerts ADD COLUMN acknowledged_by INTEGER REFERENCES users(id);
ALTER TABLE alerts ADD COLUMN acknowledged_at TEXT;
ALTER TABLE alerts ADD COLUMN resolved_at TEXT;
ALTER TABLE alerts ADD COLUMN updated_at TEXT;
UPDATE alerts SET updated_at=created_at;

ALTER TABLE work_logs ADD COLUMN work_date TEXT;

CREATE TABLE budget_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_id INTEGER REFERENCES waves(id) ON DELETE CASCADE,
    run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    operation_id TEXT UNIQUE,
    amount REAL NOT NULL CHECK(amount >= 0),
    currency TEXT NOT NULL,
    estimate_json TEXT NOT NULL DEFAULT '{}',
    budget_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','released')),
    confirmed_reason TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    released_at TEXT
);

CREATE TABLE retention_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cutoff TEXT NOT NULL,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    purged_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    actor INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE backup_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor INTEGER REFERENCES users(id),
    client_id INTEGER,
    project_id INTEGER,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX idx_attempts_project ON call_attempts(project_id,kind,created_at);
CREATE INDEX idx_attempts_run ON call_attempts(run_id,kind);
CREATE INDEX idx_attempts_answer ON call_attempts(answer_id,kind,attempt_no);
CREATE INDEX idx_reservations_project ON budget_reservations(project_id,status,budget_date);
CREATE UNIQUE INDEX ux_reservations_active_run ON budget_reservations(run_id) WHERE status='active' AND run_id IS NOT NULL;
CREATE INDEX idx_schedules_due ON schedules(status,next_run_at,next_retry_at);
CREATE UNIQUE INDEX ux_alerts_open_dedupe ON alerts(project_id,dedupe_key) WHERE status='open' AND dedupe_key IS NOT NULL;
CREATE INDEX idx_retention_project ON retention_runs(project_id,created_at);
CREATE INDEX idx_backup_project ON backup_runs(project_id,started_at);
