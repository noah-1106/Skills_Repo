"""One-site live regression: Wikipedia Alan Turing, not a universal-site claim."""
import hashlib
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from web_region_capture.capture import assert_identity
from web_region_capture.region_purity import capture_pure_regions

RUN = ROOT / 'data/runs/public-wikipedia-alan-turing-purity-v1'
RUN.mkdir(parents=True, exist_ok=False)
report = {'site': 'Wikipedia', 'scope': 'Alan Turing infobox and first substantive paragraph only',
          'universal_website_claim': False, 'status': 'started', 'steps': []}

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
        assert search.count() == 1
        search.fill('Alan Turing')
        search.press('Enter')
        page.wait_for_load_state('domcontentloaded')
        if '/wiki/Alan_Turing' not in page.url:
            page.locator('a[title="Alan Turing"]:visible').first.click()
            page.wait_for_load_state('domcontentloaded')
        page.wait_for_selector('#firstHeading', timeout=30000)
        identity = assert_identity(page, '#firstHeading', 'Alan Turing')
        report['steps'].append({'name': 'search_and_identity', 'identity': identity, 'final_url': page.url})
        paragraphs = page.locator('#mw-content-text .mw-parser-output p')
        selected = None
        selected_text = None
        for i in range(paragraphs.count()):
            candidate = paragraphs.nth(i)
            if candidate.is_visible() and len((candidate.text_content() or '').strip()) > 150:
                selected, selected_text = i, (candidate.text_content() or '').strip()
                break
        assert selected is not None
        recipes = {
            'info_box': {'selector': 'table.infobox'},
            'intro': {'selector': f'#mw-content-text .mw-parser-output p >> nth={selected}',
                      'boundary': {'strategy': 'text_line_boxes', 'padding_px': 2},
                      'exclude': {'selectors': ['table.infobox'], 'overlap_action': 'block'},
                      'occlusion': {'detect': True, 'allowed_overlay_selectors': []}},
        }
        captures = capture_pure_regions(page, recipes, RUN / 'captures')
        for item in captures.values():
            item['sha256'] = hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
        report['steps'].append({'name': 'region_capture', 'recipes': recipes, 'captures': captures})
        # Full-page debug context is separate evidence; target PNG remains unmodified.
        page.screenshot(path=str(RUN / 'page-context.png'), full_page=False)
        report['selected_paragraph_text'] = selected_text
        report['status'] = 'machine_checks_passed_visual_review_required'
        browser.close()
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    save()
    raise
save()
print(json.dumps(report, ensure_ascii=False, indent=2))
