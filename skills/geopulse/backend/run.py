#!/usr/bin/env python3
"""GeoPulse 启动器：初始化 DB（如无）+ 起 uvicorn。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app.engine.db_init import init, DB
init(seed=not DB.exists())  # 仅首次建库放种子；重启绝不往客户数据里塞演示内容
import uvicorn
if __name__ == "__main__":
    import os
    port = int(os.environ.get("GEOPULSE_PORT", "8700"))
    uvicorn.run("app.api.routes:app", host="127.0.0.1", port=port, log_level="info")
