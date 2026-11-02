"""Browser-side region boundary and purity gates.

Supported scope: ordinary, same-frame HTML elements with CSS layout. This is not
a universal website guarantee; iframe/canvas/shadow-DOM cases need their own
calibration and acceptance evidence.
"""
import json
from pathlib import Path

from PIL import Image

from .capture import CaptureError


INSPECT_JS = r"""
(element, config) => {
  const strategy = config.strategy || 'element_box';
  if (!['element_box', 'text_line_boxes'].includes(strategy)) {
    return {ok: false, code: 'REGION_BOUNDARY_INVALID', message: `Unsupported strategy: ${strategy}`};
  }
  const padding = Number(config.padding_px || 0);
  if (!Number.isFinite(padding) || padding < 0 || padding > 100) {
    return {ok: false, code: 'REGION_BOUNDARY_INVALID', message: 'padding_px must be between 0 and 100'};
  }
  const clean = r => ({x: r.x, y: r.y, left: r.left, top: r.top,
    right: r.right, bottom: r.bottom, width: r.width, height: r.height});
  const union = rects => {
    if (!rects.length) return null;
    const left = Math.min(...rects.map(r => r.left));
    const top = Math.min(...rects.map(r => r.top));
    const right = Math.max(...rects.map(r => r.right));
    const bottom = Math.max(...rects.map(r => r.bottom));
    return {left, top, right, bottom, x: left, y: top, width: right-left, height: bottom-top};
  };
  let rect = clean(element.getBoundingClientRect());
  let lineRects = [];
  if (strategy === 'text_line_boxes') {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue;
      const parent = node.parentElement;
      if (!parent) continue;
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (r.width > 0.5 && r.height > 0.5) lineRects.push(clean(r));
      }
    }
    const bounds = union(lineRects);
    if (!bounds) return {ok: false, code: 'REGION_NOT_READY', message: 'No visible text line boxes'};
    rect = bounds;
  }
  rect = {
    left: rect.left-padding, top: rect.top-padding,
    right: rect.right+padding, bottom: rect.bottom+padding,
    x: rect.left-padding, y: rect.top-padding,
    width: rect.width+2*padding, height: rect.height+2*padding
  };
  const visible = el => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0 && r.width > 0 && r.height > 0;
  };
  const intersection = (a, b) => {
    const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return width > 0.5 && height > 0.5 ? {width, height, area: width*height} : null;
  };
  const exclusions = [];
  for (const selector of config.exclude_selectors || []) {
    let matches;
    try { matches = document.querySelectorAll(selector); }
    catch (e) { return {ok: false, code: 'REGION_SELECTOR_INVALID', message: `${selector}: ${e.message}`}; }
    for (const el of matches) {
      if (!visible(el)) continue;
      const excludedRect = clean(el.getBoundingClientRect());
      const overlap = intersection(rect, excludedRect);
      if (overlap) exclusions.push({selector, rect: excludedRect, intersection: overlap});
    }
  }
  const allowedSelectors = config.allowed_overlay_selectors || [];
  const allowed = el => allowedSelectors.some(selector => {
    try { return el.matches(selector); } catch (_) { return false; }
  });
  const occlusionSamples = [];
  if (config.detect_occlusion !== false) {
    // Always sample the target box (including padding); text lines add glyph coverage.
    const sources = [rect, ...lineRects];
    for (const source of sources) {
      for (const fx of [0.05, 0.5, 0.95]) {
        for (const fy of [0.15, 0.5, 0.85]) {
          const x = source.left + source.width * fx;
          const y = source.top + source.height * fy;
          if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
          const stack = document.elementsFromPoint(x, y);
          const top = stack[0];
          const expected = top && (top === element || element.contains(top));
          if (top && !expected && !allowed(top)) {
            occlusionSamples.push({x, y, tag: top.tagName, id: top.id,
              class: typeof top.className === 'string' ? top.className : ''});
          }
        }
      }
    }
  }
  const uniqueSamples = [...new Map(occlusionSamples.map(s => [`${s.tag}|${s.id}|${s.class}`, s])).values()];
  const failed = exclusions.length || uniqueSamples.length;
  return {
    ok: !failed,
    code: exclusions.length ? 'REGION_NOT_PURE' : (uniqueSamples.length ? 'REGION_OCCLUDED' : null),
    message: exclusions.length ? 'Region intersects explicitly excluded elements' :
      (uniqueSamples.length ? 'Region has unexpected topmost elements' : 'Region purity checks passed'),
    strategy, padding_px: padding, rect, text_line_rect_count: lineRects.length,
    exclude_selectors: config.exclude_selectors || [], exclude_intersections: exclusions,
    occlusion: {detected: config.detect_occlusion !== false, samples_checked: true,
      unexpected: uniqueSamples, allowed_overlay_selectors: allowedSelectors},
    dom_mutated: false,
    scope: 'same-frame CSS-layout HTML; requires per-site visual acceptance'
  };
}
"""


