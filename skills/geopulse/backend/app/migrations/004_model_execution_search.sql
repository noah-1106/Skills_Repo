CREATE TABLE engine_configs_v4 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    vendor TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('demo','openai_compat','kimi_search','deepseek_search','manual_web')),
    model TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    secret_ref TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK(mode IN ('memory','search')),
    measurement_target TEXT NOT NULL DEFAULT 'provider_api',
    region TEXT NOT NULL DEFAULT '',
    cost_rule_json TEXT NOT NULL DEFAULT '{}',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    answer_defaults_json TEXT NOT NULL DEFAULT '{}',
    judge_defaults_json TEXT NOT NULL DEFAULT '{}',
    health_defaults_json TEXT NOT NULL DEFAULT '{}',
    timeout INTEGER NOT NULL DEFAULT 60,
    rate_limit REAL NOT NULL DEFAULT 12,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
INSERT INTO engine_configs_v4(
    id,client_id,project_id,name,vendor,kind,model,base_url,secret_ref,mode,measurement_target,
    region,cost_rule_json,timeout,rate_limit,health_status,enabled,created_at
)
SELECT id,client_id,project_id,name,vendor,kind,model,base_url,secret_ref,mode,measurement_target,
       region,cost_rule_json,timeout,rate_limit,health_status,enabled,created_at
FROM engine_configs;
DROP TABLE engine_configs;
ALTER TABLE engine_configs_v4 RENAME TO engine_configs;
CREATE INDEX idx_engines_project ON engine_configs(project_id, enabled);

ALTER TABLE call_attempts ADD COLUMN request_params_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE call_attempts ADD COLUMN response_meta_json TEXT NOT NULL DEFAULT '{}';
