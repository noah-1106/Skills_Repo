---
name: web-region-capture
description: Capture explicit, purity-checked web regions into folders or Excel; official lark-cli Base adapter is dry-run by default. Use for repeatable local browser/Excel evidence, not arbitrary one-click website automation.
---

# web-region-capture

## Run from a client-independent project root

This is a Python CLI, not a Codex/Claude/WorkBuddy plugin. Read `README.md`, `config/local.example.json`, and `config/tasks.m2-example.json`. Do not use client-specific APIs. Current working directory does not affect relative project paths.

```sh
python -m web_region_capture --root /path/to/project doctor
python -m web_region_capture --root /path/to/project run --config config/tasks.m2-example.json --run-id "我的 任务"
```

With a fresh checkout run `scripts/bootstrap.sh` on macOS/Linux or `scripts/bootstrap.ps1` on Windows. If the package is not installed, use `PYTHONPATH=<root>/src` (shell) or `$env:PYTHONPATH=<root>/src` (PowerShell). Default browser is Playwright-managed Chromium; never assume Chrome or OpenCLI. OpenCLI is not an implemented runner in M2.

## Required task contract

- `version: 1`; either inline `site` or `site_file`.
- `site.start_url`: HTTPS or project-root-relative HTML file; optional explicit `actions`, `identity`, `viewport`, `headless`.
- Each task has a unique safe `task_id`, `subject_query`, nonempty `regions`; all regions must have site recipes.
- Folder: `destination.type=folder`, `path`.
- Excel: `source_path`, `path`, exact `sheet`, and `cells` mapping every region to an A1 cell. Source is never overwritten. `.xlsx` only; output images are floating cell anchors, not Microsoft 365 Place-in-Cell values.
- Base: `base_token`, `table_id`, `record_id`, `fields` mapping every region to an attachment field. Only official `lark-cli base +record-upload-attachment --as user` is used. Base is not Excel; no A1 coordinates.

All relative paths (including local HTML and workbooks) resolve from `--root`; Unicode and spaces are supported. No cookie/password/secret belongs in config or logs. Never require a client-provided proprietary browser or Feishu SDK.

## Run, evidence and safe rerun

Default `--dry-run`: capture evidence into `data/runs/<run-id>/`, but do not write final folder/Excel targets and invoke Base only with `lark-cli --dry-run`. `--execute-local` enables local folder/Excel output; it does not authorize Base.

Every run has `manifest.json` with config fingerprint, region purity evidence, hashes, per-task state. Reusing a run ID without `--resume` is blocked. `--resume` skips completed artifacts only if hashes/config fingerprints still match; failed or changed work requires explicit diagnosis/new run. Output conflicts stop instead of overwriting. A dry-run manifest cannot be mistaken for delivered.

`needs_readback` after a real Base upload is not delivered: official record readback and attachment download/hash comparison must be completed. Real write additionally requires task `allow_live_write=true`, `allow_replace=false`, and CLI `--authorize-lark-write`. Default append only. Never use real Base data for smoke tests; ask Noah to provide an authorized test target.

## Validate before declaring completion

```sh
python tests/run-offline-poc.py
```

Evidence must name the activated tests and skipped environments. Windows, OpenCLI, live Base, and external clients are not verified by a macOS local run. For public-site acceptance, use a separate explicitly supplied site/task config; a local fixture is not public-site proof.
