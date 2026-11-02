import json
import unittest
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from web_region_capture.capture import CaptureError
from web_region_capture.region_purity import capture_region, inspect_region

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/region_purity.html'
RUN = ROOT / 'data/runs/region-purity-regression-v2'


class RegionPurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUN.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.page = cls.browser.new_page(viewport={'width': 1000, 'height': 900}, device_scale_factor=1)
        cls.page.goto(FIXTURE.as_uri())
        cls.original_dom = cls.page.locator('body').inner_html()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def assert_blocked(self, name, recipe, code):
        target = RUN / 'blocked' / f'{name}.png'
        self.assertFalse(target.exists(), f'Stale artifact would invalidate test: {target}')
        with self.assertRaises(CaptureError) as caught:
            capture_region(self.page, name, recipe, RUN / 'blocked')
        self.assertEqual(caught.exception.code, code)
        report = json.loads((RUN / 'blocked' / f'{name}-purity-check.json').read_text())
        self.assertEqual(report['code'], code)
        self.assertFalse((RUN / 'blocked' / f'{name}.png').exists())
        self.assertEqual(self.page.locator('body').inner_html(), self.original_dom)

    def test_01_element_box_success_and_check(self):
        result = capture_region(self.page, 'pure', {'selector': '#pure-card', 'exclude': {'selectors': []}}, RUN / 'captures')
        self.assertGreater(result['width'], 100)
        report = json.loads(Path(result['purity_check']).read_text())
        self.assertEqual(report['check']['strategy'], 'element_box')
        self.assertFalse(report['check']['dom_mutated'])

    def test_02_text_lines_exclude_floating_element(self):
        recipe = {'selector': '#text-target', 'boundary': {'strategy': 'text_line_boxes', 'padding_px': 2},
                  'exclude': {'selectors': ['#text-floater']}}
        _, inspection = inspect_region(self.page, recipe)
        element_width = self.page.locator('#text-target').bounding_box()['width']
        self.assertGreater(inspection['text_line_rect_count'], 2)
        self.assertLess(inspection['rect']['width'], element_width)
        self.assertEqual(inspection['exclude_intersections'], [])
        result = capture_region(self.page, 'text', recipe, RUN / 'captures')
        with Image.open(result['path']) as image:
            self.assertLess(image.width, element_width)
            # The red floating sidebar must not appear in the cropped evidence.
            red_pixels = sum(1 for r, g, b in image.convert('RGB').getdata() if r > 220 and g < 50 and b < 50)
            self.assertEqual(red_pixels, 0)

    def test_03_explicit_exclusion_intersection_blocks_element_box(self):
        self.assert_blocked('exclude', {'selector': '#pure-card', 'exclude': {'selectors': ['#inside-float']}}, 'REGION_NOT_PURE')

    def test_04_unexpected_overlay_blocks(self):
        self.assert_blocked('overlay', '#occluded-card', 'REGION_OCCLUDED')

    def test_05_exclusion_does_not_hide_occluder(self):
        # Explicitly excluded overlays are still a failed intersection, never auto-hidden.
        self.assert_blocked('excluded-overlay', {'selector': '#occluded-card', 'exclude': {'selectors': ['#unexpected-overlay']}}, 'REGION_NOT_PURE')
        self.assertTrue(self.page.locator('#unexpected-overlay').is_visible())

    def test_06_missing_region_blocks(self):
        self.assert_blocked('missing', '#not-present', 'REGION_NOT_FOUND')

    def test_07_ambiguous_region_blocks(self):
        self.assert_blocked('ambiguous', '.duplicate', 'REGION_AMBIGUOUS')

    def test_08_unsupported_boundary_blocks(self):
        self.assert_blocked('bad-boundary', {'selector': '#pure-card', 'boundary': {'strategy': 'guessed_pixels'}}, 'REGION_BOUNDARY_INVALID')


if __name__ == '__main__':
    unittest.main(verbosity=2)
