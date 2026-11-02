from pathlib import Path
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.utils import column_index_from_string, get_column_letter
from PIL import Image as PILImage


class TargetUnsafe(RuntimeError):
    pass


def image_cell(image):
    marker = image.anchor._from
    return f'{get_column_letter(marker.col + 1)}{marker.row + 1}'


def deliver_excel(source, output, sheet, cells, images, overwrite=False):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise TargetUnsafe('Refusing to modify the source workbook in place')
    if output.exists() and not overwrite:
        raise TargetUnsafe('Output already exists; repeat delivery would duplicate images')
    workbook = load_workbook(source)
    if sheet not in workbook.sheetnames:
        raise TargetUnsafe(f'Missing worksheet: {sheet}')
    worksheet = workbook[sheet]
    existing = {image_cell(image) for image in worksheet._images}
    for region, cell in cells.items():
        if cell in existing or (worksheet[cell].value is not None and not overwrite):
            raise TargetUnsafe(f'Unsafe target: {sheet}!{cell}')
        with PILImage.open(images[region]) as source_image:
            width, height = source_image.size
        scale = min(1.0, 480 / width, 280 / height)
        image = Image(str(images[region]))
        image.width, image.height = round(width * scale), round(height * scale)
        worksheet.add_image(image, cell)
        column = get_column_letter(column_index_from_string(''.join(filter(str.isalpha, cell))))
        row = int(''.join(filter(str.isdigit, cell)))
        worksheet.column_dimensions[column].width = max(worksheet.column_dimensions[column].width or 0, image.width / 7)
        worksheet.row_dimensions[row].height = max(worksheet.row_dimensions[row].height or 0, image.height * 0.75)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    check = load_workbook(output)
    anchors = {image_cell(image) for image in check[sheet]._images}
    missing = set(cells.values()) - anchors
    if missing:
        raise TargetUnsafe(f'Readback missing anchors: {sorted(missing)}')
    return {'output': str(output), 'sheet': sheet, 'anchors': sorted(anchors)}
