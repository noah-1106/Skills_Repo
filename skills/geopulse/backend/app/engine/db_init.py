"""GeoPulse 数据库初始化 + 种子数据。"""
import sqlite3
import sys
from pathlib import Path

import os
DB = Path(os.environ.get("GEOPULSE_DB") or (Path(__file__).resolve().parent.parent.parent / "geopulse.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases TEXT DEFAULT '[]',
    is_primary INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    intent TEXT DEFAULT '',
    dimension TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'pending',
    scope TEXT DEFAULT 'all',
    prompt_ids TEXT,
    provider TEXT,
    model TEXT,
    total INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    error TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    answer_text TEXT,
    mentioned_brands TEXT DEFAULT '[]',
    depth TEXT DEFAULT '{}',
    engine TEXT DEFAULT '',
    provider TEXT,
    model TEXT,
    latency_ms INTEGER,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_answers_run ON answers(run_id);
CREATE INDEX IF NOT EXISTS idx_answers_created ON answers(created_at);
"""

SEED_BRANDS = [
    ("GeoPulse", '["geopulse","Geo Pulse"]', 1),
    ("Profound", '["profound.io"]', 0),
    ("Otterly", '["otterly.ai"]', 0),
    ("Scrunch", '[]', 0),
]

SEED_PROMPTS = [
    ("有哪些好用的 AI 品牌可见性监测工具？", "品类调研"),
    ("GEO 工具怎么选？预算有限的团队推荐哪个？", "选型决策"),
    ("企业做生成式引擎优化，第一步该用什么工具摸底？", "入门指引"),
    ("自托管的开源 GEO 监测方案存在吗？", "替代方案"),
    ("内容营销团队需要盯哪些 AI 可见性指标？", "指标认知"),
]


def init(seed=True):
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    # 存量库迁移兜底（v1.2：dimension/depth/engine）
    cols_p = [r[1] for r in conn.execute("PRAGMA table_info(prompts)")]
    if "dimension" not in cols_p:
        conn.execute("ALTER TABLE prompts ADD COLUMN dimension TEXT DEFAULT ''")
    cols_a = [r[1] for r in conn.execute("PRAGMA table_info(answers)")]
    for col, ddl in [("depth", "TEXT DEFAULT '{}'"), ("engine", "TEXT DEFAULT ''")]:
        if col not in cols_a:
            conn.execute(f"ALTER TABLE answers ADD COLUMN {col} {ddl}")
    if seed:
        for name, aliases, primary in SEED_BRANDS:
            conn.execute(
                "INSERT OR IGNORE INTO brands (name, aliases, is_primary) VALUES (?,?,?)",
                (name, aliases, primary))
        for text, intent in SEED_PROMPTS:
            conn.execute(
                "INSERT OR IGNORE INTO prompts (text, intent) SELECT ?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM prompts WHERE text=?)",
                (text, intent, text))
    conn.commit()
    conn.close()
    print(f"[OK] db ready -> {DB}")


if __name__ == "__main__":
    init(seed="--no-seed" not in sys.argv)
