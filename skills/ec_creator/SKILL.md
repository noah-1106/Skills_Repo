# EC Creator Skill

> **Version: 1.1.0** | Execution Card Linter & Validator with Auto-Fix

A validation and correction tool for creating standardized Execution Cards.

---

## What's New in v1.1.0

- **Python-based**: Data-driven validation using JSON rules (no hard-coding)
- **Auto-Fix Suggestions**: Returns copy-pasteable Markdown snippets for common issues
- **Real Skill Scanning**: Actually checks `~/.openclaw/skills/` directory for skill existence
- **Enhanced Error Messages**: More actionable guidance

---

## What This Skill Does

EC Creator transforms draft workflow descriptions into production-ready Execution Cards through automated validation and iterative correction.

**Core Workflow:**
```
Draft (temp_draft.md) → Lint → Fix → Validate → Standard EC (EC-XXX.md)
```

---

## Core Functions

### 1. Structure Integrity Scan

Validates logical blocks are complete:

| Block | Check | Error if Missing |
|-------|-------|------------------|
| **Resource Dependencies** | Lists required skills/tools | "Agent may hallucinate unavailable tools" |
| **Execution Workflow** | Numbered step list | "Non-sequential, hard to parse" |
| **Execution Conventions** | I/O paths defined | "Cross-agent collaboration fails" |

### 2. Path Vitality Check

Scans and validates all paths in the EC:

```bash
# Checks:
- Resource paths: Do files exist?
- Output directories: Are they writable?
- Template references: Are they valid?

# Example Output:
[FAIL] Template POST_TEMPLATE.md not found in workspace
[PASS] Output directory posts/ exists and is writable
```

### 3. Semantic Polish

Keyword-based sanity checks:

| Keywords Found | Warning if Missing |
|----------------|-------------------|
| "upload", "post", "send" | No network/API skill in dependencies |
| "read", "write", "save" | No file system skill declared |
| "error", "fail", "retry" | No error handling section |
| "if", "check", "validate" | No input validation steps |

---

## Usage

### Command Line

```bash
# Validate a draft EC
ec_linter ExCard/temp_draft.md

# Output:
# [INFO] Scanning temp_draft.md...
# [WARN] Missing Resource Dependencies section
# [ERROR] Output path posts/ does not exist
# [FAIL] 1 error, 1 warning found

# After fixing, run again:
ec_linter ExCard/temp_draft.md
# [PASS] All checks passed. Ready to rename to EC-XXX.md
```

### In Agent Workflow

**Phase 1: Observation**
Agent records successful operations in `ExCard/temp_draft.md`

**Phase 2: Initial Structuring**
Agent formats draft according to template

**Phase 3: Lint & Validate**
```
Agent: Run ec_linter ExCard/temp_draft.md
Linter: [FAIL] Missing Input conventions
Agent: Edit file, add Input section
Agent: Run ec_linter again
Linter: [PASS]
```

**Phase 4: Activate**
Rename to `EC-005-descriptive-name.md`

---

## Validation Rules

### Rule 1: Required Sections

Must have these Markdown H2 sections:
- `## Resource Dependencies`
- `## Execution Workflow`  
- `## Execution Conventions`

### Rule 2: Numbered Steps

Execution Workflow must use numbered list (1., 2., 3.)

```markdown
## Execution Workflow
1. Read input file
2. Process data
3. Save output
```

### Rule 3: Path Verification

All paths must be:
- Relative (not absolute)
- Within workspace
- Properly formatted

### Rule 4: Dependency Declaration

Every external tool/skill must be listed in Resource Dependencies

### Rule 5: Error Handling

Must have at least one of:
- Error handling steps
- Retry logic
- Failure recovery procedure

---

## Output Format

```
EC Linter Report
================
File: ExCard/temp_draft.md
Status: [PASS] / [FAIL] / [WARN]

Structure Check:
  [✓] Resource Dependencies
  [✓] Execution Workflow  
  [✗] Execution Conventions (missing I/O paths)

Path Check:
  [✓] Input: data/input.csv
  [✗] Template: templates/missing.md (not found)

Semantic Check:
  [WARN] Steps mention 'upload' but no network skill declared
  [WARN] No error handling detected

Next Steps:
  1. Add missing Execution Conventions section
  2. Create templates/missing.md or fix path
  3. Add error handling steps or retry logic
```

---

## Integration with OpenExCard

```
┌─────────────────────────────────────────┐
│           Agent observes workflow       │
│           Records in temp_draft.md      │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      Agent formats using template       │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      EC Creator Skill (ec_linter)       │
│  ┌──────────────┬──────────────┐       │
│  │ Structure    │ Path         │       │
│  │ Scan         │ Vitality     │       │
│  └──────────────┴──────────────┘       │
│              │                          │
│              ▼                          │
│  ┌──────────────────────┐              │
│  │   Semantic Polish    │              │
│  └──────────────────────┘              │
└─────────────────┬───────────────────────┘
                  │
          [FAIL]  │  [PASS]
                  ▼
┌─────────────────┴───────────────────────┐
│  Report errors    │  Rename to EC-XXX.md │
│  Agent fixes      │  Activate            │
│  Re-run linter    │                      │
└─────────────────────────────────────────┘
```

---

## Installation

```bash
clawhub install ec_creator
```

Or clone to `~/.openclaw/skills/ec_creator/`

---

## Files

```
ec_creator/
├── SKILL.md              # This file
├── ec_linter.sh          # Main validation script
├── rules/
│   ├── structure.json    # Section requirements
│   ├── paths.json        # Path validation rules  
│   └── semantic.json     # Keyword patterns
└── templates/
    └── ec_template.md    # Starter template
```

---

## Changelog

- **v1.0.0** (2026-03-14): Initial release
  - Structure integrity scan
  - Path vitality check
  - Semantic polish
  - Iterative validation workflow

---

*Part of OpenExCard Framework*
