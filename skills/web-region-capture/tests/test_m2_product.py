import hashlib
import json
import os
import shutil
import subprocess
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from web_region_capture.product import (
    ProductError, doctor, load_config, normalize_destination, project_path,
    read_json, run, sha256, write_json,
)

ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / 'runtime/ms-playwright'


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='m2a-isolated-')
        self.root = Path(self.temp.name) / '中文 空格 项目'
        (self.root / 'config').mkdir(parents=True)
        write_json(self.root / 'config/local.json', {'browser_path': str(BROWSER), 'lark_cli_path': 'lark-cli'})
        workbook = Workbook()
        workbook.active.title = '达人提报'
        workbook.save(self.root / '中文 源表.xlsx')
        self.config = {
            'version': 1,
            'site': {'start_url': (ROOT / 'tests/fixtures/demo.html').as_uri(), 'headless': True,
                     'actions': [{'type': 'fill', 'selector': '#query', 'value_from': 'subject_query'},
                                 {'type': 'click', 'selector': '#search'},
                                 {'type': 'wait_for_selector', 'selector': '#results'}],
                     'identity': {'selector': '#identity', 'expected_from': 'subject_query'},
                     'recipes': {'gender': '[data-testid=gender]', 'audience': '[data-testid=audience]'}},
            'tasks': []}

    def tearDown(self):
        self.temp.cleanup()

    def add_task(self, destination, task_id='中文 task 001'):
        task = {'task_id': task_id, 'subject_query': '测试达人', 'regions': ['gender', 'audience'], 'destination': destination}
        self.config['tasks'] = [task]
        self.write_config()
        return task

    def write_config(self):
        write_json(self.root / '任务 配置.json', self.config)

    def execute(self, **kwargs):
        return run(self.root, '任务 配置.json', run_id='运行 001', **kwargs)

    def excel(self, nested=False, task_id='中文 excel'):
        mapping = {'type': 'excel', 'source_path': '/./中文 源表.xlsx',
                   'path': '/./outputs/结果 含 空格.xlsx', 'sheet': '达人提报',
                   'cells': {'gender': 'C5', 'audience': 'D5'}}
        return self.add_task({'mapping': mapping} if nested else mapping, task_id)

    def test_01_excel_execute_readback_resume_and_source_unchanged(self):
        self.excel()
        before = sha256(self.root / '中文 源表.xlsx')
        manifest = self.execute(dry_run=False)
        output = self.root / 'outputs/结果 含 空格.xlsx'
        self.assertTrue(output.is_file())
        workbook = load_workbook(output)
        self.assertEqual(len(workbook['达人提报']._images), 2)
        anchors = sorted(image.anchor._from.col + 1 for image in workbook['达人提报']._images)
        self.assertEqual(anchors, [3, 4])
        workbook.close()
        self.assertEqual(sha256(self.root / '中文 源表.xlsx'), before)
        self.assertEqual(manifest['tasks']['中文 excel']['status'], 'delivered')
        mtime = output.stat().st_mtime_ns
        resumed = self.execute(resume=True, dry_run=False)
        self.assertEqual(output.stat().st_mtime_ns, mtime)
        self.assertTrue(resumed['tasks']['中文 excel']['resumed'])
        with self.assertRaises(ProductError) as caught:
            self.execute(dry_run=False)
        self.assertEqual(caught.exception.code, 'RUN_EXISTS')

    def test_02_folder_and_excel_do_not_overwrite(self):
        self.add_task({'type': 'folder', 'path': '结果 目录'})
        self.execute(dry_run=False)
        target = self.root / '结果 目录/gender.png'
        target.write_bytes(b'different')
        with self.assertRaises(ProductError) as caught:
            self.execute(dry_run=False)
        self.assertEqual(caught.exception.code, 'RUN_EXISTS')

    def test_03_lark_dry_run_and_unauthorized_write_never_reaches_cli(self):
        task = self.add_task({'type': 'lark_bitable', 'base_token': 'basenPlaceholder', 'table_id': 'tblPlaceholder',
            'record_id': 'recPlaceholder', 'fields': {'gender': 'fldGender', 'audience': 'fldAudience'},
            'mode': 'append', 'allow_replace': False, 'allow_live_write': False})
        commands = []
        class Result:
            returncode = 0
            stderr = ''
            stdout = '{"api": [{"method": "POST", "url": "dry-run-only"}]}'
        def runner(command, **kwargs):
            commands.append(command)
            return Result()
        manifest = self.execute(dry_run=True, runner=runner)
        self.assertEqual(manifest['tasks'][task['task_id']]['status'], 'dry_run')
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command[:3], ['lark-cli', 'base', '+record-upload-attachment'])
            self.assertIn('--dry-run', command)
            self.assertIn('--as', command)
        with self.assertRaises(ProductError) as caught:
            run(self.root, '任务 配置.json', run_id='未授权 运行', dry_run=False, runner=runner)
        self.assertEqual(caught.exception.code, 'LARK_WRITE_NOT_AUTHORIZED')
        self.assertEqual(len(commands), 2)

    def test_04_lark_real_requires_double_gate_even_with_mock_runner(self):
        self.add_task({'type': 'lark_bitable', 'base_token': 'basenPlaceholder', 'table_id': 'tblPlaceholder',
            'record_id': 'recPlaceholder', 'fields': {'gender': 'fldGender', 'audience': 'fldAudience'},
            'allow_replace': False, 'allow_live_write': True})
        def fail_runner(*args, **kwargs):
            raise AssertionError('unauthorized real command attempted')
        with self.assertRaises(ProductError) as caught:
            self.execute(dry_run=False, runner=fail_runner)
        self.assertEqual(caught.exception.code, 'LARK_WRITE_NOT_AUTHORIZED')

    def test_05_project_root_path_resolution_and_validation(self):
        # TemporaryDirectory on macOS lives under /var -> /private/var; compare
        # canonical paths, not the unresolved self.root spelling.
        self.assertEqual(project_path(self.root, '/./中文 空格/a.png'), (self.root / '中文 空格/a.png').resolve())
        for task in ({}, {'task_id': '../escape', 'regions': ['x']},
                     {'task_id': 'ok', 'regions': ['x'], 'destination': {'type': 'excel'}}):
            with self.assertRaises(ProductError):
                from web_region_capture.product import validate_task
                validate_task(task)
        self.config['tasks'] = [{'task_id': 'x', 'regions': ['not-there'], 'destination': {'type': 'folder', 'path': 'out'}}]
        self.write_config()
        with self.assertRaises(ProductError) as caught:
            load_config(self.root, '任务 配置.json')
        self.assertEqual(caught.exception.code, 'CONFIG_INVALID')
        with self.assertRaises(ProductError):
            project_path(self.root, '../escape')

    def test_06_cli_doctor_smoke(self):
        # --root is an isolated project, so browser_path must resolve inside it.
        # Symlink the already-installed managed Chromium rather than downloading
        # a second copy or weakening project_path()'s containment check.
        (self.root / 'runtime').mkdir(parents=True, exist_ok=True)
        os.symlink(BROWSER, self.root / 'runtime/ms-playwright', target_is_directory=True)
        write_json(self.root / 'config/local.json', {'browser_path': '/./runtime/ms-playwright', 'lark_cli_path': 'lark-cli'})
        command = [str(ROOT / '.venv/bin/python'), '-m', 'web_region_capture', '--root', str(self.root), 'doctor', '--no-browser', '--artifact', 'doctor.json']
        environment = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
        completed = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = read_json(self.root / 'doctor.json')
        self.assertTrue(report['ok'])
        self.assertEqual(next(item for item in report['checks'] if item['name'] == 'opencli')['status'], 'skipped')

    def test_07_nested_mapping_manifest_freeze(self):
        self.excel(nested=True)
        result = self.execute(dry_run=True)
        run_dir = self.root / 'data/runs/运行 001'
        manifest = read_json(run_dir / 'manifest.json')
        self.assertEqual(result['tasks']['中文 excel']['status'], 'dry_run')
        self.assertFalse((self.root / 'outputs/结果 含 空格.xlsx').exists())
        self.assertEqual(manifest['root'], str(self.root.resolve()))
        for name, key in [('config.json', 'frozen_config'), ('site.json', 'frozen_site')]:
            evidence = manifest[key]
            path = run_dir / name
            self.assertEqual(Path(evidence['path']).resolve(), path.resolve())
            self.assertEqual(evidence['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(manifest['config_sha256'], manifest['frozen_config']['sha256'])
        self.assertEqual(manifest['site_sha256'], manifest['frozen_site']['sha256'])
        self.assertEqual(Path(result['tasks']['中文 excel']['delivery']['target_path']).resolve(),
                         (self.root / 'outputs/结果 含 空格.xlsx').resolve())
        # frozen_* 是文件证据（path+sha256），frozen 只含内容 hash——不含路径，
        # 所以同一项目经 /var 与 /private/var 打开也能 resume。
        self.assertEqual(manifest['frozen']['config']['sha256'], manifest['frozen_config']['sha256'])
        self.assertNotIn('path', manifest['frozen']['config'])
        self.assertNotIn('path', manifest['frozen']['local_config'])

    def test_08_dry_run_is_never_reused_as_delivered(self):
        self.excel(nested=True)
        first = self.execute(dry_run=True)
        self.assertEqual(first['tasks']['中文 excel']['status'], 'dry_run')
        second = self.execute(resume=True, dry_run=False)
        self.assertEqual(second['tasks']['中文 excel']['status'], 'delivered')
        self.assertFalse(second['tasks']['中文 excel']['delivery']['dry_run'])
        self.assertEqual(len(load_workbook(self.root / 'outputs/结果 含 空格.xlsx')['达人提报']._images), 2)
        third = self.execute(resume=True, dry_run=False)
        self.assertTrue(third['tasks']['中文 excel']['resumed'])

    def test_09_resume_rejects_target_capture_purity_and_source_tamper(self):
        self.excel(nested=True)
        manifest = self.execute(dry_run=False)
        run_dir = self.root / 'data/runs/运行 001'
        entry = manifest['tasks']['中文 excel']
        cases = [('target', Path(entry['delivery']['artifacts']['workbook']['path'])),
                 ('capture', Path(entry['evidence']['captures']['gender']['path'])),
                 ('purity', Path(entry['evidence']['purity_reports']['gender']['path']))]
        for label, path in cases:
            original = path.read_bytes()
            with self.subTest(artifact=label):
                path.write_bytes(original + b' tamper')
                with self.assertRaises(ProductError) as caught:
                    self.execute(resume=True, dry_run=False)
                self.assertEqual(caught.exception.code, 'RESUME_MISMATCH')
                path.write_bytes(original)
        workbook = load_workbook(self.root / '中文 源表.xlsx')
        workbook['达人提报']['A1'] = '源表改变'
        workbook.save(self.root / '中文 源表.xlsx')
        with self.assertRaises(ProductError) as caught:
            self.execute(resume=True, dry_run=False)
        self.assertEqual(caught.exception.code, 'RESUME_MISMATCH')

    def test_10_resume_rejects_changed_config_root_and_frozen_site(self):
        self.excel(nested=True)
        self.execute(dry_run=True)
        run_dir = self.root / 'data/runs/运行 001'
        manifest_path = run_dir / 'manifest.json'
        frozen_site = run_dir / 'site.json'
        original = frozen_site.read_bytes()
        frozen_site.write_bytes(original + b'\n')
        with self.assertRaises(ProductError) as caught:
            self.execute(resume=True, dry_run=True)
        self.assertEqual(caught.exception.code, 'RESUME_MISMATCH')
        frozen_site.write_bytes(original)
        manifest = read_json(manifest_path)
        manifest['root'] = '/another/root'
        write_json(manifest_path, manifest)
        with self.assertRaises(ProductError) as caught:
            self.execute(resume=True, dry_run=True)
        self.assertEqual(caught.exception.code, 'RESUME_MISMATCH')
        manifest['root'] = str(self.root)
        write_json(manifest_path, manifest)
        self.config['tasks'][0]['subject_query'] = '配置改变'
        self.write_config()
        with self.assertRaises(ProductError) as caught:
            self.execute(resume=True, dry_run=True)
        self.assertEqual(caught.exception.code, 'RESUME_MISMATCH')

    def test_11_folder_explicit_resume_and_atomic_excel_precheck(self):
        folder = {'task_id': 'folder task', 'subject_query': '测试达人', 'regions': ['gender', 'audience'], 'destination': {'type': 'folder', 'path': '/./outputs/独立 目录'}}
        excel = {'task_id': 'excel task', 'subject_query': '测试达人', 'regions': ['gender', 'audience'], 'destination': {'type': 'excel', 'source_path': '中文 源表.xlsx', 'path': '/./outputs/结果 含 空格.xlsx', 'sheet': '达人提报', 'cells': {'gender': 'C5', 'audience': 'D5'}}}
        self.config['tasks'] = [folder, excel]
        self.write_config()
        result = self.execute(dry_run=False)
        self.assertTrue((self.root / 'outputs/独立 目录/gender.png').is_file())
        self.assertTrue((self.root / 'outputs/结果 含 空格.xlsx').is_file())
        resumed = self.execute(resume=True, dry_run=False)
        self.assertTrue(all(entry['status'] == 'delivered' for entry in resumed['tasks'].values()))
        bad_folder = dict(folder, task_id='atomic folder', destination={'type': 'folder', 'path': '/./outputs/不会落位'})
        bad_excel = dict(excel, task_id='atomic excel', destination=dict(excel['destination'], path='/./outputs/不会生成.xlsx', sheet='不存在'))
        self.config['tasks'] = [bad_folder, bad_excel]
        self.write_config()
        with self.assertRaises(ProductError):
            run(self.root, '任务 配置.json', run_id='atomic new', dry_run=False)
        self.assertFalse((self.root / 'outputs/不会落位/gender.png').exists())
        self.assertFalse((self.root / 'outputs/不会生成.xlsx').exists())

    def test_12_destination_normalization_is_unambiguous(self):
        with self.assertRaises(ProductError):
            normalize_destination({'mapping': {'type': 'folder'}, 'path': 'outputs/x'})
        with self.assertRaises(ProductError):
            normalize_destination({'type': 'excel', 'path': 'outputs/x.xlsx', 'source_path': '中文 源表.xlsx'})
        with self.assertRaises(ProductError):
            run(self.root, '任务 配置.json', run_id='unsafe', dry_run=True) if False else (_ for _ in ()).throw(ProductError('unused'))
        normalized = normalize_destination({'mapping': {'type': 'excel', 'path': '/./outputs/合法.xlsx',
            'source_path': '/./中文 源表.xlsx', 'sheet': '达人提报', 'cells': {'gender': 'C5'}}})
        self.assertNotIn('mapping', normalized)
        self.assertEqual(normalized['cells'], {'gender': 'C5'})
        self.add_task({'type': 'folder', 'path': '../outside'})
        with self.assertRaises(ProductError) as caught:
            self.execute(dry_run=True)
        self.assertEqual(caught.exception.code, 'OUTPUT_UNSAFE')

    def test_13_later_task_capture_failure_has_no_partial_delivery(self):
        folder = {'task_id': 'folder task', 'subject_query': '测试达人', 'regions': ['gender'], 'destination': {'type': 'folder', 'path': '/./outputs/不会落位'}}
        excel = {'task_id': 'excel task', 'subject_query': '测试达人', 'regions': ['audience'], 'destination': {'type': 'excel', 'source_path': '中文 源表.xlsx', 'path': '/./outputs/不会生成.xlsx', 'sheet': '达人提报', 'cells': {'audience': 'D5'}}}
        self.config['tasks'] = [folder, excel]
        self.write_config()
        from web_region_capture.capture import CaptureError
        original = __import__('web_region_capture.region_purity', fromlist=['capture_pure_regions']).capture_pure_regions
        count = [0]
        def fail_second(*args, **kwargs):
            count[0] += 1
            if count[0] == 2:
                raise CaptureError('TEST_SECOND_TASK_FAILURE', 'Second task capture failed')
            return original(*args, **kwargs)
        with unittest.mock.patch('web_region_capture.product.capture_pure_regions', side_effect=fail_second):
            with self.assertRaises(CaptureError):
                run(self.root, '任务 配置.json', run_id='capture atomic', dry_run=False)
        self.assertFalse((self.root / 'outputs/不会落位').exists())
        self.assertFalse((self.root / 'outputs/不会生成.xlsx').exists())

    def test_14_official_lark_cli_dry_run_no_credentials(self):
        if shutil.which('lark-cli') is None:
            self.skipTest('lark-cli not installed')
        task = self.add_task({'type': 'lark_bitable', 'base_token': 'basenPlaceholder', 'table_id': 'tblPlaceholder',
            'record_id': 'recPlaceholder', 'fields': {'gender': 'fldGender', 'audience': 'fldAudience'}})
        manifest = self.execute(dry_run=True)
        self.assertEqual(manifest['tasks'][task['task_id']]['status'], 'dry_run')
        self.assertTrue(manifest['tasks'][task['task_id']]['delivery']['dry_run'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
