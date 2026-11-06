#!/usr/bin/env python3
"""GeoPulse portable launcher."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.migrations import SCHEMA_VERSION, MigrationRequired, current_version, initialize


def main():
    parser = argparse.ArgumentParser(description="GeoPulse v2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--no-worker", action="store_true")
    args = parser.parse_args()
    if args.no_worker:
        os.environ["GEOPULSE_DISABLE_WORKER"] = "1"
    version = current_version()
    if version not in (0, SCHEMA_VERSION):
        raise SystemExit(f"数据库需要迁移（v{version}→v{SCHEMA_VERSION}）。请运行 scripts/geopulse_ctl.py migrate")
    initialize(seed=True)
    import uvicorn
    from app.main import app
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
