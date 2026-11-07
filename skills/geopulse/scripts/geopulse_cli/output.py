"""Machine-first JSON output with an optional, non-lossy-data-contract table view."""
from __future__ import annotations

import json
import sys
from typing import Any


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def render_table(value: Any) -> str:
    rows = value.get("items") if isinstance(value, dict) else value
    if not isinstance(rows, list) and isinstance(value, dict):
        rows = next((item for item in value.values() if isinstance(item, list) and all(isinstance(row, dict) for row in item)), None)
    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
        if not rows:
            return "(no rows)"
        columns = list(dict.fromkeys(key for row in rows for key in row))
        widths = {key: min(60, max(len(key), *(len(_cell(row.get(key))) for row in rows))) for key in columns}
        header = "  ".join(key.ljust(widths[key]) for key in columns)
        divider = "  ".join("-" * widths[key] for key in columns)
        lines = [header, divider]
        for row in rows:
            lines.append("  ".join(_cell(row.get(key))[:widths[key]].ljust(widths[key]) for key in columns))
        return "\n".join(lines)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_cell(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(_cell(item) for item in value)
    return _cell(value)


def emit(value: Any, output_format: str = "json") -> None:
    print(render_json(value) if output_format == "json" else render_table(value))


def emit_error(value: Any) -> None:
    print(render_json(value), file=sys.stderr)
