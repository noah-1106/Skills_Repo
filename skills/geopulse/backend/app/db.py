"""SQLite access with tenant-safe defaults and explicit transactions."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return {} if default is None else default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def transaction(path: Path | None = None):
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def one(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> dict | None:
    row = conn.execute(sql, tuple(args)).fetchone()
    return dict(row) if row is not None else None


def all_rows(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]


def public(row: dict | None, *json_fields: str) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for field in json_fields:
        if field in result:
            result[field.removesuffix("_json")] = loads(result.pop(field), [])
    return result
