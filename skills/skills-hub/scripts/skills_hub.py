#!/usr/bin/env python3
"""skills-hub: discover, install and update skills from ClawHub.

Zero third-party dependencies (Python stdlib only). Cross-platform
(macOS/Linux/Windows) via pathlib. No ClawHub account needed for
search/show/install (anonymous API).

Data conventions:
  No local cache - every search hits the live ClawHub API (always fresh).
  Origin mark : <skill>/.skills-hub.json inside each installed skill
                (slug/version/installedAt, for update checks)

Usage:
  python3 scripts/skills_hub.py search <kw>          # live search (always fresh)
  python3 scripts/skills_hub.py show <slug>          # details + SKILL.md head
  python3 scripts/skills_hub.py install <slug>       # download + install
  python3 scripts/skills_hub.py update               # check updates for installed
  python3 scripts/skills_hub.py list                 # ClawHub-sourced skills
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path

BASE = "https://clawhub.ai"
API = BASE + "/api/v1"
SKILLS_ROOT = Path.home() / ".exflower" / "skills"
UA = "exflower-skills-hub/1.0 (+local skill manager)"
TIMEOUT = 30


def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def http_download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)





def cmd_search(args):
    kw = " ".join(args.query)
    d = http_json(f"{API}/search?q={urllib.parse.quote(kw)}&limit=15")
    rows = d.get("results", [])
    if not rows:
        print(f"[0 results] keyword search: {kw}")
        print("[TIP] ClawHub search is keyword-based. Try concrete nouns: tool name / product / file format (e.g. pptx, 视频下载, PDF)")
        return
    for r in rows:
        print(f"  {(r.get('slug') or '?'):<38} {(r.get('displayName') or '')[:30]:<30} dl:{r.get('downloads', '?')}")
    print(f"[OK] {len(rows)} live results from ClawHub | install: python3 scripts/skills_hub.py install <slug>")



def cmd_show(args):
    try:
        d = http_json(f"{API}/skills/{urllib.parse.quote(args.slug)}")
    except Exception as e:
        print(f"[FAIL] detail API unreachable: {e}")
        print("[TIP] search/install usually still work; show is non-essential. Try again later.")
        sys.exit(1)
    sk = d.get("skill", d)
    print(f"slug        : {sk.get('slug')}")
    print(f"name        : {sk.get('displayName')}")
    print(f"summary     : {sk.get('summary')}")
    print(f"latest      : {sk.get('latestVersion')}")
    st = sk.get("stats") or {}
    print(f"stats       : {st}")
    desc = sk.get("description") or ""
    print("--- SKILL.md preview ---")
    print(desc[:600])


def install_from_zip(zip_path: Path, slug: str) -> Path:
    dest = SKILLS_ROOT / slug
    if dest.exists():
        print(f"[FAIL] already installed: {dest} (delete it to reinstall)")
        sys.exit(1)
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            z.extractall(td)
        # zip may contain top-level folder or files directly
        root = Path(td)
        inner = root / slug if (root / slug).is_dir() else root
        if not (inner / "SKILL.md").is_file():
            # search one level
            cands = [p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
            inner = cands[0] if cands else root
        SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
        shutil.copytree(inner, dest, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    (dest / ".skills-hub.json").write_text(json.dumps({
        "source": "clawhub", "slug": slug,
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
    return dest


def cmd_install(args):
    slug = args.slug
    url = f"{API}/download?slug={urllib.parse.quote(slug)}"
    if args.version:
        url += f"&version={urllib.parse.quote(args.version)}"
    print(f"  downloading {url}")
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "pkg.zip"
        try:
            http_download(url, zp)
        except urllib.error.HTTPError as e:
            print(f"[FAIL] HTTP {e.code} for slug '{slug}'")
            if e.code == 409:
                print("[TIP] slug conflict - marketplace has duplicate slugs. Pick a unique one (e.g. the 2nd by downloads).")
            elif e.code == 404:
                print("[TIP] slug not found - copy it exactly from search results.")
            sys.exit(1)
        n = zp.stat().st_size
        if n < 200:
            print(f"[FAIL] download too small ({n}B) - slug may not exist")
            sys.exit(1)
        dest = install_from_zip(zp, slug)
    n_files = sum(1 for p in dest.rglob("*") if p.is_file())
    print(f"[OK] installed {slug} -> {dest} ({n_files} files)")
    print(f"[OK] agents should now see it via list_skills")


def origin_of(skill_dir: Path) -> dict | None:
    f = skill_dir / ".skills-hub.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def cmd_update(args):
    if not SKILLS_ROOT.is_dir():
        print("[FAIL] no skills directory")
        return
    installed = []
    for d in SKILLS_ROOT.iterdir():
        if not d.is_dir():
            continue
        o = origin_of(d)
        if o and o.get("source") == "clawhub":
            installed.append(o.get("slug", d.name))
    if not installed:
        print("[OK] no ClawHub-sourced skills installed yet")
        return
    print(f"  checking {len(installed)} skills ...")
    outdated = 0
    for slug in installed:
        try:
            d = http_json(f"{API}/skills/{urllib.parse.quote(slug)}")
            latest = (d.get("skill") or {}).get("latestVersion")
        except Exception as e:
            print(f"  {slug:<35} [ERR] {e}")
            continue
        print(f"  {slug:<35} latest={latest} (reinstall: install {slug} after deleting old)")
    print("[OK] check done")


def cmd_list(args):
    if not SKILLS_ROOT.is_dir():
        print("[FAIL] no skills directory")
        return
    rows = 0
    for d in SKILLS_ROOT.iterdir():
        if not d.is_dir():
            continue
        o = origin_of(d)
        if o:
            print(f"  {d.name:<35} {o.get('installedAt', '?')}")
            rows += 1
    if not rows:
        print("[OK] none installed from ClawHub yet")
    else:
        print(f"[OK] {rows} ClawHub-sourced skills")


def main():
    ap = argparse.ArgumentParser(prog="skills-hub", description="ClawHub skill manager for ExFlower")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="live keyword search on ClawHub")
    p.add_argument("query", nargs="+")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="show skill details + SKILL.md preview")
    p.add_argument("slug")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("install", help="download and install a skill")
    p.add_argument("slug")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("update", help="check latest versions of installed skills")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("list", help="list ClawHub-sourced installed skills")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
