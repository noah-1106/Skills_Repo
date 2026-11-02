import json
import sys
from pathlib import Path
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from web_region_capture.excel_delivery import deliver_excel

run = ROOT / 'data/runs/offline-poc'
source = run / '原始 提报表.xlsx'
output = run / '结果 提报表.xlsx'
workbook = Workbook()
workbook.active.title = '达人提报'
workbook.save(source)
images = {name: run / 'captures' / f'{name}.png' for name in ('gender', 'audience')}
result = deliver_excel(source, output, '达人提报', {'gender': 'C5', 'audience': 'D5'}, images, overwrite=False)
check = load_workbook(output)
assert len(check['达人提报']._images) == 2
(run / 'excel-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'source': str(source), 'result': result, 'images_readback': 2}, ensure_ascii=False, indent=2))
