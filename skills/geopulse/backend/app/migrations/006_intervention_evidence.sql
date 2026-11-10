CREATE TABLE content_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','superseded','legacy')),
    target_prompt_item_id INTEGER REFERENCES prompt_items(id),
    information_gain TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    expected_observation TEXT NOT NULL DEFAULT '',
    channels_json TEXT NOT NULL DEFAULT '[]',
    success_criteria TEXT NOT NULL DEFAULT '',
    claims_json TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT,
    UNIQUE(action_id,version)
);
CREATE INDEX idx_briefs_action ON content_briefs(action_id,status,version);

CREATE TABLE action_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    brief_id INTEGER REFERENCES content_briefs(id),
    title TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'fact_page',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','superseded','legacy')),
    content_json TEXT NOT NULL DEFAULT '{}',
    facts_json TEXT NOT NULL DEFAULT '[]',
    applicability TEXT NOT NULL DEFAULT '',
    exclusions TEXT NOT NULL DEFAULT '',
    supersedes_asset_id INTEGER REFERENCES action_assets(id),
    content_hash TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT,
    UNIQUE(action_id,title,version)
);
CREATE INDEX idx_assets_action ON action_assets(action_id,status,version);

CREATE TABLE asset_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    asset_id INTEGER NOT NULL REFERENCES action_assets(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    outlet TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    cost REAL CHECK(cost IS NULL OR cost>=0),
    currency TEXT NOT NULL DEFAULT '',
    relationship TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT NOT NULL DEFAULT '',
    recorded_by INTEGER REFERENCES users(id),
    recorded_at TEXT NOT NULL,
    UNIQUE(asset_id,channel,outlet,url)
);
CREATE INDEX idx_publications_action ON asset_publications(action_id,published_at);

CREATE TABLE action_remeasurement_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL,
    offset_days INTEGER NOT NULL CHECK(offset_days BETWEEN 1 AND 365),
    baseline_wave_id INTEGER NOT NULL REFERENCES waves(id),
    baseline_run_id INTEGER REFERENCES runs(id),
    target_wave_id INTEGER NOT NULL REFERENCES waves(id),
    target_run_id INTEGER REFERENCES runs(id),
    surface TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_measurement'
        CHECK(status IN ('pending_measurement','measured','insufficient_evidence','incomparable','legacy_unavailable')),
    attribution_status TEXT NOT NULL DEFAULT 'not_attributable' CHECK(attribution_status IN ('not_attributable')),
    success_criteria TEXT NOT NULL DEFAULT '',
    observed_change TEXT NOT NULL DEFAULT '' CHECK(observed_change IN ('','improved','not_improved','unknown')),
    comparison_json TEXT NOT NULL DEFAULT '{}',
    comparison_hash TEXT NOT NULL DEFAULT '',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    conclusion_reason TEXT NOT NULL DEFAULT '',
    assessed_by INTEGER REFERENCES users(id),
    assessed_at TEXT,
    reminder_at TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(action_id,round_no)
);
CREATE INDEX idx_rounds_due ON action_remeasurement_rounds(status,due_at);
CREATE INDEX idx_rounds_action ON action_remeasurement_rounds(action_id,round_no);

ALTER TABLE external_events ADD COLUMN action_id INTEGER REFERENCES actions(id) ON DELETE SET NULL;
ALTER TABLE external_events ADD COLUMN asset_id INTEGER REFERENCES action_assets(id) ON DELETE SET NULL;
ALTER TABLE external_events ADD COLUMN publication_id INTEGER REFERENCES asset_publications(id) ON DELETE SET NULL;
ALTER TABLE external_events ADD COLUMN remeasurement_round_id INTEGER REFERENCES action_remeasurement_rounds(id) ON DELETE SET NULL;
CREATE INDEX idx_events_action ON external_events(action_id,event_at);

ALTER TABLE schedules ADD COLUMN remeasurement_round_id INTEGER REFERENCES action_remeasurement_rounds(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX ux_schedule_round ON schedules(remeasurement_round_id) WHERE remeasurement_round_id IS NOT NULL;

-- v5 records remain explicitly legacy: no structured claims or historical comparison are invented.
INSERT INTO content_briefs(client_id,project_id,action_id,version,status,target_prompt_item_id,created_at)
SELECT a.client_id,a.project_id,a.id,1,'legacy',o.prompt_item_id,a.created_at
FROM actions a JOIN opportunities o ON o.id=a.opportunity_id;

INSERT INTO action_assets(client_id,project_id,action_id,brief_id,title,version,status,content_json,created_at)
SELECT a.client_id,a.project_id,a.id,b.id,a.title,1,'legacy',
       json_object('target_url',a.target_url,'summary',''),a.created_at
FROM actions a JOIN content_briefs b ON b.action_id=a.id AND b.version=1
WHERE a.published_url<>'';

INSERT INTO asset_publications(client_id,project_id,action_id,asset_id,channel,outlet,url,published_at,cost,currency,relationship,recorded_at)
SELECT a.client_id,a.project_id,a.id,s.id,'legacy','',a.published_url,a.published_at,NULL,'','unknown',a.updated_at
FROM actions a JOIN action_assets s ON s.action_id=a.id AND s.version=1
WHERE a.published_url<>'' AND a.published_at IS NOT NULL;

UPDATE external_events SET
    action_id=(SELECT p.action_id FROM asset_publications p WHERE p.project_id=external_events.project_id AND p.url=external_events.source AND p.published_at=external_events.event_at),
    asset_id=(SELECT p.asset_id FROM asset_publications p WHERE p.project_id=external_events.project_id AND p.url=external_events.source AND p.published_at=external_events.event_at),
    publication_id=(SELECT p.id FROM asset_publications p WHERE p.project_id=external_events.project_id AND p.url=external_events.source AND p.published_at=external_events.event_at)
WHERE action_id IS NULL AND kind='内容发布' AND EXISTS(
    SELECT 1 FROM asset_publications p WHERE p.project_id=external_events.project_id
      AND p.url=external_events.source AND p.published_at=external_events.event_at
);

INSERT INTO action_remeasurement_rounds(
    client_id,project_id,action_id,round_no,offset_days,baseline_wave_id,baseline_run_id,
    target_wave_id,target_run_id,surface,due_at,status,conclusion_reason,created_at
)
SELECT s.client_id,s.project_id,s.action_id,
       ROW_NUMBER() OVER(PARTITION BY s.action_id ORDER BY s.id),
       MAX(1,CAST(julianday(s.scheduled_at)-julianday(a.published_at) AS INTEGER)),
       o.wave_id,NULL,s.wave_id,NULL,
       COALESCE(json_extract(w.protocol_json,'$.measurement_target'),'provider_api'),
       s.scheduled_at,'legacy_unavailable','v5 调度未冻结正式 Run 与完整 comparison，仅保留历史节点',s.created_at
FROM schedules s
JOIN actions a ON a.id=s.action_id
JOIN opportunities o ON o.id=a.opportunity_id
JOIN waves w ON w.id=s.wave_id
WHERE s.action_id IS NOT NULL;

UPDATE schedules SET remeasurement_round_id=(
    SELECT r.id FROM action_remeasurement_rounds r
    WHERE r.action_id=schedules.action_id AND r.target_wave_id=schedules.wave_id AND r.due_at=schedules.scheduled_at
) WHERE action_id IS NOT NULL AND EXISTS(
    SELECT 1 FROM action_remeasurement_rounds r
    WHERE r.action_id=schedules.action_id AND r.target_wave_id=schedules.wave_id AND r.due_at=schedules.scheduled_at
);
