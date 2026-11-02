import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.goto('https://en.wikipedia.org/wiki/Alan_Turing', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_selector('#firstHeading')
    result = {
        'url': page.url,
        'infobox_count': page.locator('table.infobox').count(),
        'direct_p_count': page.locator('#mw-content-text .mw-parser-output > p').count(),
        'all_p_count': page.locator('#mw-content-text .mw-parser-output p').count(),
        'paragraphs': page.locator('#mw-content-text .mw-parser-output p').evaluate_all('(els) => els.slice(0,12).map((e,i) => ({i, text:(e.innerText||"").slice(0,180), display:getComputedStyle(e).display, visibility:getComputedStyle(e).visibility, rect:{w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}, parent:e.parentElement.tagName+"."+e.parentElement.className}))')
    }
    path = ROOT/'evidence/wikipedia-dom-inspection.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    browser.close()
