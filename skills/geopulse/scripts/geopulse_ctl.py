#!/usr/bin/env python3
"""GeoPulse administration CLI. Paid provider calls are never implicit."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import config
from app.db import connect, dumps, one
from app.migrations import SCHEMA_VERSION, backup, initialize, migrate, restore
from app.security import hash_password
from app.services.exports import build_project_export
from app.services.measurement import Worker


def main():
    parser = argparse.ArgumentParser(prog="geopulse")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("migrate")
    sub.add_parser("backup")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("path", type=Path)
    restore_parser.add_argument("--yes", action="store_true")
    password = sub.add_parser("set-admin-password")
    password.add_argument("email")
    worker = sub.add_parser("run-worker")
    golden = sub.add_parser("golden-eval")
    golden.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "golden.json")
    golden.add_argument("--out", type=Path)
    export = sub.add_parser("export")
    export.add_argument("project_id", type=int)
    export.add_argument("--out", type=Path)
    delete = sub.add_parser("delete-project")
    delete.add_argument("project_id", type=int)
    delete.add_argument("--confirm", required=True)
    args = parser.parse_args()

    if args.command == "init":
        initialize(seed=True)
        print(f"GeoPulse schema v{SCHEMA_VERSION} ready: {config.db_path()}")
    elif args.command == "migrate":
        print(json.dumps(migrate(), ensure_ascii=False, indent=2))
    elif args.command == "backup":
        print(json.dumps(backup(), ensure_ascii=False, indent=2))
    elif args.command == "restore":
        if not args.yes and input(f"确认用 {args.path} 覆盖当前测试/工作库？输入 RESTORE：") != "RESTORE":
            raise SystemExit("已取消")
        restore(args.path)
        print("恢复完成")
    elif args.command == "set-admin-password":
        password_value = getpass.getpass("新密码（至少10位）：")
        with connect() as conn:
            result = conn.execute("UPDATE users SET password_hash=? WHERE email=? AND global_role='admin'",
                                  (hash_password(password_value), args.email))
            if not result.rowcount:
                raise SystemExit("管理员不存在")
            conn.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE email=?)", (args.email,))
            conn.commit()
        print("密码已更新，旧会话已失效")
    elif args.command == "run-worker":
        instance = Worker()
        instance.start()
        print("Worker 已启动，Ctrl+C 停止")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            instance.stop()
    elif args.command == "golden-eval":
        from app.services.evaluation import evaluate_dataset
        result = evaluate_dataset(args.dataset)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    elif args.command == "export":
        with connect() as conn:
            project = one(conn, "SELECT * FROM projects WHERE id=?", (args.project_id,))
            if not project:
                raise SystemExit("项目不存在")
            payload = build_project_export(conn, project)
            conn.commit()
        target = args.out or (config.export_dir() / f"geopulse-project-{args.project_id}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dumps(payload), encoding="utf-8")
        target.chmod(0o600)
        print(target)
    elif args.command == "delete-project":
        with connect() as conn:
            project = one(conn, "SELECT * FROM projects WHERE id=?", (args.project_id,))
            if not project or project["name"] != args.confirm:
                raise SystemExit("项目名确认不匹配")
            conn.execute("DELETE FROM projects WHERE id=?", (args.project_id,))
            conn.commit()
            conn.execute("VACUUM")
        print("项目已删除并执行 VACUUM；备份文件需按保留策略另行处理")


if __name__ == "__main__":
    main()
