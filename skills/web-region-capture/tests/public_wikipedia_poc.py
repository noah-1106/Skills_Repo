import hashlib
import json
import os
import sys
from pathlib import Path

from openpyxl import Workbook
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from web_region_capture.capture import assert_identity, capture_regions
from web_region_capture.excel_delivery import deliver_excel

RUN = ROOT / 'data/runs/public-wikipedia-alan-turing-v2'
RUN.mkdir(parents=True, exist_ok=False)
report = {'site': 'Wikipedia', 'requires_login': False, 'status': 'started', 'steps': []}

def step(name, **data):
    report['steps'].append({'name': name, **data})
    print(json.dumps(report['steps'][-1], ensure_ascii=False), flush=True)

def save():
    (RUN / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

try:
    with sync_playwright() as p:
        executable = Path(p.chromium.executable_path)
        assert str(ROOT / 'runtime/ms-playwright') in str(executable), executable
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page.goto('https://en.wikipedia.org/wiki/Main_Page', wait_until='domcontentloaded', timeout=60000)
        search = page.locator('input[name=search]:visible')
        assert search.count() == 1, f'visible search inputs: {search.count()}'
        search.fill('Alan Turing')
        search.press('Enter')
        page.wait_for_load_state('domcontentloaded')
        if '/wiki/Alan_Turing' not in page.url:
            result = page.locator('a[title="Alan Turing"]:visible')
            assert result.count() >= 1, 'Alan Turing result not found'
            result.first.click()
            page.wait_for_load_state('domcontentloaded')
        page.wait_for_selector('#firstHeading', timeout=30000)
        identity = assert_identity(page, '#firstHeading', 'Alan Turing')
        step('search_and_identity', query='Alan Turing', identity=identity, final_url=page.url)

        # Current Wikipedia Parsoid layout wraps paragraphs in SECTION elements.
        # Locate all descendants, then choose by visible text, not assumed direct-child DOM.
        paragraphs = page.locator('#mw-content-text .mw-parser-output p')
        selected = None
        for i in range(paragraphs.count()):
            candidate = paragraphs.nth(i)
            if candidate.is_visible() and len((candidate.text_content() or '').strip()) > 150:
                selected = i
                break
        assert selected is not None, 'No substantive intro paragraph found'
        regions = {
            'info_box': 'table.infobox',
            'intro': f'#mw-content-text .mw-parser-output p >> nth={selected}',
        }
        captures = capture_regions(page, regions, RUN / 'captures')
        for item in captures.values():
            item['sha256'] = hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
        step('region_capture', regions=regions, captures=captures)

        source = RUN / 'source.xlsx'
        output = RUN / 'Alan-Turing-Wikipedia.xlsx'
        workbook = Workbook()
        workbook.active.title = 'Wikipedia'
        workbook.active['A1'] = 'Public webpage region capture test'
        workbook.save(source)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        delivery = deliver_excel(source, output, 'Wikipedia', {'info_box': 'C5', 'intro': 'D5'}, {name: Path(item['path']) for name, item in captures.items()})
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
        step('excel_delivery', delivery=delivery, source_unchanged=True)
        browser.close()
    report['status'] = 'passed'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    save()
    raise
save()
print(json.dumps(report, ensure_ascii=False, indent=2))
