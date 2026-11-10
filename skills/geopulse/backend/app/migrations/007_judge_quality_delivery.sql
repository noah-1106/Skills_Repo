CREATE TABLE judge_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    scope TEXT NOT NULL CHECK(scope IN ('all_eligible','selected')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','partial','failed','cancelled')),
    judge_engine_snapshot_json TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    judge_version TEXT NOT NULL,
    estimate_json TEXT NOT NULL DEFAULT '{}',
    max_safe_retries INTEGER NOT NULL DEFAULT 2 CHECK(max_safe_retries BETWEEN 0 AND 5),
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    budget_confirmation_reason TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);
CREATE INDEX idx_judge_batches_run ON judge_batches(run_id,status,created_at);
CREATE INDEX idx_judge_batches_project ON judge_batches(project_id,status);

CREATE TABLE judge_batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES judge_batches(id) ON DELETE CASCADE,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','failed','cancelled')),
    attempt_no INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    error_detail TEXT,
    outcome_unknown INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(batch_id,answer_id)
);
CREATE INDEX idx_judge_batch_items_queue ON judge_batch_items(status,id);
CREATE INDEX idx_judge_batch_items_answer ON judge_batch_items(answer_id,batch_id);

ALTER TABLE call_attempts ADD COLUMN judge_batch_id INTEGER REFERENCES judge_batches(id) ON DELETE SET NULL;
CREATE INDEX idx_call_attempts_judge_batch ON call_attempts(judge_batch_id,kind,status);
