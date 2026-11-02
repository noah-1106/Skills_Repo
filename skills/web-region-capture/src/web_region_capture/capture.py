from pathlib import Path
from PIL import Image


class CaptureError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


def assert_identity(page, selector, expected):
    locator = page.locator(selector)
    if locator.count() != 1:
        raise CaptureError('IDENTITY_MISMATCH', 'Identity anchor is not unique')
    actual = (locator.text_content() or '').strip()
    if actual != expected:
        raise CaptureError('IDENTITY_MISMATCH', f'Expected {expected!r}, got {actual!r}')
    return actual


def capture_regions(page, regions, output_dir):
    """Compatibility entry point; all captures use the shared purity gate."""
    from .region_purity import capture_pure_regions
    return capture_pure_regions(page, regions, output_dir)
