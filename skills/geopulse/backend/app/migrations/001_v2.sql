CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    retention_policy TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT 'CN',
    language TEXT NOT NULL DEFAULT 'zh-CN',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status TEXT NOT NULL DEFAULT 'active',
    service_package TEXT NOT NULL DEFAULT 'diagnosis',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(client_id, name)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    global_role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('admin','analyst','reviewer','viewer')),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, user_id)
);

CREATE TABLE engine_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    vendor TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('demo','openai_compat','kimi_search')),
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

CREATE TABLE brand_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    logical_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('primary','competitor','candidate')),
    name TEXT NOT NULL,
    entity_card_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    reviewed_by INTEGER REFERENCES users(id),
    review_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, logical_id, version)
);

CREATE TABLE prompt_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    weights_json TEXT NOT NULL DEFAULT '{}',
    frozen_at TEXT,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, version)
);

CREATE TABLE prompt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt_set_id INTEGER NOT NULL REFERENCES prompt_sets(id) ON DELETE CASCADE,
    logical_id TEXT NOT NULL,
    canonical_intent_id TEXT NOT NULL,
    text TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK(dimension IN ('brand','scene','compare','choice')),
    funnel_stage TEXT NOT NULL DEFAULT '考虑',
    query_type TEXT NOT NULL CHECK(query_type IN ('discovery','navigation')),
    persona TEXT NOT NULL DEFAULT '',
    scenario TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'zh-CN',
    price_band TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '专家设计',
    priority INTEGER NOT NULL DEFAULT 3,
    eligibility TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    fields_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(prompt_set_id, logical_id)
);

CREATE TABLE waves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt_set_id INTEGER NOT NULL REFERENCES prompt_sets(id),
    entity_version TEXT NOT NULL,
    label TEXT NOT NULL,
    anchor_at TEXT,
    protocol_json TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    official_run_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_id INTEGER NOT NULL REFERENCES waves(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    snapshot_json TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    UNIQUE(wave_id, attempt_no)
);

CREATE TABLE answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    prompt_item_id INTEGER NOT NULL REFERENCES prompt_items(id),
    engine_config_id INTEGER NOT NULL REFERENCES engine_configs(id),
    round_no INTEGER NOT NULL,
    raw_text TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error_type TEXT,
    error_detail TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    model TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, prompt_item_id, engine_config_id, round_no)
);

CREATE TABLE call_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('answer','judge','search')),
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    request_id TEXT,
    model TEXT,
    latency_ms INTEGER,
    usage_json TEXT NOT NULL DEFAULT '{}',
    cost REAL,
    error_type TEXT,
    error_detail TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(answer_id, kind, attempt_no)
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    brand_entity_id INTEGER NOT NULL REFERENCES brand_entities(id),
    revision INTEGER NOT NULL,
    entity_status TEXT NOT NULL,
    mentioned INTEGER NOT NULL DEFAULT 0,
    depth TEXT NOT NULL DEFAULT 'absent',
    sentiment TEXT NOT NULL DEFAULT 'unknown',
    top_choice INTEGER NOT NULL DEFAULT 0,
    evidence TEXT NOT NULL DEFAULT '',
    citation_urls_json TEXT NOT NULL DEFAULT '[]',
    discovered_json TEXT NOT NULL DEFAULT '[]',
    judge_status TEXT NOT NULL,
    judge_meta_json TEXT NOT NULL DEFAULT '{}',
    review_status TEXT NOT NULL DEFAULT 'machine',
    review_reason TEXT NOT NULL DEFAULT '',
    reviewer_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(answer_id, brand_entity_id, revision)
);

CREATE TABLE citations (
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
    UNIQUE(answer_id, raw_url, content_hash)
);

CREATE TABLE opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_id INTEGER NOT NULL REFERENCES waves(id) ON DELETE CASCADE,
    prompt_item_id INTEGER NOT NULL REFERENCES prompt_items(id),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    gap_type TEXT NOT NULL,
    eligibility TEXT NOT NULL DEFAULT 'unknown',
    score REAL,
    score_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    close_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(wave_id, prompt_item_id)
);

CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    geo_step INTEGER NOT NULL CHECK(geo_step BETWEEN 1 AND 7),
    title TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    target_url TEXT NOT NULL DEFAULT '',
    artifact_version TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    published_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    target_wave_id INTEGER REFERENCES waves(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE external_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_ids_json TEXT NOT NULL,
    data_snapshot_json TEXT NOT NULL,
    data_snapshot_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'draft',
    client_html TEXT NOT NULL DEFAULT '',
    internal_html TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, version)
);

CREATE TABLE report_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    actor INTEGER REFERENCES users(id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor INTEGER REFERENCES users(id),
    client_id INTEGER,
    project_id INTEGER,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_id INTEGER NOT NULL REFERENCES waves(id) ON DELETE CASCADE,
    scheduled_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_run_id INTEGER REFERENCES runs(id),
    created_at TEXT NOT NULL,
    UNIQUE(wave_id, scheduled_at)
);

CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wave_id INTEGER REFERENCES waves(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE work_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    hours REAL NOT NULL CHECK(hours >= 0),
    kind TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_membership_user ON memberships(user_id, project_id);
CREATE INDEX idx_engines_project ON engine_configs(project_id, enabled);
CREATE INDEX idx_entities_project ON brand_entities(project_id, logical_id, version);
CREATE INDEX idx_prompt_items_set ON prompt_items(prompt_set_id, canonical_intent_id);
CREATE INDEX idx_waves_project ON waves(project_id, created_at);
CREATE INDEX idx_runs_wave ON runs(wave_id, attempt_no);
CREATE INDEX idx_answers_run ON answers(run_id, status);
CREATE INDEX idx_answers_project ON answers(project_id, created_at);
CREATE INDEX idx_attempts_answer ON call_attempts(answer_id, kind, attempt_no);
CREATE INDEX idx_observations_answer ON observations(answer_id, brand_entity_id, revision);
CREATE INDEX idx_observations_project ON observations(project_id, entity_status);
CREATE INDEX idx_citations_project ON citations(project_id, domain);
CREATE INDEX idx_opportunities_project ON opportunities(project_id, status);
CREATE INDEX idx_actions_project ON actions(project_id, status);
CREATE INDEX idx_audit_project ON audit_events(project_id, created_at);
CREATE INDEX idx_alerts_project ON alerts(project_id, status, created_at);
CREATE UNIQUE INDEX ux_prompt_normalized ON prompt_items(prompt_set_id, lower(trim(text)));
