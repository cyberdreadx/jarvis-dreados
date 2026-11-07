"""draw_chart: bar, line, area, pie, donut and scatter charts drawn as DreadOS-styled SVG.

Pure standard library and deterministic. All user text is escaped with svgkit.esc.
"""
import math

from . import svgkit
from .svgkit import COLORS, SERIES, esc

TYPES = ('bar', 'horizontal_bar', 'stacked_bar', 'line', 'area', 'pie', 'donut', 'scatter')
MAX_LABELS = 50
MAX_SERIES = 8
MAX_VALUES = 200
WIDTH, HEIGHT = 760, 440
CURRENCY = ('$', '€', '£', '¥', '₹', '₩', '₽', '₿', 'US$', 'A$', 'C$', 'R$', 'HK$', 'NZ$')

TOOLS = [{
    'name': 'draw_chart',
    'description': (
        'Draw a data chart as an image. Use this instead of image generation for ANY chart or graph. '
        'Pass type (bar, horizontal_bar, stacked_bar, line, area, pie, donut, scatter), labels '
        '(category names) and series: [{name, values}] with one number per label. Scatter: values are '
        '[x, y] pairs. Pie/donut: one series. Optional: title, x_label, y_label, unit ("$", "%", "kg"), '
        'show_values.'),
    'inputSchema': {
        'type': 'object', 'additionalProperties': False, 'required': ['type', 'series'],
        'properties': {
            'type': {'type': 'string', 'enum': list(TYPES), 'description': 'Chart type.'},
            'title': {'type': 'string', 'maxLength': 120},
            'labels': {'type': 'array', 'maxItems': MAX_LABELS, 'description': 'Category labels, one per value.',
                       'items': {'type': ['string', 'number'], 'maxLength': 40}},
            'series': {
                'type': 'array', 'minItems': 1, 'maxItems': MAX_SERIES,
                'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['values'],
                    'properties': {
                        'name': {'type': 'string', 'maxLength': 40},
                        'values': {'type': 'array', 'minItems': 1, 'maxItems': MAX_VALUES, 'items': {
                            'anyOf': [{'type': 'number'},
                                      {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number'}}]}},
                    }}},
            'x_label': {'type': 'string', 'maxLength': 60},
            'y_label': {'type': 'string', 'maxLength': 60},
            'unit': {'type': 'string', 'maxLength': 8, 'description': 'Unit shown on values, e.g. "$", "%", "kg".'},
            'show_values': {'type': 'boolean', 'description': 'Print the value on each bar/point/slice.'},
        }},
}]


class InputError(ValueError):
    """Bad user input: reported back as a friendly message, never raised out of call()."""


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


# ---------------------------------------------------------------- numbers and text

def nice_step(raw):
    """Smallest 1/2/5 x 10^n step that is >= raw."""
    if not raw > 0 or not math.isfinite(raw):
        return 1.0
    exponent = math.floor(math.log10(raw))
    fraction = raw / 10 ** exponent
    for nice in (1, 2, 5, 10):
        if fraction <= nice * (1 + 1e-9):
            break
    return float(f'{nice * 10 ** exponent:.12g}')


def nice_ticks(lo, hi, target=5, include_zero=False):
    """Evenly spaced 'nice' ticks (1/2/5 x 10^n steps) covering [lo, hi]."""
    lo, hi = float(lo), float(hi)
    if lo > hi:
        lo, hi = hi, lo
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.1 or 1.0
        lo, hi = (lo - pad, hi + pad) if not include_zero else (min(lo, 0.0), max(hi, 0.0) or pad)
        if include_zero and lo == hi:
            hi = lo + 1
    step = nice_step((hi - lo) / max(1, target))
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    decimals = max(0, -math.floor(math.log10(step)) + 1)
    count = int(round((end - start) / step))
    return [round(start + i * step, decimals) + 0.0 for i in range(count + 1)]


def _trim(text):
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _attach_unit(number_text, negative, unit):
    sign = '-' if negative else ''
    if not unit:
        return sign + number_text
    if unit in CURRENCY:
        return f'{sign}{unit}{number_text}'
    if len(unit) == 1 and not unit.isalnum() or unit.startswith('°'):
        return f'{sign}{number_text}{unit}'
    return f'{sign}{number_text} {unit}'


def fmt_value(value, unit=''):
    """Human value label: thousands separators, up to 2 decimals, M/B for very large numbers."""
    a = abs(value)
    if a >= 1e12:
        text = _trim(f'{a / 1e12:,.2f}') + 'T'
    elif a >= 1e9:
        text = _trim(f'{a / 1e9:.2f}') + 'B'
    elif a >= 1e6:
        text = _trim(f'{a / 1e6:.2f}') + 'M'
    elif a and a < 0.01:
        text = f'{a:.2g}'
    else:
        text = _trim(f'{a:,.2f}')
    return _attach_unit(text, value < 0 and text.strip('0.') != '', unit)


def fmt_tick(value, step, biggest, unit=''):
    """Axis tick label: k/M/B abbreviations once ticks reach 10,000."""
    div, suffix = 1, ''
    for limit, d, s in ((1e12, 1e12, 'T'), (1e9, 1e9, 'B'), (1e6, 1e6, 'M'), (1e4, 1e3, 'k')):
        if biggest >= limit:
            div, suffix = d, s
            break
    decimals = max(0, -math.floor(math.log10(step / div) + 1e-9))
    text = _trim(f'{abs(value) / div:,.{decimals}f}')
    if text == '0':
        suffix = ''
    return _attach_unit(text + suffix, value < 0 and text != '0', unit)


def text_width(text, size):
    """Rough rendered width of text in Segoe UI at the given font size."""
    total = 0.0
    for ch in str(text):
        if ch in "il.,:;|!'`jtfr()[] ":
            total += 0.32
        elif ch in 'mwMW@%':
            total += 0.86
        elif ch.isupper() or ch in '&#':
            total += 0.66
        elif ch.isdigit():
            total += 0.56
        else:
            total += 0.54
    return total * size


def _clip(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + '…'


def _color(i):
    base = SERIES[i % len(SERIES)]
    rnd = i // len(SERIES)
    if not rnd:
        return base
    r, g, b = (int(base[k:k + 2], 16) for k in (1, 3, 5))
    t = 0.45 if rnd % 2 else 0.35
    if rnd % 2:  # lighter
        r, g, b = (int(c + (255 - c) * t) for c in (r, g, b))
    else:  # darker
        r, g, b = (int(c * (1 - t)) for c in (r, g, b))
    return f'#{r:02x}{g:02x}{b:02x}'


def _f(v):
    """Compact coordinate formatting."""
    return _trim(f'{v:.2f}')


class _Placer:
    """Keeps text boxes from overlapping: place() returns False if the box hits an earlier one."""

    def __init__(self):
        self.boxes = []

    def place(self, x0, y0, x1, y1, pad=1.5):
        for a in self.boxes:
            if x0 < a[2] + pad and x1 > a[0] - pad and y0 < a[3] + pad and y1 > a[1] - pad:
                return False
        self.boxes.append((x0, y0, x1, y1))
        return True


def _text(x, y, text, size=12, fill=None, anchor='start', weight=None, extra=''):
    attrs = f'x="{_f(x)}" y="{_f(y)}" font-size="{size}" fill="{fill or COLORS["sub"]}"'
    if anchor != 'start':
        attrs += f' text-anchor="{anchor}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    return f'<text {attrs}{extra}>{esc(text)}</text>'


# ---------------------------------------------------------------- validation

def _number(value, where):
    if isinstance(value, bool):
        raise InputError(f'{where} must be a number, not true/false.')
    if isinstance(value, str):
        cleaned = value.strip().replace(',', '').replace('$', '').replace('%', '')
        try:
            value = float(cleaned)
        except ValueError:
            raise InputError(f'{where} must be a number (got "{_clip(value, 20)}").') from None
    if not isinstance(value, (int, float)):
        raise InputError(f'{where} must be a number.')
    value = float(value)
    if not math.isfinite(value):
        raise InputError(f'{where} must be a finite number.')
    if abs(value) > 1e15:
        raise InputError(f'{where} is too large (limit 1e15).')
    return value


def _text_arg(arguments, key, limit):
    value = arguments.get(key)
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise InputError(f'"{key}" must be text.')
    value = ' '.join(str(value).split())
    if len(value) > limit:
        raise InputError(f'"{key}" is too long (max {limit} characters).')
    return value


def validate(arguments):
    if not isinstance(arguments, dict):
        raise InputError('Pass an object like {"type": "bar", "labels": [...], "series": [{"name": ..., "values": [...]}]}.')
    unknown = sorted(set(arguments) - set(TOOLS[0]['inputSchema']['properties']))
    if unknown:
        raise InputError(f'Unknown field(s): {", ".join(unknown)}. Allowed: type, title, labels, series, x_label, y_label, unit, show_values.')
    kind = str(arguments.get('type') or '').strip().lower().replace('-', '_').replace(' ', '_')
    kind = {'column': 'bar', 'hbar': 'horizontal_bar', 'stacked': 'stacked_bar', 'doughnut': 'donut'}.get(kind, kind)
    if kind not in TYPES:
        raise InputError(f'"type" must be one of: {", ".join(TYPES)}.')
    spec = {'type': kind,
            'title': _text_arg(arguments, 'title', 120),
            'x_label': _text_arg(arguments, 'x_label', 60),
            'y_label': _text_arg(arguments, 'y_label', 60),
            'unit': _text_arg(arguments, 'unit', 8)}
    show = arguments.get('show_values')
    if show is not None and not isinstance(show, bool):
        raise InputError('"show_values" must be true or false.')
    spec['show_values'] = show

    labels = arguments.get('labels')
    if labels is None:
        labels = []
    if not isinstance(labels, list):
        raise InputError('"labels" must be a list of category names.')
    if len(labels) > MAX_LABELS:
        raise InputError(f'Too many labels ({len(labels)}); the limit is {MAX_LABELS}.')
    clean_labels = []
    for i, label in enumerate(labels):
        if label is None or isinstance(label, (dict, list, bool)):
            raise InputError(f'Label {i + 1} must be text.')
        label = ' '.join(str(label).split())
        if len(label) > 40:
            raise InputError(f'Label {i + 1} is too long (max 40 characters).')
        clean_labels.append(label)

    series = arguments.get('series')
    if not isinstance(series, list) or not series:
        raise InputError('"series" must be a non-empty list like [{"name": "Sales", "values": [1, 2, 3]}].')
    if len(series) > MAX_SERIES:
        raise InputError(f'Too many series ({len(series)}); the limit is {MAX_SERIES}.')
    clean_series = []
    for si, item in enumerate(series):
        if isinstance(item, list):  # tolerate a bare list of values
            item = {'values': item}
        if not isinstance(item, dict):
            raise InputError(f'Series {si + 1} must be an object like {{"name": "Sales", "values": [1, 2]}}.')
        extra = sorted(set(item) - {'name', 'values'})
        if extra:
            raise InputError(f'Series {si + 1} has unknown field(s): {", ".join(extra)}. Use name and values.')
        name = item.get('name')
        name = ' '.join(str(name).split()) if name not in (None, '') else f'Series {si + 1}'
        if len(name) > 40:
            raise InputError(f'Series {si + 1} name is too long (max 40 characters).')
        values = item.get('values')
        if not isinstance(values, list) or not values:
            raise InputError(f'Series "{name}" needs a non-empty "values" list.')
        if len(values) > MAX_VALUES:
            raise InputError(f'Series "{name}" has {len(values)} values; the limit is {MAX_VALUES}.')
        if kind == 'scatter':
            points = []
            for vi, pair in enumerate(values):
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise InputError(f'Scatter series "{name}": value {vi + 1} must be an [x, y] pair.')
                points.append((_number(pair[0], f'Series "{name}" point {vi + 1} x'),
                               _number(pair[1], f'Series "{name}" point {vi + 1} y')))
            clean_series.append({'name': name, 'values': points})
        else:
            nums = []
            for vi, v in enumerate(values):
                if isinstance(v, (list, tuple)):
                    raise InputError(f'Series "{name}": value {vi + 1} must be a single number ([x, y] pairs are only for scatter).')
                nums.append(_number(v, f'Series "{name}" value {vi + 1}'))
            clean_series.append({'name': name, 'values': nums})

    if kind != 'scatter':
        count = len(clean_series[0]['values'])
        if not clean_labels:
            if any(len(s['values']) != count for s in clean_series):
                raise InputError('All series must have the same number of values.')
            clean_labels = [str(i + 1) for i in range(count)]
        for s in clean_series:
            if len(s['values']) != len(clean_labels):
                raise InputError(f'Series "{s["name"]}" has {len(s["values"])} values but there are '
                                 f'{len(clean_labels)} labels; they must match one-to-one.')
        if kind in ('bar', 'horizontal_bar', 'stacked_bar', 'pie', 'donut') and len(clean_labels) > MAX_LABELS:
            raise InputError(f'Too many categories; the limit is {MAX_LABELS}.')
    if kind in ('pie', 'donut'):
        if len(clean_series) != 1:
            raise InputError('Pie and donut charts take exactly one series (one value per slice). '
                             'Use a bar or stacked_bar chart to compare several series.')
        values = clean_series[0]['values']
        if any(v < 0 for v in values):
            raise InputError('Pie and donut values must not be negative.')
        if sum(values) <= 0:
            raise InputError('Pie and donut values must add up to more than zero.')
    spec['labels'] = clean_labels
    spec['series'] = clean_series
    return spec


# ---------------------------------------------------------------- shared pieces

def _legend(items, y, width, x0=18):
    """Horizontal, wrapping legend. Returns (elements, height)."""
    out, x, row = [], x0, 0
    for color, name in items:
        name = _clip(name, 32)
        w = 12 + 6 + text_width(name, 12) + 18
        if x + w > width - 18 and x > x0:
            x, row = x0, row + 1
        yy = y + row * 20
        out.append(f'<rect x="{_f(x)}" y="{_f(yy - 10)}" width="12" height="12" rx="3" fill="{color}"/>')
        out.append(_text(x + 18, yy, name, 12, COLORS['text']))
        x += w
    return out, (row + 1) * 20


def _header(spec, width):
    """Title space plus legend for multi-series charts. Returns (elements, next_y)."""
    y = 52 if spec['title'] else 20
    out = []
    if len(spec['series']) > 1:
        items = [(_color(i), s['name']) for i, s in enumerate(spec['series'])]
        out, h = _legend(items, y + 6, width)
        y += h + 2
    return out, y


def _category_plan(labels, band, rotate_ok):
    """How to draw category labels on the x axis: (mode, step, labels, height)."""
    texts = [_clip(l, 24) for l in labels]
    widest = max((text_width(t, 11) for t in texts), default=0)
    if widest <= band - 6:
        return 'flat', 1, texts, 20
    if not rotate_ok:
        step = max(1, math.ceil((widest + 10) / max(band, 1e-6)))
        return 'flat', step, texts, 20
    texts = [_clip(l, 18) for l in labels]
    widest = max(text_width(t, 11) for t in texts)
    step = max(1, math.ceil(15 / max(band, 1e-6)))
    height = widest * math.sin(math.radians(40)) + 22
    return 'rotate', step, texts, min(height, 110)


def _frame_y(ticks, unit, x0, x1, y_of, out, zero=True):
    biggest = max(abs(t) for t in ticks)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    for t in ticks:
        y = y_of(t)
        stroke = COLORS['line'] if (t == 0 and zero and ticks[0] < 0 < ticks[-1]) else COLORS['grid']
        width = 1.4 if stroke == COLORS['line'] else 1
        out.append(f'<line x1="{_f(x0)}" y1="{_f(y)}" x2="{_f(x1)}" y2="{_f(y)}" stroke="{stroke}" stroke-width="{width}"/>')
        out.append(_text(x0 - 8, y + 4, fmt_tick(t, step, biggest, unit), 11, anchor='end'))


def _tick_width(ticks, unit):
    biggest = max(abs(t) for t in ticks)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    return max(text_width(fmt_tick(t, step, biggest, unit), 11) for t in ticks)


def _axis_titles(spec, left, right, top, bottom_y, width, out, x_mid=None):
    if spec['y_label']:
        cy = (top + bottom_y) / 2
        out.append(f'<text x="18" y="{_f(cy)}" font-size="12" fill="{COLORS["sub"]}" text-anchor="middle" '
                   f'transform="rotate(-90 18 {_f(cy)})" dy="4">{esc(_clip(spec["y_label"], 60))}</text>')
    if spec['x_label']:
        mid = x_mid if x_mid is not None else (left + width - right) / 2
        out.append(_text(mid, bottom_y, _clip(spec['x_label'], 60), 12, anchor='middle'))


def _value_range(values, include_zero, pad_labels):
    lo, hi = min(values), max(values)
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if pad_labels:
        span = (hi - lo) or abs(hi) or 1
        if hi > 0:
            hi += span * 0.08
        if lo < 0:
            lo -= span * 0.08
    return lo, hi


# ---------------------------------------------------------------- vertical bars, lines, areas

def _cartesian(spec):
    kind, unit, labels, series = spec['type'], spec['unit'], spec['labels'], spec['series']
    n, ns = len(labels), len(series)
    width, height = WIDTH, HEIGHT
    out, top = _header(spec, width)
    top += 10
    show = spec['show_values']
    is_bar = kind in ('bar', 'stacked_bar')

    if kind == 'stacked_bar':
        pos = [sum(max(0.0, s['values'][i]) for s in series) for i in range(n)]
        neg = [sum(min(0.0, s['values'][i]) for s in series) for i in range(n)]
        all_values = pos + neg
    else:
        all_values = [v for s in series for v in s['values']]
    auto_line_values = kind in ('line', 'area') and ns == 1 and n <= 16
    want_values = show is True or (show is None and (is_bar or auto_line_values))
    lo, hi = _value_range(all_values, include_zero=is_bar or kind == 'area', pad_labels=False)
    ticks = nice_ticks(lo, hi, 5, include_zero=is_bar or kind == 'area')

    left = 18 + (24 if spec['y_label'] else 0) + _tick_width(ticks, unit) + 10
    right = 24
    plot_w = width - left - right
    inset = 14 if kind == 'line' else 0
    band = plot_w / n if is_bar else ((plot_w - 2 * inset) / max(1, n - 1) if n > 1 else plot_w)
    mode, step, cat_texts, cat_h = _category_plan(labels, band, rotate_ok=is_bar)
    if mode == 'rotate':  # the first rotated label hangs to the left of its bar: make room
        overhang = text_width(cat_texts[0], 11) * math.cos(math.radians(40)) - band / 2 + 10
        if overhang > left:
            left = overhang
            plot_w = width - left - right
            band = plot_w / n
    bottom = cat_h + (26 if spec['x_label'] else 6) + 10
    plot_h = height - top - bottom
    if plot_h < 160:  # very tall legend or labels: grow the canvas
        height += 160 - plot_h
        plot_h = 160
    base_y = top + plot_h
    t0, t1 = ticks[0], ticks[-1]
    # pixel headroom for value labels above the top tick / below the bottom tick (instead of a wasted tick)
    head_px = foot_px = 0.0
    if want_values:
        if (t1 - hi) / (t1 - t0) * plot_h < 16:
            head_px = 16.0
        if lo < 0 and (lo - t0) / (t1 - t0) * plot_h < 16:
            foot_px = 16.0

    def y_of(v):
        return top + head_px + (t1 - v) / (t1 - t0) * (plot_h - head_px - foot_px)

    def x_center(i):
        if is_bar:
            return left + band * (i + 0.5)
        return left + (inset + band * i if n > 1 else plot_w / 2)

    _frame_y(ticks, unit, left, left + plot_w, y_of, out)
    out.append(f'<line x1="{_f(left)}" y1="{_f(top)}" x2="{_f(left)}" y2="{_f(base_y)}" stroke="{COLORS["line"]}"/>')
    zero_y = y_of(min(max(0.0, t0), t1))
    placer = _Placer()
    labels_out = []

    if kind == 'bar':
        group = band * (0.78 if ns > 1 else 0.62)
        bw = group / ns
        boxes = []
        for si, s in enumerate(series):
            color = _color(si)
            for i, v in enumerate(s['values']):
                x = x_center(i) - group / 2 + si * bw
                y0, y1 = sorted((y_of(v), zero_y))
                gap = min(2.0, bw * 0.12) if ns > 1 else 0
                out.append(f'<rect x="{_f(x + gap / 2)}" y="{_f(y0)}" width="{_f(max(0.8, bw - gap))}" '
                           f'height="{_f(max(0.0, y1 - y0))}" rx="{_f(min(3, bw / 4))}" fill="{color}"/>')
                boxes.append((x + bw / 2, v, bw))
        if want_values:
            texts = [(cx, v, fmt_value(v, unit), bw_) for cx, v, bw_ in boxes]
            fits = all(text_width(t, 10) <= bw_ + band * 0.2 * (ns == 1) + 4 for _, _, t, bw_ in texts)
            if fits or show is True:
                rotate = not fits
                for cx, v, t, _ in texts:
                    y = y_of(v)
                    tw = text_width(t, 10)
                    if rotate:
                        yy = y - 5 if v >= 0 else y + 5
                        anchor = 'start' if v >= 0 else 'end'
                        box = (cx - 6, yy - tw, cx + 6, yy) if v >= 0 else (cx - 6, yy, cx + 6, yy + tw)
                        if placer.place(*box):
                            labels_out.append(f'<text x="{_f(cx + 3.5)}" y="{_f(yy)}" font-size="10" fill="{COLORS["text"]}" '
                                              f'text-anchor="{anchor}" transform="rotate(-90 {_f(cx + 3.5)} {_f(yy)})">{esc(t)}</text>')
                    else:
                        yy = y - 5 if v >= 0 else y + 13
                        if placer.place(cx - tw / 2, yy - 10, cx + tw / 2, yy + 2):
                            labels_out.append(_text(cx, yy, t, 10, COLORS['text'], 'middle'))
    elif kind == 'stacked_bar':
        bw = band * 0.62
        pos_acc, neg_acc = [0.0] * n, [0.0] * n
        for si, s in enumerate(series):
            color = _color(si)
            for i, v in enumerate(s['values']):
                if v >= 0:
                    a, b = pos_acc[i], pos_acc[i] + v
                    pos_acc[i] = b
                else:
                    a, b = neg_acc[i], neg_acc[i] + v
                    neg_acc[i] = b
                y0, y1 = sorted((y_of(a), y_of(b)))
                x = x_center(i) - bw / 2
                out.append(f'<rect x="{_f(x)}" y="{_f(y0)}" width="{_f(bw)}" height="{_f(max(0.0, y1 - y0))}" '
                           f'fill="{color}" stroke="{COLORS["bg"]}" stroke-width="1"/>')
                t = fmt_value(v, unit)
                if want_values and v and y1 - y0 >= 15 and text_width(t, 10) <= bw - 4:
                    labels_out.append(_text(x + bw / 2, (y0 + y1) / 2 + 3.5, t, 10, COLORS['accent_text'], 'middle', 600))
        if want_values:
            for i in range(n):
                total = sum(s['values'][i] for s in series)
                t = fmt_value(total, unit)
                tw = text_width(t, 10)
                cx = x_center(i)
                yy = (y_of(pos_acc[i]) - 5) if total >= 0 else (y_of(neg_acc[i]) + 13)
                if tw <= band + 2 and placer.place(cx - tw / 2, yy - 10, cx + tw / 2, yy + 2):
                    labels_out.append(_text(cx, yy, t, 10, COLORS['text'], 'middle', 600))
    else:  # line / area
        markers = n <= 40
        for si, s in enumerate(series):
            color = _color(si)
            pts = [(x_center(i), y_of(v)) for i, v in enumerate(s['values'])]
            line = ' '.join(f'{_f(x)},{_f(y)}' for x, y in pts)
            if kind == 'area':
                poly = f'{_f(pts[0][0])},{_f(zero_y)} {line} {_f(pts[-1][0])},{_f(zero_y)}'
                out.append(f'<polygon points="{poly}" fill="{color}" fill-opacity="{0.28 if ns == 1 else 0.16}"/>')
            if len(pts) == 1:
                out.append(f'<circle cx="{_f(pts[0][0])}" cy="{_f(pts[0][1])}" r="4.5" fill="{color}"/>')
            else:
                out.append(f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.4" '
                           f'stroke-linejoin="round" stroke-linecap="round"/>')
            if markers and len(pts) > 1:
                for x, y in pts:
                    out.append(f'<circle cx="{_f(x)}" cy="{_f(y)}" r="3.4" fill="{color}" stroke="{COLORS["bg"]}" stroke-width="1.5"/>')
        if want_values:
            for x, y in [(x_center(i), y_of(v)) for s in series for i, v in enumerate(s['values'])]:
                placer.place(x - 4, y - 4, x + 4, y + 4, pad=0)  # keep labels off the markers
            for si, s in enumerate(series):
                for i, v in enumerate(s['values']):
                    x, y = x_center(i), y_of(v)
                    t = fmt_value(v, unit)
                    tw = text_width(t, 10)
                    for yy in (y - 8, y + 16):
                        if top <= yy - 10 and yy <= base_y and placer.place(x - tw / 2, yy - 10, x + tw / 2, yy + 2):
                            labels_out.append(_text(x, yy, t, 10, _color(si) if ns > 1 else COLORS['text'], 'middle'))
                            break

    out.append(f'<line x1="{_f(left)}" y1="{_f(zero_y)}" x2="{_f(left + plot_w)}" y2="{_f(zero_y)}" stroke="{COLORS["line"]}" stroke-width="1.4"/>')
    out.extend(labels_out)
    # category labels
    for i, t in enumerate(cat_texts):
        if i % step:
            continue
        x = x_center(i)
        if mode == 'flat':
            anchor = 'middle'
            if not is_bar and n > 1 and i == 0:
                anchor = 'start' if text_width(t, 11) / 2 > left - 4 else 'middle'
            if not is_bar and n > 1 and i == n - 1 and text_width(t, 11) / 2 > right:
                anchor = 'end'
            out.append(_text(x, base_y + 18, t, 11, anchor=anchor))
        else:
            y = base_y + 14
            out.append(f'<text x="{_f(x + 3)}" y="{_f(y)}" font-size="11" fill="{COLORS["sub"]}" text-anchor="end" '
                       f'transform="rotate(-40 {_f(x + 3)} {_f(y)})">{esc(t)}</text>')
    _axis_titles(spec, left, right, top, height - 12, width, out, x_mid=left + plot_w / 2)
    return width, height, out


# ---------------------------------------------------------------- horizontal bars

def _horizontal(spec):
    unit, labels, series = spec['unit'], spec['labels'], spec['series']
    n, ns = len(labels), len(series)
    width = WIDTH
    out, top = _header(spec, width)
    top += 8
    show = spec['show_values']
    want_values = show is not False
    all_values = [v for s in series for v in s['values']]
    lo, hi = _value_range(all_values, True, False)
    ticks = nice_ticks(lo, hi, 5, include_zero=True)
    pos_label = max([text_width(fmt_value(v, unit), 10) for v in all_values if v >= 0] or [0])
    neg_label = max([text_width(fmt_value(v, unit), 10) for v in all_values if v < 0] or [0])
    band = max(22.0, ns * 11.0 + 10)
    if n * band > 1500:
        band = max(14.0, 1500 / n)
    texts = [_clip(l, 26) for l in labels]
    label_w = max(text_width(t, 11) for t in texts)
    left = 18 + (24 if spec['y_label'] else 0) + label_w + 10
    right = 28
    bottom = 28 + (26 if spec['x_label'] else 4)
    plot_h = n * band
    height = max(HEIGHT, int(top + plot_h + bottom + 6))
    if height > HEIGHT:
        plot_h = n * band
    else:
        plot_h = height - top - bottom
        band = plot_h / n
    plot_w = width - left - right
    t0, t1 = ticks[0], ticks[-1]
    # pixel room for value labels beyond the outermost ticks
    pad_r = pad_l = 0.0
    if want_values:
        if (t1 - hi) / (t1 - t0) * plot_w < pos_label + 8:
            pad_r = pos_label + 8
        if lo < 0 and (lo - t0) / (t1 - t0) * plot_w < neg_label + 8:
            pad_l = neg_label + 8

    def x_of(v):
        return left + pad_l + (v - t0) / (t1 - t0) * (plot_w - pad_l - pad_r)

    biggest = max(abs(t) for t in ticks)
    tstep = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    base_y = top + plot_h
    for t in ticks:
        x = x_of(t)
        out.append(f'<line x1="{_f(x)}" y1="{_f(top)}" x2="{_f(x)}" y2="{_f(base_y)}" stroke="{COLORS["grid"]}"/>')
        out.append(_text(x, base_y + 18, fmt_tick(t, tstep, biggest, unit), 11, anchor='middle'))
    zero_x = x_of(min(max(0.0, t0), t1))
    group = min(band * (0.8 if ns > 1 else 0.64), ns * 26.0)
    bh = group / ns
    labels_out = []
    placer = _Placer()
    fits = bh >= 9
    for si, s in enumerate(series):
        color = _color(si)
        for i, v in enumerate(s['values']):
            y = top + band * i + (band - group) / 2 + si * bh
            x0, x1 = sorted((x_of(v), zero_x))
            gap = 1.5 if ns > 1 else 0
            out.append(f'<rect x="{_f(x0)}" y="{_f(y + gap / 2)}" width="{_f(max(0.0, x1 - x0))}" '
                       f'height="{_f(max(0.8, bh - gap))}" rx="{_f(min(3, bh / 4))}" fill="{color}"/>')
            if want_values and (fits or show is True):
                t = fmt_value(v, unit)
                tw = text_width(t, 10)
                cy = y + bh / 2 + 3.5
                tx = x_of(v) + (5 if v >= 0 else -5)
                box = (tx, cy - 10, tx + tw, cy + 2) if v >= 0 else (tx - tw, cy - 10, tx, cy + 2)
                if placer.place(*box, pad=0):
                    labels_out.append(_text(tx, cy, t, 10, COLORS['text'], 'start' if v >= 0 else 'end'))
    out.append(f'<line x1="{_f(zero_x)}" y1="{_f(top)}" x2="{_f(zero_x)}" y2="{_f(base_y)}" stroke="{COLORS["line"]}" stroke-width="1.4"/>')
    out.extend(labels_out)
    for i, t in enumerate(texts):
        cy = top + band * (i + 0.5) + 4
        out.append(_text(left - 8, cy, t, 11, anchor='end'))
    _axis_titles(spec, left, right, top, height - 10, width, out, x_mid=left + plot_w / 2)
    return width, height, out


# ---------------------------------------------------------------- scatter

def _scatter(spec):
    unit, series = spec['unit'], spec['series']
    ns = len(series)
    width, height = WIDTH, HEIGHT
    out, top = _header(spec, width)
    top += 10
    xs = [p[0] for s in series for p in s['values']]
    ys = [p[1] for s in series for p in s['values']]

    def padded(vals):
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or abs(hi) or 1
        return lo - span * 0.05, hi + span * 0.05

    xt = nice_ticks(*padded(xs), 6)
    yt = nice_ticks(*padded(ys), 5)
    left = 18 + (24 if spec['y_label'] else 0) + _tick_width(yt, unit) + 10
    right = 24
    bottom = 26 + (26 if spec['x_label'] else 6)
    plot_w, plot_h = width - left - right, height - top - bottom
    if plot_h < 160:
        height += 160 - plot_h
        plot_h = 160
    base_y = top + plot_h

    def x_of(v):
        return left + (v - xt[0]) / (xt[-1] - xt[0]) * plot_w

    def y_of(v):
        return top + (yt[-1] - v) / (yt[-1] - yt[0]) * plot_h

    _frame_y(yt, unit, left, left + plot_w, y_of, out)
    xbig = max(abs(t) for t in xt)
    xstep = xt[1] - xt[0] if len(xt) > 1 else 1
    for t in xt:
        x = x_of(t)
        stroke = COLORS['line'] if (t == 0 and xt[0] < 0 < xt[-1]) else COLORS['grid']
        out.append(f'<line x1="{_f(x)}" y1="{_f(top)}" x2="{_f(x)}" y2="{_f(base_y)}" stroke="{stroke}"/>')
        out.append(_text(x, base_y + 18, fmt_tick(t, xstep, xbig), 11, anchor='middle'))
    out.append(f'<rect x="{_f(left)}" y="{_f(top)}" width="{_f(plot_w)}" height="{_f(plot_h)}" fill="none" stroke="{COLORS["line"]}"/>')
    r = 4.5 if len(xs) <= 80 else 3.4
    for si, s in enumerate(series):
        color = _color(si)
        for x, y in s['values']:
            out.append(f'<circle cx="{_f(x_of(x))}" cy="{_f(y_of(y))}" r="{r}" fill="{color}" fill-opacity="0.85" '
                       f'stroke="{COLORS["bg"]}" stroke-width="1"/>')
    labels = spec['labels']
    if ns == 1 and labels and len(labels) == len(series[0]['values']) and spec['show_values'] is not False:
        placer = _Placer()
        for x, y in series[0]['values']:
            placer.place(x_of(x) - r, y_of(y) - r, x_of(x) + r, y_of(y) + r, pad=0)
        for (x, y), label in zip(series[0]['values'], labels):
            t = _clip(label, 18)
            tw = text_width(t, 10)
            px, py = x_of(x), y_of(y)
            for dx, dy, anchor in ((7, 4, 'start'), (-7, 4, 'end'), (0, -8, 'middle'), (0, 16, 'middle')):
                x0 = px + dx if anchor == 'start' else px + dx - tw if anchor == 'end' else px - tw / 2
                if x0 >= left and x0 + tw <= left + plot_w and top + 10 <= py + dy <= base_y and \
                        placer.place(x0, py + dy - 10, x0 + tw, py + dy + 2):
                    out.append(_text(px + dx, py + dy, t, 10, COLORS['text'], anchor))
                    break
    _axis_titles(spec, left, right, top, height - 12, width, out, x_mid=left + plot_w / 2)
    return width, height, out


# ---------------------------------------------------------------- pie / donut

def _pie(spec):
    labels, values, unit = spec['labels'], spec['series'][0]['values'], spec['unit']
    n = len(values)
    total = sum(values)
    width = WIDTH
    top = 52 if spec['title'] else 20
    cols = 1 if n <= 16 else 2
    rows = math.ceil(n / cols)
    legend_h = rows * 22
    height = max(HEIGHT, int(top + legend_h + 30))
    r = min(150.0, (min(height, HEIGHT) - top - 44) / 2)
    cx, cy = 60 + r, top + 12 + r + max(0.0, (HEIGHT - top - 2 * r - 24) / 2)
    inner = r * 0.58 if spec['type'] == 'donut' else 0
    out, labels_out = [], []
    placer = _Placer()
    angle = -math.pi / 2
    show = spec['show_values'] is not False

    def pt(a, rad):
        return cx + rad * math.cos(a), cy + rad * math.sin(a)

    for i, v in enumerate(values):
        if v <= 0:
            continue
        frac = v / total
        sweep = frac * 2 * math.pi
        a0, a1 = angle, angle + sweep
        color = _color(i)
        if frac >= 0.9999:
            out.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="{color}"/>')
            if inner:
                out.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(inner)}" fill="{COLORS["bg"]}"/>')
        else:
            large = 1 if sweep > math.pi else 0
            x0, y0 = pt(a0, r)
            x1, y1 = pt(a1, r)
            if inner:
                ix1, iy1 = pt(a1, inner)
                ix0, iy0 = pt(a0, inner)
                d = (f'M{_f(x0)},{_f(y0)} A{_f(r)},{_f(r)} 0 {large} 1 {_f(x1)},{_f(y1)} '
                     f'L{_f(ix1)},{_f(iy1)} A{_f(inner)},{_f(inner)} 0 {large} 0 {_f(ix0)},{_f(iy0)} Z')
            else:
                d = f'M{_f(cx)},{_f(cy)} L{_f(x0)},{_f(y0)} A{_f(r)},{_f(r)} 0 {large} 1 {_f(x1)},{_f(y1)} Z'
            out.append(f'<path d="{d}" fill="{color}" stroke="{COLORS["bg"]}" stroke-width="2" stroke-linejoin="round"/>')
        if show:
            pct = frac * 100
            t = f'{pct:.0f}%' if pct >= 10 else f'{pct:.1f}%'
            mid = (a0 + a1) / 2
            tw = text_width(t, 12)
            if frac >= 0.05 or (inner and frac >= 0.04):
                lx, ly = pt(mid, (r + inner) / 2 if inner else r * 0.66) if frac < 0.9999 else (cx, cy + (0 if not inner else (r + inner) / 2))
                placer.place(lx - tw / 2, ly - 8, lx + tw / 2, ly + 6)
                labels_out.append(_text(lx, ly + 4, t, 12, COLORS['accent_text'], 'middle', 700))
            elif frac >= 0.004:
                ex, ey = pt(mid, r + 2)
                lx, ly = pt(mid, r + 18)
                anchor = 'start' if math.cos(mid) >= 0 else 'end'
                bx = lx if anchor == 'start' else lx - tw
                if placer.place(bx, ly - 6, bx + tw, ly + 7):
                    labels_out.append(f'<line x1="{_f(ex)}" y1="{_f(ey)}" x2="{_f(lx)}" y2="{_f(ly)}" stroke="{color}" stroke-width="1.2"/>')
                    labels_out.append(_text(lx + (3 if anchor == 'start' else -3), ly + 4, t, 11, COLORS['text'], anchor))
        angle = a1
    out.extend(labels_out)
    if inner:
        out.append(_text(cx, cy + 2, fmt_value(total, unit), 20, COLORS['text'], 'middle', 700))
        out.append(_text(cx, cy + 22, 'Total', 12, COLORS['sub'], 'middle'))
    # legend
    lx0 = cx + r + 56
    col_w = (width - lx0 - 16) / cols if cols > 1 else min(270.0, width - lx0 - 16)
    name_chars = 26 if cols == 1 else 14
    ly0 = top + 14 + max(0, (height - top - 20 - legend_h) / 2)
    for i, (label, v) in enumerate(zip(labels, values)):
        col, row = divmod(i, rows)
        x, y = lx0 + col * col_w, ly0 + row * 22
        pct = v / total * 100
        out.append(f'<rect x="{_f(x)}" y="{_f(y - 10)}" width="12" height="12" rx="3" fill="{_color(i)}"/>')
        out.append(_text(x + 18, y, _clip(label, name_chars), 12, COLORS['text']))
        detail = f'{fmt_value(v, unit)} · {pct:.1f}%' if cols == 1 else f'{pct:.1f}%'
        out.append(_text(x + col_w - 10, y, detail, 11, COLORS['sub'], 'end'))
    return width, height, out


# ---------------------------------------------------------------- entry point

def _summary(spec):
    kind = spec['type'].replace('_', ' ')
    head = f'{kind.capitalize()} chart' + (f' "{spec["title"]}"' if spec['title'] else '')
    unit = spec['unit']
    parts = []
    if spec['type'] == 'scatter':
        for s in spec['series']:
            xs = [p[0] for p in s['values']]
            ys = [p[1] for p in s['values']]
            parts.append(f'{s["name"]}: {len(xs)} point{"s" if len(xs) != 1 else ""}, x {fmt_value(min(xs))} to {fmt_value(max(xs))}, '
                         f'y {fmt_value(min(ys), unit)} to {fmt_value(max(ys), unit)}')
    else:
        labels = spec['labels']
        for s in spec['series']:
            vals = s['values']
            lo, hi = min(vals), max(vals)
            parts.append(f'{s["name"]}: {len(vals)} value{"s" if len(vals) != 1 else ""}, min {fmt_value(lo, unit)} ({labels[vals.index(lo)]}), '
                         f'max {fmt_value(hi, unit)} ({labels[vals.index(hi)]}), total {fmt_value(sum(vals), unit)}')
        if spec['type'] in ('pie', 'donut'):
            vals = spec['series'][0]['values']
            total = sum(vals)
            top = sorted(range(len(vals)), key=lambda i: -vals[i])[:5]
            parts.append('largest slices: ' + ', '.join(f'{labels[i]} {vals[i] / total * 100:.1f}%' for i in top))
    return f'{head}. ' + '; '.join(parts) + '.'


def render(spec):
    kind = spec['type']
    if kind in ('pie', 'donut'):
        width, height, body = _pie(spec)
    elif kind == 'horizontal_bar':
        width, height, body = _horizontal(spec)
    elif kind == 'scatter':
        width, height, body = _scatter(spec)
    else:
        width, height, body = _cartesian(spec)
    return svgkit.svg_document(width, height, body, _clip(spec['title'], 70))


def call(tool, arguments):
    if tool != 'draw_chart':
        return _error(f'Unknown chart tool "{tool}". Use draw_chart.')
    try:
        spec = validate(arguments)
    except InputError as error:
        return _error(str(error))
    svg = render(spec)
    return svgkit.image_result(_summary(spec), svg)
