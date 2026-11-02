"""Client-independent M2 product core. All state transitions are file backed."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

from .capture import CaptureError, capture_regions
from .region_purity import capture_pure_regions
from .excel_delivery import deliver_excel, image_cell

SAFE_ID = re.compile(r'^[\w][\w .()\-]{0,119}$', re.UNICODE)
A1_CELL = re.compile(r'^[A-Za-z]+[1-9][0-9]*$')


class ProductError(RuntimeError):
    def __init__(self, message, code='PRODUCT_ERROR'):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def same_path(left, right):
    """Path identity: macOS /var -> /private/var symlinks and hardlinks both count."""
    try:
        return os.path.samefile(left, right)
    except OSError:
        return Path(left).resolve() == Path(right).resolve()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def project_path(root, value):
    """/./ selects project root; no resolved path may escape that root.

    The /./ form returns the lexical join (root is already resolved) so callers
    comparing against `root / name` do not see symlink re-expansion (/var ->
    /private/var). All other forms resolve fully before the containment check.
    """
    root = Path(root).resolve()
    text = str(value)
    if text.startswith('/./'):
        path = root / text[3:]
        normalized = Path(os.path.normpath(path))
        if normalized != root and root not in normalized.parents:
            raise ProductError(f'Path must stay inside project root: {value}', 'PATH_UNSAFE')
        return normalized
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path != root and root not in path.parents:
        raise ProductError(f'Path must stay inside project root: {value}', 'PATH_UNSAFE')
    return path


def file_evidence(path, expected_hash=None):
    path = Path(path)
    if not path.is_file():
        raise ProductError(f'Missing evidence: {path}', 'EVIDENCE_MISSING')
    result = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path)}
    if expected_hash is not None and result['sha256'] != expected_hash:
        raise ProductError(f'Evidence hash mismatch: {path}', 'EVIDENCE_HASH_MISMATCH')
    return result


def verify_evidence_bundle(bundle):
    if not isinstance(bundle, dict):
        raise ProductError('Evidence bundle is not an object', 'EVIDENCE_INVALID')
    result = {}
    for name, expected in bundle.items():
        actual = file_evidence(expected.get('path'), expected.get('sha256'))
        if actual['bytes'] != expected.get('bytes'):
            raise ProductError(f'Evidence size mismatch: {name}', 'EVIDENCE_HASH_MISMATCH')
        result[name] = actual
    return result


def verify_delivery(entry):
    """A delivery is reusable only after real target readback, never after dry-run."""
    if not isinstance(entry, dict) or entry.get('status') != 'delivered' or entry.get('dry_run') is not False:
        raise ProductError('Delivery is not a verified real delivery', 'DELIVERY_NOT_REUSABLE')
    kind = entry.get('type')
    if kind == 'folder':
        files = entry.get('files')
        if not isinstance(files, dict) or not files:
            raise ProductError('Folder delivery has no file manifest', 'DELIVERY_INVALID')
        for name, evidence in files.items():
            if Path(name).name != name or Path(name).suffix.lower() != '.png':
                raise ProductError('Unsafe folder delivery entry', 'DELIVERY_INVALID')
            verify_png(evidence.get('path'), evidence.get('sha256'))
    elif kind == 'excel':
        # Live adapter writes artifacts.workbook (file_evidence shape); older
        # runs used a flat output/sha256 pair. Both are accepted, never a
        # missing hash.
        artifact = entry.get('artifacts', {}).get('workbook') if isinstance(entry.get('artifacts'), dict) else None
        if artifact:
            output = Path(artifact.get('path', ''))
            entry = {**entry, 'output': str(output), 'sha256': artifact.get('sha256')}
        else:
            output = Path(entry.get('output', ''))
        if output.suffix.lower() != '.xlsx' or sha256(output) != entry.get('sha256'):
            raise ProductError('Excel output missing or changed', 'DELIVERY_HASH_MISMATCH')
        workbook = load_workbook(output)
        sheet = entry.get('sheet')
        cells = entry.get('cells')
        if sheet not in workbook.sheetnames or not isinstance(cells, dict):
            raise ProductError('Excel delivery metadata invalid', 'DELIVERY_INVALID')
        anchors = {image_cell(image) for image in workbook[sheet]._images}
        if set(cells.values()) != anchors:
            raise ProductError('Excel delivered anchors differ from manifest', 'DELIVERY_ANCHOR_MISMATCH')
    else:
        raise ProductError('Only folder/Excel deliveries are reusable locally', 'DELIVERY_NOT_REUSABLE')
    return True


def verify_png(path, expected_hash=None):
    evidence = file_evidence(path, expected_hash)
    try:
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise ValueError('not PNG')
            image.verify()
    except Exception as exc:
        raise ProductError(f'Invalid PNG evidence: {path}', 'CAPTURE_INVALID') from exc
    return evidence


def normalize_destination(raw, regions=None):
    """Return one flat canonical mapping; run() nests it as destination.mapping."""
    if not isinstance(raw, dict):
        raise ProductError('destination must be an object', 'CONFIG_INVALID')
    if 'mapping' in raw:
        if set(raw) != {'mapping'} or not isinstance(raw['mapping'], dict):
            raise ProductError('destination.mapping must be its only property', 'CONFIG_INVALID')
        raw = raw['mapping']
    kind = raw.get('type')
    if kind == 'lark_bitable':
        kind = 'base'
    if kind not in ('folder', 'excel', 'base'):
        raise ProductError('destination type must be folder, excel or base', 'CONFIG_INVALID')
    result = {'type': kind}
    if kind == 'folder':
        if not isinstance(raw.get('path'), str) or not raw['path']:
            raise ProductError('Folder path required', 'CONFIG_INVALID')
        result['path'] = raw['path']
    elif kind == 'excel':
        for key in ('source_path', 'path', 'sheet'):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise ProductError(f'Excel {key} required', 'CONFIG_INVALID')
        if any(Path(raw[key]).suffix.lower() != '.xlsx' for key in ('path', 'source_path')):
            raise ProductError('Only .xlsx files are supported', 'CONFIG_INVALID')
        cells = raw.get('cells')
        if not isinstance(cells, dict) or not cells:
            raise ProductError('Excel cells required', 'CONFIG_INVALID')
        if any(not isinstance(cell, str) or not A1_CELL.fullmatch(cell) for cell in cells.values()):
            raise ProductError('Excel cells must be A1 addresses', 'CONFIG_INVALID')
        if len({cell.upper() for cell in cells.values()}) != len(cells):
            raise ProductError('Excel cells must be unique', 'CONFIG_INVALID')
        overwrite = raw.get('overwrite', False)
        if not isinstance(overwrite, bool):
            raise ProductError('overwrite must be boolean', 'CONFIG_INVALID')
        result.update(source_path=raw['source_path'], path=raw['path'], sheet=raw['sheet'],
                      cells={key: value.upper() for key, value in cells.items()}, overwrite=overwrite)
    else:
        for key in ('base_token', 'table_id', 'record_id'):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise ProductError(f'Base {key} required', 'CONFIG_INVALID')
        fields = raw.get('fields')
        if not isinstance(fields, dict) or not fields or not all(isinstance(v, str) and v for v in fields.values()):
            raise ProductError('Base fields required', 'CONFIG_INVALID')
        if raw.get('mode', 'append') != 'append' or raw.get('allow_replace', False):
            raise ProductError('Base supports append only', 'CONFIG_INVALID')
        for key in ('allow_live_write', 'allow_replace'):
            if not isinstance(raw.get(key, False), bool):
                raise ProductError(f'{key} must be boolean', 'CONFIG_INVALID')
        result.update(base_token=raw['base_token'], table_id=raw['table_id'], record_id=raw['record_id'],
                      fields=fields, allow_live_write=raw.get('allow_live_write', False), allow_replace=False)
    if regions is not None:
        mapping_key = 'cells' if kind == 'excel' else 'fields' if kind == 'base' else None
        if mapping_key and set(result[mapping_key]) != set(regions):
            raise ProductError(f'{mapping_key} must map every region exactly once', 'CONFIG_INVALID')
    return result


def validate_task(task):
    if not isinstance(task, dict) or not isinstance(task.get('task_id'), str) or not SAFE_ID.fullmatch(task['task_id']):
        raise ProductError('Invalid task_id', 'CONFIG_INVALID')
    if not isinstance(task.get('regions'), list) or not task['regions'] or len(set(task['regions'])) != len(task['regions']):
        raise ProductError('Invalid regions', 'CONFIG_INVALID')
    normalize_destination(task.get('destination'), task['regions'])


def normalize_config(root, config_path, local_config_path=None):
    config_path = project_path(root, config_path)
    try:
        raw = read_json(config_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductError(f'Cannot read config: {exc}', 'CONFIG_INVALID') from exc
    if not isinstance(raw, dict) or raw.get('version') != 1 or not isinstance(raw.get('tasks'), list) or not raw['tasks']:
        raise ProductError('Config version 1 and tasks required', 'CONFIG_INVALID')
    inline, site_file = raw.get('site'), raw.get('site_file')
    if (inline is None) == (site_file is None):
        raise ProductError('Exactly one inline site or site_file required', 'CONFIG_INVALID')
    if inline is not None:
        if not isinstance(inline, dict):
            raise ProductError('Inline site must be object', 'CONFIG_INVALID')
        site = dict(inline)
        site_source = {'kind': 'inline', 'sha256': hashlib.sha256(canonical(site).encode()).hexdigest()}
    else:
        site_path = project_path(root, site_file)
        site = read_json(site_path)
        # Root-relative reference, not an absolute path: path spelling must not
        # change the frozen site hash when the project is opened via a symlink.
        site_source = {'kind': 'file', 'path': str(site_path.relative_to(root)), 'sha256': sha256(site_path)}
    if not isinstance(site, dict) or not isinstance(site.get('start_url'), str) or not site['start_url']:
        raise ProductError('site.start_url required', 'CONFIG_INVALID')
    if 'regions' not in site and 'recipes' in site:
        site['regions'] = site['recipes']
    if not isinstance(site.get('regions'), dict) or not site['regions']:
        raise ProductError('site.regions required', 'CONFIG_INVALID')
    tasks, ids = [], set()
    for source in raw['tasks']:
        validate_task(source)
        task = dict(source)
        if task['task_id'] in ids or any(name not in site['regions'] or not SAFE_ID.fullmatch(name) for name in task['regions']):
            raise ProductError('Duplicate task or unknown/unsafe region', 'CONFIG_INVALID')
        ids.add(task['task_id'])
        task['destination'] = {'mapping': normalize_destination(source['destination'], task['regions'])}
        # Delivery targets are user outputs, not general config paths: escaping
        # the project root is reported as OUTPUT_UNSAFE at validation time.
        if task['destination']['mapping']['type'] in ('folder', 'excel'):
            target_path(root, task)
        tasks.append(task)
    config = dict(raw, tasks=tasks)
    if local_config_path is None:
        local_path = root / 'config/local.json'
        if not local_path.exists():
            local_path = root / 'config/local.example.json'
    else:
        local_path = project_path(root, local_config_path)
    local = read_json(local_path) if local_path.exists() else {}
    # Frozen identity = raw bytes + normalized task config, NOT filesystem paths:
    # the same project opened through /var vs /private/var must still resume.
    frozen = {'config': {'sha256': sha256(config_path),
                         'normalized_sha256': hashlib.sha256(canonical(config).encode()).hexdigest()},
              'local_config': {'sha256': sha256(local_path) if local_path.exists() else None},
              'site': {'source': site_source, 'effective': site,
                       'sha256': hashlib.sha256(canonical(site).encode()).hexdigest()}}
    return config, local, frozen


def load_config(root, relative):
    config, _, frozen = normalize_config(Path(root).resolve(), relative)
    return {'version': 1, 'config_sha256': frozen['config']['sha256'], 'site': frozen['site']['effective'],
            'tasks': config['tasks']}


def destination_of(task):
    destination = task['destination']
    return destination['mapping'] if 'mapping' in destination else destination


def task_fingerprint(task):
    return hashlib.sha256(canonical(task).encode()).hexdigest()


def target_path(root, task):
    destination = destination_of(task)
    if destination['type'] not in ('folder', 'excel'):
        return None
    try:
        path = project_path(root, destination['path'])
    except ProductError as exc:
        if exc.code == 'PATH_UNSAFE':
            raise ProductError(f'Local output must be a new path inside project root: {destination["path"]}', 'OUTPUT_UNSAFE') from exc
        raise
    if path == root or root not in path.parents:
        raise ProductError(f'Local output must be a new path inside project root: {path}', 'OUTPUT_UNSAFE')
    return path


def planned_delivery(root, task, dry_run):
    target = target_path(root, task)
    return {'mode': destination_of(task)['type'], 'dry_run': dry_run, 'delivered': False,
            'status': 'dry_run' if dry_run else 'pending', 'target_path': str(target) if target else None}


def preflight_targets(root, tasks):
    targets, sources = {}, {}
    for task in tasks:
        target = target_path(root, task)
        if target is not None:
            if str(target) in targets:
                raise ProductError(f'Duplicate output target: {target}', 'OUTPUT_CONFLICT')
            targets[str(target)] = task['task_id']
        if destination_of(task)['type'] == 'excel':
            source = project_path(root, destination_of(task)['source_path'])
            sources[str(source)] = task['task_id']
    collision = set(targets) & set(sources)
    if collision:
        raise ProductError(f'Output cannot overwrite a source workbook: {sorted(collision)}', 'SOURCE_UNSAFE')
    for task in tasks:
        if destination_of(task)['type'] == 'excel':
            inspect_excel_source(root, task)


def inspect_excel_source(root, task):
    destination = destination_of(task)
    if destination['type'] != 'excel':
        return None
    source = project_path(root, destination['source_path'])
    if source == target_path(root, task):
        raise ProductError('Source workbook cannot be modified in place', 'SOURCE_UNSAFE')
    evidence = file_evidence(source)
    workbook = load_workbook(source)
    try:
        if destination['sheet'] not in workbook.sheetnames:
            raise ProductError(f"Missing worksheet: {destination['sheet']}", 'SHEET_MISSING')
        worksheet = workbook[destination['sheet']]
        anchors = {image_cell(image) for image in worksheet._images}
        unsafe = [cell for cell in destination['cells'].values()
                  if (worksheet[cell].value is not None or cell in anchors) and not destination['overwrite']]
        if unsafe:
            raise ProductError(f'Unsafe Excel cells: {unsafe}', 'CELL_UNSAFE')
    finally:
        workbook.close()
    return {'path': evidence['path'], 'bytes': evidence['bytes'], 'sha256': evidence['sha256'],
            'source_sha256': evidence['sha256'], 'sheet': destination['sheet'], 'cells': dict(destination['cells'])}


def official_cli(args, cli, runner=None, timeout=60):
    run = runner or (lambda command, timeout: subprocess.run(command, capture_output=True, text=True, timeout=timeout))
    response = run([cli, *args], timeout=timeout)
    if response.returncode != 0:
        raise ProductError(f'lark-cli failed: {response.stderr[-2000:]}', 'LARK_CLI_FAILED')
    return response.stdout


def base_delivery(task, run_dir, local, runner=None):
    destination, calls = destination_of(task), []
    cli, prefix = local.get('lark_cli_path', 'lark-cli'), list(local.get('lark_args', []))
    # lark-cli rejects absolute --file paths: it must be relative to the process
    # cwd. Bind cwd on the default runner only, so injected mock runners keep
    # their (command, timeout) signature and calls stay plain argv lists.
    capture_dir = run_dir / 'captures' / task['task_id']
    if runner is None:
        runner = lambda command, timeout: subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, cwd=str(capture_dir))
    for region, field in destination['fields'].items():
        command = [*prefix, 'base', '+record-upload-attachment', '--base-token', destination['base_token'],
                   '--table-id', destination['table_id'], '--record-id', destination['record_id'], '--field-id', field,
                   '--file', f'./{region}.png', '--as', 'user', '--dry-run']
        calls.append(command)
    responses = [json.loads(official_cli(command, cli, runner)) for command in calls]
    return {'mode': 'base', 'dry_run': True, 'delivered': False, 'status': 'dry_run', 'calls': calls,
            'responses': responses, 'requires_readback_before_delivery': True}


def validate_frozen(manifest, frozen):
    if manifest.get('frozen') != frozen:
        raise ProductError('Resume refused: root/config/site/local environment changed', 'FROZEN_CONFIG_CHANGED')


def reusable(state, task, root):
    """Validate the complete chain: frozen task -> capture -> purity -> target readback."""
    try:
        if state.get('status') != 'delivered' or state.get('task_fingerprint') != task_fingerprint(task):
            return False
        delivery = state['delivery']
        # target_path may be spelled via a symlink (/var vs /private/var); compare
        # resolved paths, never raw strings.
        if delivery.get('delivered') is not True or Path(delivery['target_path']).resolve() != target_path(root, task).resolve():
            return False
        verify_delivery(delivery)
        for name in task['regions']:
            capture = state['evidence']['captures'][name]
            report = state['evidence']['purity_reports'][name]
            verify_png(capture['path'], capture['sha256'])
            file_evidence(report['path'], report['sha256'])
            check = read_json(report['path'])
            if (check.get('status') != 'passed' or check.get('region') != name
                    or check.get('check', {}).get('ok') is not True):
                return False
            if destination_of(task)['type'] == 'folder':
                delivered_file = delivery['files'][f'{name}.png']
                # files entries are evidence dicts ({path, bytes, sha256});
                # accept a bare path string only for legacy manifests.
                if isinstance(delivered_file, dict):
                    verify_png(delivered_file['path'], capture['sha256'])
                else:
                    file_evidence(delivered_file, capture['sha256'])
        if destination_of(task)['type'] == 'excel':
            source = state['evidence']['source']
            if Path(source['path']).resolve() != project_path(root, destination_of(task)['source_path']).resolve():
                return False
            file_evidence(source['path'], source['sha256'])
            if delivery['sheet'] != destination_of(task)['sheet'] or delivery['cells'] != destination_of(task)['cells']:
                return False
        return True
    except (OSError, KeyError, TypeError, ValueError, ProductError, json.JSONDecodeError):
        return False


def preflight_delivery(root, task, state):
    """Preflight each pending task immediately before writing, not before browser work."""
    destination = destination_of(task)
    if destination['type'] == 'excel':
        current = inspect_excel_source(root, task)
        if current['sha256'] != state['evidence']['source']['sha256']:
            raise ProductError('Source workbook changed before delivery', 'SOURCE_HASH_MISMATCH')
    target = target_path(root, task)
    if target is not None and target.exists():
        raise ProductError(f'Refusing existing output: {target}', 'OUTPUT_CONFLICT')


def deliver_local(root, task, run_dir, execute, state=None):
    """Deliver captured evidence to a local folder/Excel target.

    ``task`` is the normalized config task; capture evidence lives on the
    per-run manifest ``state``, so it is passed explicitly rather than guessed
    via task.get('evidence').
    """
    destination = destination_of(task)
    if destination['type'] not in ('folder', 'excel'):
        raise ProductError('Non-local delivery passed to local adapter', 'DELIVERY_INVALID')
    if not execute:
        return planned_delivery(root, task, True)
    if state is None:
        raise ProductError('deliver_local() requires manifest task state carrying capture evidence', 'DELIVERY_INVALID')
    evidence = state['evidence']
    target = target_path(root, task)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck for races immediately before creating the staging directory.
    if target.exists():
        raise ProductError(f'Refusing existing output: {target}', 'OUTPUT_CONFLICT')
    staging_dir = Path(tempfile.mkdtemp(prefix=f'.{target.name}.pending-', dir=target.parent))
    try:
        if destination['type'] == 'folder':
            artifacts = {}
            for region in task['regions']:
                source = Path(evidence['captures'][region]['path'])
                staged = staging_dir / f'{region}.png'
                shutil.copyfile(source, staged)
                artifacts[staged.name] = verify_png(staged, evidence['captures'][region]['sha256'])
            os.replace(staging_dir, target)
            # Re-key evidence to the final paths: after os.replace the staging
            # directory no longer exists, so staging paths are dead pointers.
            for name, expected in artifacts.items():
                artifacts[name] = verify_png(target / name, expected['sha256'])
            readback = {'files': sorted(artifacts)}
        else:
            source = project_path(root, destination['source_path'])
            images = {region: evidence['captures'][region]['path'] for region in task['regions']}
            staged = staging_dir / target.name
            result = deliver_excel(source, staged, destination['sheet'], destination['cells'], images,
                                   overwrite=destination['overwrite'])
            if sha256(source) != evidence['source']['sha256']:
                raise ProductError('Source workbook changed during delivery', 'SOURCE_HASH_MISMATCH')
            staged_hash = sha256(staged)
            os.replace(staged, target)
            artifact = file_evidence(target, staged_hash)
            workbook = load_workbook(target)
            try:
                anchors = sorted(image_cell(image) for image in workbook[destination['sheet']]._images)
            finally:
                workbook.close()
            if anchors != sorted(result['anchors']) or not set(destination['cells'].values()).issubset(anchors):
                raise ProductError('Excel final readback mismatch', 'READBACK_FAILED')
            artifacts = {'workbook': artifact}
            readback = {'anchors': anchors, 'source_sha256_after': sha256(source)}
        receipt = {'type': destination['type'], 'dry_run': False, 'delivered': True, 'status': 'delivered',
                   'target_path': str(target), 'anchors': anchors if destination['type'] == 'excel' else None,
                   'output_sha256': artifact['sha256'] if destination['type'] == 'excel' else None,
                   'artifacts': artifacts, 'readback': readback}
        # Reuse contract consumed by verify_delivery()/reusable(); keep in sync with both.
        if destination['type'] == 'folder':
            # files maps "name.png" -> evidence dict; output is the folder path.
            receipt['files'] = dict(artifacts)
            receipt['output'] = str(target)
        else:
            receipt['output'] = str(target)
            receipt['sha256'] = artifact['sha256']
            receipt['sheet'] = destination['sheet']
            receipt['cells'] = dict(destination['cells'])
        return receipt
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def navigate_and_capture(root, site, tasks, run_dir, local):
    from playwright.sync_api import sync_playwright
    if local.get('browser', {}).get('driver', 'playwright') != 'playwright' or local.get('browser', {}).get('channel', 'chromium') != 'chromium':
        raise ProductError('Only managed Playwright Chromium is implemented', 'DRIVER_NOT_IMPLEMENTED')
    browser_path = Path(local.get('browser_path', root / 'runtime/ms-playwright')).expanduser().resolve()
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browser_path)
    temporary = root / 'runtime/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    results = {}
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        if browser_path not in executable.parents:
            raise ProductError('Refusing non-managed browser', 'BROWSER_UNSAFE')
        browser = playwright.chromium.launch(headless=site.get('headless', True))
        try:
            page = browser.new_page(viewport=site.get('viewport', {'width': 1440, 'height': 1000}), device_scale_factor=1)
            start_url = site['start_url']
            # Absolute URLs (including local file:// fixtures) are used verbatim;
            # only bare paths are resolved against the project root.
            if not re.match(r'^[A-Za-z][A-Za-z0-9+.\-]*://', start_url):
                start_url = project_path(root, start_url).as_uri()
            page.goto(start_url, wait_until='domcontentloaded')
            bindings = {}
            for action in site.get('actions', []):
                kind = action.get('type', action.get('action'))
                if kind not in ('fill', 'click', 'wait_for_selector'):
                    raise ProductError('Navigation action not allowed', 'ACTION_NOT_ALLOWED')
                if kind == 'fill':
                    value = action.get('value')
                    if action.get('value_from') == 'subject_query':
                        values = {task['subject_query'] for task in tasks}
                        if len(values) != 1:
                            raise ProductError('Mixed subject queries need separate site runs', 'SUBJECT_AMBIGUOUS')
                        value = values.pop()
                    page.locator(action['selector']).fill(value)
                    bindings['subject_query'] = value
                elif kind == 'click':
                    page.locator(action['selector']).click()
                else:
                    page.locator(action['selector']).wait_for(state='visible')
            identity = site.get('identity')
            if identity:
                locator = page.locator(identity['selector'])
                if locator.count() != 1:
                    raise ProductError('Identity anchor not unique', 'IDENTITY_MISMATCH')
                actual = (locator.text_content() or '').strip()
                expected = bindings.get(identity.get('expected_from'), identity.get('equals'))
                if actual != expected:
                    raise ProductError(f'Identity mismatch: {actual!r} != {expected!r}', 'IDENTITY_MISMATCH')
            for task in tasks:
                results[task['task_id']] = capture_pure_regions(page, {name: site['regions'][name] for name in task['regions']},
                                                              run_dir / 'captures' / task['task_id'])
        finally:
            browser.close()
    return {'captures': results}


def doctor(root, local_path=None, check_browser=True):
    root = Path(root).resolve()
    local_path = project_path(root, local_path) if local_path else root / 'config/local.json'
    local = read_json(local_path) if local_path.exists() else {}
    browser_path = project_path(root, local.get('browser_path', 'runtime/ms-playwright'))
    try:
        import playwright
        imported = True
    except ImportError:
        imported = False
    lark = shutil.which(local.get('lark_cli_path', 'lark-cli'))
    checks = [{'name': 'python', 'status': 'pass'},
              {'name': 'playwright_import', 'status': 'pass' if imported else 'fail'},
              {'name': 'playwright_chromium', 'status': 'pass' if browser_path.exists() else 'fail'},
              {'name': 'opencli', 'status': 'skipped', 'detail': 'Not selected; not an implemented runner'},
              {'name': 'lark_cli', 'status': 'pass' if lark else 'skipped'}]
    result = {'ok': imported and browser_path.exists(), 'project_root': str(root), 'browser_path': str(browser_path), 'checks': checks}
    if check_browser and result['ok']:
        previous = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browser_path)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path)
                if browser_path not in executable.parents or not executable.is_file():
                    raise ProductError(f'Wrong Chromium location: {executable}')
                browser = playwright.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:
            result['ok'] = False
            checks.append({'name': 'browser_launch', 'status': 'fail', 'detail': str(exc)})
        finally:
            if previous is None:
                os.environ.pop('PLAYWRIGHT_BROWSERS_PATH', None)
            else:
                os.environ['PLAYWRIGHT_BROWSERS_PATH'] = previous
    return result


def run(root, config_path, local_config_path=None, run_id=None, resume=False, dry_run=True,
        execute_local=None, authorize_lark_write=False, runner=None, lark_runner=None, capture_runner=navigate_and_capture):
    root = Path(root).resolve()
    # navigate_and_capture sets process-global TMPDIR for its browser subprocess;
    # restore it even on failure so later runs/tests in this process are unaffected.
    previous_tmpdir = os.environ.get('TMPDIR')
    try:
        return _run(root, config_path, local_config_path, run_id, resume, dry_run,
                    execute_local, authorize_lark_write, runner, lark_runner, capture_runner)
    finally:
        if previous_tmpdir is None:
            os.environ.pop('TMPDIR', None)
        else:
            os.environ['TMPDIR'] = previous_tmpdir


def _run(root, config_path, local_config_path=None, run_id=None, resume=False, dry_run=True,
        execute_local=None, authorize_lark_write=False, runner=None, lark_runner=None, capture_runner=navigate_and_capture):
    if run_id is None:
        from datetime import datetime, timezone
        run_id = 'run-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    if not SAFE_ID.fullmatch(run_id):
        raise ProductError('Unsafe run_id', 'CONFIG_INVALID')
    if execute_local is not None:
        if dry_run is not True and dry_run == execute_local:
            raise ProductError('Conflicting delivery flags', 'CONFIG_INVALID')
        dry_run = not execute_local
    config_path = project_path(root, config_path)
    config, local, frozen = normalize_config(root, config_path, local_config_path)
    if local.get('browser', {}).get('driver', 'playwright') != 'playwright' or local.get('browser', {}).get('channel', 'chromium') != 'chromium':
        raise ProductError('Only managed Playwright Chromium is implemented', 'DRIVER_NOT_IMPLEMENTED')
    runner = lark_runner or runner
    for task in config['tasks']:
        if destination_of(task)['type'] == 'base' and (not dry_run or authorize_lark_write):
            if not authorize_lark_write or not destination_of(task)['allow_live_write']:
                raise ProductError('Real Base write requires both task and CLI authorization', 'LARK_WRITE_NOT_AUTHORIZED')
            raise ProductError('Live Base requires M2C readback/download/hash reconciliation', 'LARK_LIVE_NOT_IMPLEMENTED')
    run_dir = root / 'data/runs' / run_id
    manifest_path = run_dir / 'manifest.json'
    if manifest_path.exists():
        if not resume:
            raise ProductError('Run exists; explicit resume required', 'RUN_EXISTS')
        manifest = read_json(manifest_path)
        if manifest.get('root') != str(root):
            raise ProductError('Resume refused: project root changed', 'RESUME_MISMATCH')
        for key in ('frozen_config', 'frozen_site'):
            evidence = manifest.get(key, {})
            if not evidence.get('sha256'):
                raise ProductError(f'Resume refused: missing {key} evidence', 'RESUME_MISMATCH')
            try:
                file_evidence(evidence.get('path'), evidence['sha256'])
            except ProductError as exc:
                raise ProductError(f'Resume refused: {key} changed ({exc})', 'RESUME_MISMATCH') from exc
        site_file = run_dir / 'site.json'
        if not site_file.is_file() or read_json(site_file) != frozen['site']['effective']:
            raise ProductError('Resume refused: frozen site changed', 'RESUME_MISMATCH')
        validate_frozen(manifest, frozen)
        expected_ids = {task['task_id'] for task in config['tasks']}
        if set(manifest.get('tasks', {})) != expected_ids:
            raise ProductError('Resume task IDs changed', 'TASK_CONFIG_CHANGED')
        for task in config['tasks']:
            if manifest['tasks'][task['task_id']].get('task_fingerprint') != task_fingerprint(task):
                raise ProductError('Resume task configuration changed', 'TASK_CONFIG_CHANGED')
    else:
        if resume:
            raise ProductError('Cannot resume without manifest', 'RUN_NOT_FOUND')
        run_dir.mkdir(parents=True, exist_ok=False)
        preflight_targets(root, config['tasks'])
        # Frozen config/site are real artifacts so resume can verify their bytes.
        frozen_config_file = run_dir / 'config.json'
        frozen_site_file = run_dir / 'site.json'
        write_json(frozen_config_file, read_json(config_path))
        write_json(frozen_site_file, frozen['site']['effective'])
        manifest = {'version': 1, 'run_id': run_id, 'root': str(root), 'frozen': frozen,
                    'config_sha256': sha256(frozen_config_file), 'site_sha256': sha256(frozen_site_file),
                    'frozen_config': file_evidence(frozen_config_file),
                    'frozen_site': file_evidence(frozen_site_file), 'tasks': {}}
        for task in config['tasks']:
            manifest['tasks'][task['task_id']] = {'task_fingerprint': task_fingerprint(task), 'status': 'planned',
                'evidence': {'captures': {}, 'purity_reports': {}, 'source': inspect_excel_source(root, task)},
                'delivery': planned_delivery(root, task, True)}
        write_json(manifest_path, manifest)
    preflight_targets(root, config['tasks'])
    pending = []
    for task in config['tasks']:
        state = manifest['tasks'][task['task_id']]
        if reusable(state, task, root):
            state['resumed'] = True
            continue
        if destination_of(task)['type'] != 'base' and state['evidence']['source'] is None:
            state['evidence']['source'] = inspect_excel_source(root, task)
        if state.get('status') == 'delivered':
            raise ProductError('Delivered evidence/output failed reconciliation', 'RESUME_MISMATCH')
        target = target_path(root, task)
        if target is not None and target.exists():
            raise ProductError(f'Existing non-reusable target: {target}', 'OUTPUT_CONFLICT')
        pending.append(task)
    if pending:
        # Validate all requested inputs before any delivery, preventing partial success.
        preflight_targets(root, config['tasks'])
        for task in pending:
            manifest['tasks'][task['task_id']]['status'] = 'capturing'
        write_json(manifest_path, manifest)
        navigation = capture_runner(root, frozen['site']['effective'], pending, run_dir, local)
        for task in pending:
            state = manifest['tasks'][task['task_id']]
            captures = navigation['captures'][task['task_id']]
            if set(captures) != set(task['regions']):
                raise ProductError('Captured regions do not match request', 'CAPTURE_INVALID')
            state['evidence']['captures'] = {name: file_evidence(item['path']) for name, item in captures.items()}
            state['evidence']['purity_reports'] = {name: file_evidence(item['purity_check']) for name, item in captures.items()}
            state['status'] = 'captured'
            write_json(manifest_path, manifest)
        # Second phase starts only after all pending capture evidence exists.
        for task in pending:
            state = manifest['tasks'][task['task_id']]
            if destination_of(task)['type'] == 'base':
                state['delivery'] = base_delivery(task, run_dir, local, runner)
                state['status'] = 'dry_run'
            else:
                state['delivery'] = deliver_local(root, task, run_dir, not dry_run, state)
                state['status'] = 'delivered' if not dry_run else 'dry_run'
            write_json(manifest_path, manifest)
    manifest['status'] = 'complete'
    write_json(manifest_path, manifest)
    return manifest
