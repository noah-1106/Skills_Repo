#!/usr/bin/env python3
"""Isolated test-server launcher; never defaults to the production database."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not os.environ.get("GEOPULSE_DB") or not os.environ.get("GEOPULSE_SECRETS"):
    raise SystemExit("测试启动必须显式设置 GEOPULSE_DB 和 GEOPULSE_SECRETS")
os.environ["GEOPULSE_DISABLE_WORKER"] = "1"
sys.path.insert(0, str(ROOT / "backend"))

from app.migrations import initialize

initialize(seed=True)

import uvicorn
from app.main import app

uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("GEOPULSE_PORT", "8701")), log_level="warning")
