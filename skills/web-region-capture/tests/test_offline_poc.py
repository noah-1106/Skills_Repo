import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook
from PIL import Image
from playwright.sync_api import sync_playwright

from web_region_capture.capture import CaptureError, assert_identity, capture_regions
from web_region_capture.excel_delivery import TargetUnsafe, deliver_excel

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/demo.html'
RUN = ROOT / 'data/runs/offline-poc'


class BrowserCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUN.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=1)
        cls.page.goto(FIXTURE.as_uri())
        cls.page.locator('#query').fill('测试达人')
        cls.page.locator('#search').click()
        assert_identity(cls.page, '#identity', '测试达人')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_01_capture_two_regions(self):
        result = capture_regions(self.page, {'gender': '[data-testid=gender]', 'audience': '[data-testid=audience]'}, RUN / 'captures')
        self.assertEqual(set(result), {'gender', 'audience'})
        for name, item in result.items():
            path = Path(item['path'])
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 1000)
            self.assertGreater(item['width'], 100)
            self.assertGreater(item['height'], 100)
            with Image.open(path) as image:
                self.assertGreater(len(image.convert('RGB').getcolors(maxcolors=1000000)), 3)
        (RUN / 'capture-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def test_02_identity_mismatch_blocks(self):
        with self.assertRaises(CaptureError) as caught:
            assert_identity(self.page, '#identity', '错误达人')
        self.assertEqual(caught.exception.code, 'IDENTITY_MISMATCH')

    def test_03_missing_region_blocks(self):
        with self.assertRaises(CaptureError) as caught:
            capture_regions(self.page, {'missing': '#does-not-exist'}, RUN / 'should-not-exist')
        self.assertEqual(caught.exception.code, 'REGION_NOT_FOUND')

    def test_04_ambiguous_region_blocks(self):
        with self.assertRaises(CaptureError) as caught:
            capture_regions(self.page, {'duplicate': '.card'}, RUN / 'should-not-exist')
        self.assertEqual(caught.exception.code, 'REGION_AMBIGUOUS')


class ExcelTests(unittest.TestCase):
    def setUp(self):
        self.images = {name: RUN / 'captures' / f'{name}.png' for name in ('gender', 'audience')}
        self.assertTrue(all(path.is_file() for path in self.images.values()), 'Run browser capture test first')
        self.temp = TemporaryDirectory(dir=ROOT / 'data/runs')
        self.dir = Path(self.temp.name)
        self.source = self.dir / '原始 提报表.xlsx'
        workbook = Workbook()
        workbook.active.title = '达人提报'
        workbook.save(self.source)
        self.output = self.dir / '结果 提报表.xlsx'
        self.cells = {'gender': 'C5', 'audience': 'D5'}

    def tearDown(self):
        self.temp.cleanup()

    def source_hash(self):
        return hashlib.sha256(self.source.read_bytes()).hexdigest()

    def deliver(self):
        return deliver_excel(self.source, self.output, '达人提报', self.cells, self.images)

    def test_05_excel_explicit_cells_and_readback(self):
        before = self.source_hash()
        result = self.deliver()
        self.assertEqual(set(result['anchors']), {'C5', 'D5'})
        check = load_workbook(self.output)
        self.assertEqual(len(check['达人提报']._images), 2)
        self.assertEqual(self.source_hash(), before)
        self.assertNotEqual(self.source_hash(), hashlib.sha256(self.output.read_bytes()).hexdigest())
        (RUN / 'excel-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def test_06_repeat_delivery_blocked(self):
        self.deliver()
        with self.assertRaises(TargetUnsafe):
            self.deliver()
        self.assertEqual(len(load_workbook(self.output)['达人提报']._images), 2)

    def test_07_nonempty_cell_requires_overwrite(self):
        workbook = load_workbook(self.source)
        workbook['达人提报']['C5'] = '不要覆盖'
        workbook.save(self.source)
        with self.assertRaises(TargetUnsafe):
            self.deliver()
        self.assertFalse(self.output.exists())

    def test_08_missing_sheet_blocks(self):
        with self.assertRaises(TargetUnsafe):
            deliver_excel(self.source, self.output, '不存在', self.cells, self.images)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
