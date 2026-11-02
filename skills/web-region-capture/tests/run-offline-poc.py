import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/ms-playwright')
os.environ['TMPDIR'] = str(ROOT / 'runtime/tmp')
(ROOT / 'runtime/tmp').mkdir(parents=True, exist_ok=True)
(ROOT / 'evidence').mkdir(exist_ok=True)
log_path = ROOT / 'evidence/offline-poc-unittest.log'
started = time.time()
with log_path.open('w') as log:
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
summary = {
    'suite': 'tests/test_*.py',
    'tests_run': result.testsRun,
    'failures': len(result.failures),
    'errors': len(result.errors),
    'skipped': len(result.skipped),
    'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    'success': result.wasSuccessful(),
    'seconds': round(time.time() - started, 3),
    'activated_tests': ['managed Chromium launch', 'HTML navigation/search', 'identity assertion', 'element_box and text_line_boxes boundaries', 'explicit exclusion intersection blocking', 'unexpected overlay blocking without DOM mutation', 'missing/ambiguous region failures', 'invalid boundary strategy blocking', 'explicit Excel anchors/readback', 'source workbook unchanged', 'repeat delivery blocked', 'nonempty cell protection', 'missing worksheet protection', 'M2 CLI doctor and project-root paths', 'M2 Unicode/space Excel delivery/readback', 'M2 manifest safe resume', 'M2 folder conflict handling', 'M2 official-lark-cli command construction/dry-run using a fake runner', 'M2 real Base double authorization gate'],
    'not_activated': ['Xingtu live', 'OpenCLI', 'Lark Base live write', 'Windows OS', 'Codex/Claude Code/WorkBuddy clients', 'PowerShell execution on Windows', 'real lark-cli from product adapter (separate dry-run smoke test)', 'tamper/corrupt-output resume beyond tested happy-path conflict cases'],
    'log': str(log_path),
}
(ROOT / 'evidence/offline-poc-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False, indent=2))
print(log_path.read_text())
raise SystemExit(0 if result.wasSuccessful() else 1)
