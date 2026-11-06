"""Ordered, checksummed migrations with restorable SQLite backups."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from . import config
from .db import connect, dumps, utc_now

SCHEMA_VERSION = 1
MIGRATIONS = {1: Path(__file__).parent / "migrations" / "001_v2.sql"}


class MigrationRequired(RuntimeError):
    pass


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def current_version(path: Path | None = None) -> int:
    target = path or config.db_path()
    if not target.exists():
        return 0
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def initialize(seed: bool = True) -> None:
    config.ensure_directories()
    version = current_version()
    if version not in (0, SCHEMA_VERSION):
        raise MigrationRequired(f"数据库 schema=v{version}，当前程序需要 v{SCHEMA_VERSION}；请先运行迁移命令")
    if version == 0:
        sql = MIGRATIONS[1].read_text(encoding="utf-8")
        conn = connect()
        try:
            conn.executescript(sql)
            conn.execute("PRAGMA user_version=1")
            conn.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(1,?,?)",
                         (_checksum(sql), utc_now()))
            conn.commit()
        finally:
            conn.close()
    if seed:
        from .bootstrap import seed_demo
        seed_demo()


def backup(destination: Path | None = None) -> dict:
    config.ensure_directories()
    source = config.db_path()
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    target = destination or (config.backup_dir() / f"geopulse-v{current_version()}-{stamp}.db")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {"source": str(source), "backup": str(target), "schema_version": current_version(),
                "sha256": digest, "created_at": utc_now()}
    target.with_suffix(".manifest.json").write_text(dumps(manifest), encoding="utf-8")
    target.with_suffix(".manifest.json").chmod(0o600)
    target.chmod(0o600)
    return manifest


def restore(backup_path: Path, destination: Path | None = None) -> None:
    source = backup_path.resolve()
    target = (destination or config.db_path()).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == target:
        raise ValueError("恢复源和目标不能相同")
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version != SCHEMA_VERSION:
        raise MigrationRequired(f"备份 schema=v{version}，需先迁移副本")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(0o600)


def migrate() -> dict:
    version = current_version()
    if version == 0:
        initialize(seed=False)
        return {"from": 0, "to": SCHEMA_VERSION, "backup": None}
    if version == SCHEMA_VERSION:
        return {"from": version, "to": version, "backup": None}
    if version > SCHEMA_VERSION:
        raise MigrationRequired("数据库来自更新版本，拒绝降级打开")
    manifest = backup()
    # Future ordered migrations run here, each in its own transaction.
    raise MigrationRequired(f"没有从 v{version} 到 v{SCHEMA_VERSION} 的迁移路径；备份已保留")