def _recipe(value):
    if isinstance(value, str):
        return {'selector': value}
    if not isinstance(value, dict) or not isinstance(value.get('selector'), str):
        raise CaptureError('REGION_SELECTOR_INVALID', 'Region recipe requires a selector string')
    return value


def inspect_region(page, value):
    """Resolve one unique region and run side-effect-free browser checks."""
    recipe = _recipe(value)
    selector = recipe['selector']
    locator = page.locator(selector)
    count = locator.count()
    if count == 0:
        raise CaptureError('REGION_NOT_FOUND', f'{selector}: no match')
    if count != 1:
        raise CaptureError('REGION_AMBIGUOUS', f'{selector}: {count} matches')
    locator.scroll_into_view_if_needed()
    boundary = recipe.get('boundary', {})
    exclude = recipe.get('exclude', {})
    occlusion = recipe.get('occlusion', {})
    config = {
        'strategy': boundary.get('strategy', 'element_box'),
        'padding_px': boundary.get('padding_px', 0),
        'exclude_selectors': list(exclude.get('selectors', [])),
        'detect_occlusion': occlusion.get('detect', True),
        'allowed_overlay_selectors': list(occlusion.get('allowed_overlay_selectors', [])),
    }
    result = locator.evaluate(INSPECT_JS, config)
    result['selector'] = selector
    if not result['ok']:
        raise CaptureError(result['code'], result['message'], details=result)
    return locator, result


def capture_region(page, name, value, output_dir):
    """Capture only after all enabled gates pass; never hide or edit page nodes."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        locator, check = inspect_region(page, value)
    except CaptureError as error:
        failure = {'region': name, 'status': 'blocked', 'code': error.code,
                   'message': str(error), 'check': error.details}
        (output_dir / f'{name}-purity-check.json').write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + '\n')
        raise
    path = output_dir / f'{name}.png'
    recipe = _recipe(value)
    strategy = recipe.get('boundary', {}).get('strategy', 'element_box')
    if strategy == 'element_box':
        locator.screenshot(path=str(path), animations='disabled')
    else:
        rect = check['rect']
        # Re-read geometry at screenshot time; scrolling can change viewport coords.
        _, current = inspect_region(page, value)
        rect = current['rect']
        page.screenshot(path=str(path), animations='disabled', clip={
            'x': max(0, rect['left']), 'y': max(0, rect['top']),
            'width': rect['width'] - max(0, -rect['left']),
            'height': rect['height'] - max(0, -rect['top']),
        })
        check = current
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        if image.width < 2 or image.height < 2:
            raise CaptureError('REGION_NOT_READY', f'{name}: empty image')
        result = {'path': str(path), 'width': image.width, 'height': image.height}
    check_path = output_dir / f'{name}-purity-check.json'
    check_path.write_text(json.dumps({'region': name, 'status': 'passed', 'check': check},
                                     ensure_ascii=False, indent=2) + '\n')
    result['purity_check'] = str(check_path)
    return result


def capture_pure_regions(page, regions, output_dir):
    return {name: capture_region(page, name, recipe, output_dir)
            for name, recipe in regions.items()}
