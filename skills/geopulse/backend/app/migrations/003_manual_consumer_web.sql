CREATE TABLE engine_configs_v3 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    vendor TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('demo','openai_compat','kimi_search','manual_web')),
    model TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    secret_ref TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK(mode IN ('memory','search')),
    measurement_target TEXT NOT NULL DEFAULT 'provider_api',
    region TEXT NOT NULL DEFAULT '',
    cost_rule_json TEXT NOT NULL DEFAULT '{}',
    timeout INTEGER NOT NULL DEFAULT 60,
    rate_limit REAL NOT NULL DEFAULT 12,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
INSERT INTO engine_configs_v3 SELECT * FROM engine_configs;
DROP TABLE engine_configs;
ALTER TABLE engine_configs_v3 RENAME TO engine_configs;

ALTER TABLE waves ADD COLUMN judge_snapshot_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE answers ADD COLUMN raw_text_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE citations ADD COLUMN origin TEXT NOT NULL DEFAULT 'provider_returned'
    CHECK(origin IN ('provider_returned','manual_page'));

CREATE TABLE web_collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    answer_id INTEGER NOT NULL UNIQUE REFERENCES answers(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'awaiting_collection' CHECK(status IN
        ('awaiting_collection','collecting','review_pending','completed','failed','recollect_required')),
    draft_text TEXT NOT NULL DEFAULT '',
    actual_url TEXT NOT NULL DEFAULT '',
    observed_mode TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT '',
    collector_id INTEGER REFERENCES users(id),
    session_context_json TEXT NOT NULL DEFAULT '{}',
    retrieval_status TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT NOT NULL DEFAULT '',
    failure_type TEXT NOT NULL DEFAULT '',
    failure_detail TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    submitted_at TEXT,
    content_purged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE answer_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('screenshot','raw_html','raw_text')),
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
    sha256 TEXT NOT NULL,
    content BLOB,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    purged_at TEXT
);

CREATE INDEX idx_collections_project_status ON web_collections(project_id,status);
CREATE INDEX idx_collections_answer ON web_collections(answer_id);
CREATE INDEX idx_attachments_answer ON answer_attachments(answer_id,kind);
CREATE INDEX idx_attachments_project ON answer_attachments(project_id,purged_at);
