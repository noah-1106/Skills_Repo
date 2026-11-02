from pathlib import Path
import json

root = Path('/Volumes/Backups/web-region-capture')
files = {
    'design': root / 'DESIGN.md',
    'environment': root / 'ENVIRONMENT.md',
    'base': root / 'docs/LARK_BASE.md',
    'excel': root / 'docs/LOCAL_EXCEL.md',
    'tasks': root / 'config/tasks.example.json',
    'site': root / 'config/sites/xingtu.example.yaml',
    'pointer': Path('/Users/tannoah/.exflower/workspace/agent-022/web-region-capture/POINTER.md'),
}
for name, path in files.items():
    assert path.is_file() and path.stat().st_size > 0, (name, path)
design = files['design'].read_text()
env = files['environment'].read_text()
base = files['base'].read_text()
excel = files['excel'].read_text()
tasks = json.loads(files['tasks'].read_text())
assert all(x in design for x in ['Windows / macOS', 'Codex、Claude Code、WorkBuddy', 'Playwright 托管 Chromium', 'OpenCLI = 可选浏览器驱动', '不必安装 Chrome'])
assert all(x in design for x in ['显式单元格映射', 'larksuite/cli', 'record_id + 每个区域对应的附件 field_id', '/Volumes/Backups/web-region-capture/'])
assert all(x in env for x in ['PLAYWRIGHT_BROWSERS_PATH', 'python -m playwright install chromium', 'Windows PowerShell', '可选组件需要', '不预设 Chrome'])
assert all(x in base for x in ['npx @larksuite/cli@latest install', 'lark-cli config init', 'lark-cli auth login --recommend', 'base +record-upload-attachment', '--record-id', '--field-id', '默认是追加，不是替换', '+record-download-attachment'])
assert all(x in excel for x in ['工作簿路径', '工作表名', '浮动图片锚定到指定单元格', '不是 Microsoft 365 原生'])
assert len(tasks['tasks']) == 3
assert tasks['tasks'][1]['destination']['cells'] == {'gender': 'C5', 'audience': 'D5'}
assert tasks['tasks'][2]['destination']['type'] == 'lark_bitable'
assert '唯一开发与交付目录' in files['pointer'].read_text()
report = {
    'status': 'verified',
    'checks': {
        'external_canonical_project': True,
        'windows_mac_and_client_independent': True,
        'managed_chromium_no_chrome_assumption': True,
        'opencli_optional': True,
        'explicit_local_excel_cells': True,
        'official_lark_cli_record_field_upload': True,
        'write_readback_and_append_semantics': True,
        'example_json_valid': True,
        'local_pointer_present': True,
    },
    'passed': 9,
    'total': 9,
    'files': {name: {'path': str(path), 'lines': len(path.read_text().splitlines()), 'bytes': path.stat().st_size} for name, path in files.items()},
    'note': 'Design and documentation contract only; no real browser, Xingtu, Excel, Lark or cross-OS execution test activated.',
}
(root / 'evidence/design-gate-v0.2.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
