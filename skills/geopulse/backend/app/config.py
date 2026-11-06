"""Runtime configuration. Paths stay portable and test-isolatable."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

DEFAULT_PROJECT_SETTINGS = {
    "confidence_level": 0.95,
    "small_sample_n": 30,
    "min_pair_completeness": 0.90,
    "repeats": 3,
    "prompt_quotas": {"brand": 2, "scene": 2, "compare": 2, "choice": 2},
    "score_weights": {
        "business_value": 1.0,
        "eligibility_confidence": 1.0,
        "competitive_gap": 1.0,
        "evidence_reliability": 1.0,
        "executability": 1.0,
    },
    "source_domains": {
        "baike.baidu.com": "百科",
        "zh.wikipedia.org": "百科",
        "zhihu.com": "UGC",
        "xiaohongshu.com": "UGC",
    },
    "budget": {"enabled": False, "hard_limit": False, "amount": None, "currency": "CNY"},
    "retention_days": None,
}


def db_path() -> Path:
    return Path(os.environ.get("GEOPULSE_DB", str(BACKEND / "geopulse.db")))


def secret_path() -> Path:
    return Path(os.environ.get("GEOPULSE_SECRETS", str(BACKEND / "secrets.json")))


def legacy_config_path() -> Path:
    return Path(os.environ.get("GEOPULSE_CONFIG", str(BACKEND / "config.json")))


def backup_dir() -> Path:
    return Path(os.environ.get("GEOPULSE_BACKUP_DIR", str(BACKEND / "backups")))


def export_dir() -> Path:
    return Path(os.environ.get("GEOPULSE_EXPORT_DIR", str(ROOT / "outputs")))


def worker_count() -> int:
    return max(1, min(16, int(os.environ.get("GEOPULSE_WORKERS", "4"))))


def session_hours() -> int:
    return int(os.environ.get("GEOPULSE_SESSION_HOURS", "12"))


def ensure_directories() -> None:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    secret_path().parent.mkdir(parents=True, exist_ok=True)
    backup_dir().mkdir(parents=True, exist_ok=True)
    export_dir().mkdir(parents=True, exist_ok=True)
