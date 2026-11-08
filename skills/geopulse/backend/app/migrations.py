"""Ordered, checksummed migrations with restorable SQLite backups."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import config
from .db import connect, dumps, utc_now

MIGRATIONS = {
    1: Path(__file__).parent / "migrations" / "001_v2.sql",
    2: Path(__file__).parent / "migrations" / "002_execution_governance.sql",
    3: Path(__file__).parent / "migrations" / "003_manual_consumer_web.sql",
    4: Path(__file__).parent / "migrations" / "004_model_execution_search.sql",
    5: Path(__file__).parent / "migrations" / "005_authorized_browser_collector.sql",
}
SCHEMA_VERSION = max(MIGRATIONS)


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


def _verify_applied_checksums() -> None:
    version = current_version()
    if not version:
        return
    conn = sqlite3.connect(f"file:{config.db_path()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT version,checksum FROM schema_migrations WHERE version<=?", (version,)).fetchall()
    finally:
        conn.close()
    recorded = {int(number): checksum for number, checksum in rows}
    for number in range(1, version + 1):
        expected = _checksum(MIGRATIONS[number].read_text(encoding="utf-8"))
        if recorded.get(number) != expected:
            raise MigrationRequired(f"schema migration v{number} 的 checksum 不匹配，拒绝继续")


def _apply_migrations(version: int) -> None:
    for number in range(version + 1, SCHEMA_VERSION + 1):
        sql = MIGRATIONS[number].read_text(encoding="utf-8")
        digest = _checksum(sql)
        conn = connect()
        try:
            if number in {3, 4, 5}:
                # Table rebuild requires FK off before the transaction starts.
                conn.execute("PRAGMA foreign_keys=OFF")
            script = (
                "BEGIN IMMEDIATE;\n" + sql
                + f"\nINSERT INTO schema_migrations(version,checksum,applied_at) VALUES({number},'{digest}','{utc_now()}');"
                + f"\nPRAGMA user_version={number};\nCOMMIT;"
            )
            conn.executescript(script)
            if number in {3, 4, 5}:
                conn.execute("PRAGMA foreign_keys=ON")
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise MigrationRequired(f"schema v{number} 外键检查失败：{violations[:5]}")
        finally:
            conn.close()


def initialize(seed: bool = True) -> None:
    config.ensure_directories()
    version = current_version()
    if version > SCHEMA_VERSION:
        raise MigrationRequired(f"数据库 schema=v{version}，当前程序需要 v{SCHEMA_VERSION}；拒绝降级打开")
    if version and version < SCHEMA_VERSION:
        raise MigrationRequired(f"数据库 schema=v{version}，当前程序需要 v{SCHEMA_VERSION}；请先运行迁移命令")
    if version == 0:
        _apply_migrations(0)
    else:
        _verify_applied_checksums()
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
    manifest_path = target.with_suffix(".manifest.json")
    manifest_path.write_text(dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    target.chmod(0o600)
    return manifest


def _check_sqlite(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity_check 失败：{integrity}")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"SQLite foreign_key_check 失败：{violations[:5]}")
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def restore(backup_path: Path, destination: Path | None = None) -> None:
    source = backup_path.resolve()
    target = (destination or config.db_path()).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == target:
        raise ValueError("恢复源和目标不能相同")
    manifest_path = source.with_suffix(".manifest.json")
    if not manifest_path.is_file():
        raise ValueError("缺少相邻的备份 manifest，拒绝未校验恢复")
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if manifest.get("sha256") != digest:
        raise ValueError("备份 SHA-256 与 manifest 不匹配，拒绝恢复")
    version = _check_sqlite(source)
    if version != SCHEMA_VERSION:
        raise MigrationRequired(f"备份 schema=v{version}，需先迁移副本")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.restore-", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        _check_sqlite(temporary)
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def migrate() -> dict:
    version = current_version()
    if version == 0:
        initialize(seed=False)
        return {"from": 0, "to": SCHEMA_VERSION, "backup": None}
    if version > SCHEMA_VERSION:
        raise MigrationRequired("数据库来自更新版本，拒绝降级打开")
    _verify_applied_checksums()
    if version == SCHEMA_VERSION:
        return {"from": version, "to": version, "backup": None}
    manifest = backup()
    start = version
    _apply_migrations(version)
    _verify_applied_checksums()
    return {"from": start, "to": SCHEMA_VERSION, "backup": manifest}
