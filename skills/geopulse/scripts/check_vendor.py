#!/usr/bin/env python3
"""Verify vendored browser assets without downloading or executing them."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "frontend" / "vendor"


def main() -> None:
    manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    checked = []
    for artifact in manifest["artifacts"]:
        path = VENDOR / artifact["file"]
        if not path.is_file():
            errors.append(f"missing: {artifact['file']}")
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != artifact["bytes"]:
            errors.append(f"byte size mismatch: {artifact['file']}")
        if digest != artifact["sha256"]:
            errors.append(f"SHA-256 mismatch: {artifact['file']}")
        for field in ("license_file", "notice_file"):
            if not (VENDOR / artifact[field]).is_file():
                errors.append(f"missing {field}: {artifact[field]}")
        if artifact["version"] != "5.5.0" or b"5.5.0" not in content:
            errors.append(f"version header mismatch: {artifact['file']}")
        checked.append({"file": artifact["file"], "version": artifact["version"], "sha256": digest})
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"status": "passed", "artifacts": checked}, ensure_ascii=False))


if __name__ == "__main__":
    main()
