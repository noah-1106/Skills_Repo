CREATE TABLE browser_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    engine_config_id INTEGER NOT NULL REFERENCES engine_configs(id) ON DELETE CASCADE,
    driver TEXT NOT NULL CHECK(driver IN ('deepseek_web','kimi_web')),
    profile_ref TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','expired','revoked')),
    verification_requested INTEGER NOT NULL DEFAULT 0,
    authorized_by INTEGER REFERENCES users(id),
    authorized_at TEXT NOT NULL,
    last_verified_at TEXT,
    worker_heartbeat_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX idx_browser_sessions_engine ON browser_sessions(engine_config_id,status);

ALTER TABLE web_collections ADD COLUMN collection_method TEXT NOT NULL DEFAULT 'manual'
    CHECK(collection_method IN ('manual','browser_assisted'));
ALTER TABLE web_collections ADD COLUMN browser_phase TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_session_id INTEGER REFERENCES browser_sessions(id) ON DELETE SET NULL;
ALTER TABLE web_collections ADD COLUMN browser_driver TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_driver_version TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE web_collections ADD COLUMN browser_lease_owner TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_lease_expires_at TEXT;
ALTER TABLE web_collections ADD COLUMN browser_heartbeat_at TEXT;
ALTER TABLE web_collections ADD COLUMN browser_send_started_at TEXT;
ALTER TABLE web_collections ADD COLUMN prompt_submitted_at TEXT;
ALTER TABLE web_collections ADD COLUMN conversation_url TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_phase_detail TEXT NOT NULL DEFAULT '';
ALTER TABLE web_collections ADD COLUMN browser_requested_by INTEGER REFERENCES users(id);
CREATE INDEX idx_browser_collection_queue ON web_collections(collection_method,status,browser_phase,browser_lease_expires_at);

CREATE TABLE citations_v5 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    observation_id INTEGER REFERENCES observations(id) ON DELETE SET NULL,
    raw_url TEXT NOT NULL,
    final_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '其他',
    content_hash TEXT NOT NULL DEFAULT '',
    returned_at TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'provider_returned'
        CHECK(origin IN ('provider_returned','manual_page','browser_page')),
    UNIQUE(answer_id, raw_url, content_hash)
);
INSERT INTO citations_v5 SELECT * FROM citations;
DROP TABLE citations;
ALTER TABLE citations_v5 RENAME TO citations;
