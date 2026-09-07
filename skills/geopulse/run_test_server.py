#!/usr/bin/env python3
"""隔离启动：测试服务器用独立 DB + 独立 config，绝不碰用户数据。"""
import os
import sys
from pathlib import Path

BEFORE = Path(__file__).resolve().parent / "backend"
TEST_DB = "/tmp/geopulse_test.db"
TEST_CFG = "/tmp/geopulse_test_config.json"

os.environ["GEOPULSE_DB"] = TEST_DB
os.environ["GEOPULSE_CONFIG"] = TEST_CFG
os.environ["GEOPULSE_PORT"] = "8700"
sys.path.insert(0, str(BEFORE))

from app.engine.db_init import init
init(seed=True)

import uvicorn
from app.api.routes import app
uvicorn.run(app, host="127.0.0.1", port=8700, log_level="warning")
