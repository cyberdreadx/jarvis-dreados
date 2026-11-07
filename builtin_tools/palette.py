"""Colour palettes from one colour, with exact HEX/RGB/HSL values and WCAG contrast checks.

Colour maths is done in HSL; contrast ratios follow WCAG 2.1 (relative luminance of sRGB).
"""
import colorsys
import math
import re

from .svgkit import COLORS, MONO, esc, image_result, svg_document

SCHEMES = ('analogous', 'complementary', 'triadic', 'tetradic', 'split-complementary', 'monochromatic', 'shades')

NAMES = {
    'black': '000000', 'white': 'ffffff', 'gray': '808080', 'grey': '808080', 'silver': 'c0c0c0',
    'red': 'ff0000', 'maroon': '800000', 'crimson': 'dc143c', 'coral': 'ff7f50', 'tomato': 'ff6347',
    'orange': 'ffa500', 'gold': 'ffd700', 'yellow': 'ffff00', 'olive': '808000', 'lime': '00ff00',
    'green': '008000', 'teal': '008080', 'cyan': '00ffff', 'aqua': '00ffff', 'turquoise': '40e0d0',
    'blue': '0000ff', 'navy': '000080', 'skyblue': '87ceeb', 'royalblue': '4169e1', 'indigo': '4b0082',
    'purple': '800080', 'violet': 'ee82ee', 'magenta': 'ff00ff', 'fuchsia': 'ff00ff', 'pink': 'ffc0cb',
    'hotpink': 'ff69b4', 'brown': 'a52a2a', 'chocolate': 'd2691e', 'beige': 'f5f5dc', 'salmon': 'fa8072',
    'khaki': 'f0e68c', 'lavender': 'e6e6fa',
}

TOOLS = [{
    'name': 'color_palette',
    'description': ('Make a colour palette from one colour and show it as swatches with exact HEX, RGB, HSL and '
                    'WCAG contrast (AA/AAA vs white and black text). Use when asked for colour schemes, matching '
                    'colours or whether text is readable on a colour. Pass color as "#2ff3d0", "2ff3d0", '
                    '"rgb(47,243,208)" or a name like "teal"; scheme (default analogous); count 3-8.'),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'color': {'type': 'string', 'minLength': 1, 'maxLength': 60,
                      'description': 'Base colour: hex (#2ff3d0, #abc), rgb(r, g, b) or a CSS name like coral.'},
            'scheme': {'type': 'string', 'enum': list(SCHEMES), 'default': 'analogous',
                       'description': 'Palette type. shades = tints and shades of the base colour.'},
            'count': {'type': 'integer', 'minimum': 3, 'maximum': 8, 'default': 5,
                      'description': 'Number of colours (3-8).'},
            'title': {'type': 'string', 'maxLength': 80, 'description': 'Optional heading for the image.'},
        },
        'required': ['color'],
        'additionalProperties': False,
    },
}]


class PaletteError(Exception):
    pass


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': str(message)}]}


# ---------------------------------------------------------------- parsing

def _channel(text):
    text = text.strip()
    if text.endswith('%'):
        value = float(text[:-1]) * 255 / 100
    else:
        value = float(text)
    if not 0 <= value <= 255:
        raise PaletteError('rgb() values must be 0-255 (or 0%-100%).')
    return int(round(value))


def parse_color(text):
    """Return an (r, g, b) tuple of ints 0-255."""
    if not isinstance(text, str) or not text.strip():
        raise PaletteError('Pass a colour, e.g. "#2ff3d0", "rgb(47, 243, 208)" or "teal".')
    s = text.strip().lower()
    m = re.fullmatch(r'#?([0-9a-f]{3}|[0-9a-f]{6})', s)
    if m:
        digits = m.group(1)
        if len(digits) == 3:
            digits = ''.join(ch * 2 for ch in digits)
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    num = r'\s*(\d{1,3}(?:\.\d+)?%?)\s*'
    m = re.fullmatch(rf'rgba?\({num}[,\s]{num}[,\s]{num}(?:[,/]\s*[\d.]+%?\s*)?\)', s)
    if m:
        return tuple(_channel(g) for g in m.groups())
    m = re.fullmatch(r'hsla?\(\s*(\d{1,3}(?:\.\d+)?)(?:deg)?\s*[,\s]\s*(\d{1,3}(?:\.\d+)?)%\s*[,\s]\s*'
                     r'(\d{1,3}(?:\.\d+)?)%\s*(?:[,/]\s*[\d.]+%?\s*)?\)', s)
    if m:
        h, sat, light = float(m.group(1)), float(m.group(2)), float(m.group(3))
        if sat > 100 or light > 100:
            raise PaletteError('hsl() saturation and lightness must be 0%-100%.')
        return _hsl_to_rgb(h, sat / 100, light / 100)
    key = re.sub(r'[\s_-]+', '', s)
    if key in NAMES:
        return parse_color(NAMES[key])
    raise PaletteError(f'"{text[:60]}" is not a colour I know. Use hex like "#2ff3d0" or "#abc", '
                       f'"rgb(47, 243, 208)", or a name: {", ".join(sorted(NAMES))}.')


# ---------------------------------------------------------------- colour maths

def _hsl_to_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, min(max(l, 0), 1), min(max(s, 0), 1))
    return tuple(int(round(c * 255)) for c in (r, g, b))


def rgb_to_hsl(rgb):
    """(hue degrees 0-360, saturation 0-1, lightness 0-1)."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return h * 360, s, l


def hex_of(rgb):
    return '#' + ''.join(f'{c:02X}' for c in rgb)


def luminance(rgb):
    def linear(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _lighten(l, amount):
    return l + (1 - l) * amount


def _darken(l, amount):
    return l * (1 - amount)


KEY_SCHEMES = {
    'complementary': ([0, 180], ['Base', 'Complement']),
    'triadic': ([0, 120, 240], ['Base', 'Triad +120°', 'Triad +240°']),
    'tetradic': ([0, 90, 180, 270], ['Base', 'Square +90°', 'Complement', 'Square +270°']),
    'split-complementary': ([0, 150, 210], ['Base', 'Split +150°', 'Split +210°']),
}
VARIANTS = [('tint', 0.45), ('shade', 0.4), ('tint', 0.72), ('shade', 0.65)]


def generate(rgb, scheme='analogous', count=5):
    """List of (rgb, role) for the palette; the base colour is always included exactly."""
    h, s, l = rgb_to_hsl(rgb)
    out = []
    if scheme in KEY_SCHEMES:
        offsets, names = KEY_SCHEMES[scheme]
        groups = [[(l, rgb if i == 0 else _hsl_to_rgb(h + off, s, l), names[i])]
                  for i, off in enumerate(offsets)][:count]
        k = len(groups)
        for j in range(count - k):
            key, (kind, amount) = j % k, VARIANTS[(j // k) % len(VARIANTS)]
            vl = _lighten(l, amount) if kind == 'tint' else _darken(l, amount)
            groups[key].append((vl, _hsl_to_rgb(h + offsets[key], s, vl), f'{names[key]} {kind} L{round(vl * 100)}%'))
        for group in groups:
            out.extend((c, role) for _, c, role in sorted(group, key=lambda item: -item[0]))
    elif scheme == 'analogous':
        step = 30 if count <= 5 else round(120 / (count - 1))
        for i in range(count):
            off = (i - (count - 1) // 2) * step
            out.append((rgb if off == 0 else _hsl_to_rgb(h + off, s, l), 'Base' if off == 0 else f'{off:+d}°'))
    elif scheme == 'monochromatic':
        levels = [0.9 - i * (0.9 - 0.15) / (count - 1) for i in range(count)]
        nearest = min(range(count), key=lambda i: abs(levels[i] - l))
        for i, level in enumerate(levels):
            if i == nearest:
                out.append((rgb, 'Base'))
            else:
                out.append((_hsl_to_rgb(h, s, level), f'L {round(level * 100)}%'))
    elif scheme == 'shades':
        n_light = (count - 1) // 2
        n_dark = count - 1 - n_light
        for k in range(n_light, 0, -1):
            t = 0.8 * k / n_light
            out.append((tuple(int(round(c + (255 - c) * t)) for c in rgb), f'Tint {round(t * 100)}%'))
        out.append((rgb, 'Base'))
        for k in range(1, n_dark + 1):
            t = 0.75 * k / n_dark
            out.append((tuple(int(round(c * (1 - t))) for c in rgb), f'Shade {round(t * 100)}%'))
    else:
        raise PaletteError(f'Unknown scheme. Use one of: {", ".join(SCHEMES)}.')
    return out


def describe(rgb):
    h, s, l = rgb_to_hsl(rgb)
    white, black = contrast(rgb, (255, 255, 255)), contrast(rgb, (0, 0, 0))
    return {
        'hex': hex_of(rgb), 'rgb': rgb,
        'hsl': (int(round(h)) % 360, int(round(s * 100)), int(round(l * 100))),
        'white': white, 'black': black,
        'best': 'white' if white >= black else 'black',
    }


def _passes(ratio):
    return ratio >= 4.5, ratio >= 7


def _ratio_text(ratio):
    return f'{math.floor(ratio * 100) / 100:.2f}:1'   # WCAG: never round a ratio up


# ---------------------------------------------------------------- drawing

CARD_W, CARD_H, GAP, MARGIN, TOP = 240, 318, 18, 24, 74
PASS_FILL, PASS_TEXT, FAIL = '#7cff6b', '#06121a', COLORS['warn']


def _badge(x, y, label, ok):
    width = 30 + 9 * len(label)
    mark = '✓' if ok else '✗'
    if ok:
        rect = f'<rect x="{x}" y="{y}" width="{width}" height="22" rx="11" fill="{PASS_FILL}"/>'
        color = PASS_TEXT
    else:
        rect = (f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{width - 1}" height="21" rx="10.5" fill="none" '
                f'stroke="{FAIL}" stroke-width="1.2"/>')
        color = FAIL
    return rect + (f'<text x="{x + width / 2}" y="{y + 15.5}" text-anchor="middle" font-size="12" '
                   f'font-weight="700" fill="{color}">{label} {mark}</text>'), width


def _contrast_row(x, y, info, against):
    ratio = info[against]
    text_hex = '#FFFFFF' if against == 'white' else '#000000'
    parts = [f'<rect x="{x}" y="{y}" width="40" height="24" rx="6" fill="{info["hex"]}" '
             f'stroke="{COLORS["grid"]}"/>',
             f'<text x="{x + 20}" y="{y + 17}" text-anchor="middle" font-size="14" font-weight="700" '
             f'fill="{text_hex}">Aa</text>',
             f'<text x="{x + 50}" y="{y + 17}" font-size="14" font-family="{MONO}" '
             f'fill="{COLORS["accent"] if info["best"] == against else COLORS["text"]}" '
             f'font-weight="{700 if info["best"] == against else 400}">'
             f'{_ratio_text(ratio)}</text>']
    aa, aaa = _passes(ratio)
    bx = x + 122
    for label, ok in (('AA', aa), ('AAA', aaa)):
        svg, width = _badge(bx, y + 1, label, ok)
        parts.append(svg)
        bx += width + 6
    return ''.join(parts)


def _card(x, y, info, role, is_base):
    fg = '#FFFFFF' if info['best'] == 'white' else '#000000'
    r, g, b = info['rgb']
    h, s, l = info['hsl']
    sx, sw = x + 10, CARD_W - 20
    parts = [
        f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="18" fill="{COLORS["panel"]}" '
        f'stroke="{COLORS["accent"] if is_base else COLORS["grid"]}" stroke-width="{2 if is_base else 1}"/>',
        f'<rect x="{sx}" y="{y + 10}" width="{sw}" height="150" rx="14" fill="{info["hex"]}" '
        f'stroke="#ffffff" stroke-opacity="0.12"/>',
        f'<text x="{sx + 14}" y="{y + 34}" font-size="13" font-weight="600" fill="{fg}" fill-opacity="0.85">'
        f'{esc(role)}</text>',
        f'<text x="{sx + sw / 2}" y="{y + 98}" text-anchor="middle" font-size="28" font-weight="700" '
        f'font-family="{MONO}" fill="{fg}">{esc(info["hex"])}</text>',
    ]
    ty = y + 160
    for i, (label, value) in enumerate((('RGB', f'{r}, {g}, {b}'), ('HSL', f'{h}°, {s}%, {l}%'))):
        parts.append(f'<text x="{x + 16}" y="{ty + 28 + i * 22}" font-size="14" fill="{COLORS["sub"]}">{label}'
                     f'<tspan x="{x + 56}" font-family="{MONO}" fill="{COLORS["text"]}">{esc(value)}</tspan></text>')
    parts.append(f'<text x="{x + 16}" y="{ty + 84}" font-size="11" letter-spacing="1" fill="{COLORS["sub"]}">'
                 'TEXT ON THIS COLOUR</text>')
    parts.append(_contrast_row(x + 16, ty + 92, info, 'white'))
    parts.append(_contrast_row(x + 16, ty + 120, info, 'black'))
    return ''.join(parts)


def render(entries, title, subtitle):
    count = len(entries)
    cols = count if count <= 5 else math.ceil(count / 2)
    rows = math.ceil(count / cols)
    width = MARGIN * 2 + cols * CARD_W + (cols - 1) * GAP
    height = TOP + rows * CARD_H + (rows - 1) * GAP + 46
    body = [f'<text x="18" y="56" font-size="14" fill="{COLORS["sub"]}">{esc(subtitle)}</text>']
    for i, (info, role) in enumerate(entries):
        row, col = divmod(i, cols)
        body.append(_card(MARGIN + col * (CARD_W + GAP), TOP + row * (CARD_H + GAP), info, role, role == 'Base'))
    body.append(f'<text x="18" y="{height - 18}" font-size="12" fill="{COLORS["sub"]}">WCAG 2.1 contrast for '
                'normal text: AA needs 4.5:1, AAA needs 7:1. "Aa" shows white and black text on each colour.</text>')
    return svg_document(width, height, body, title)


# ---------------------------------------------------------------- entry point

def _count(value):
    if value is None:
        return 5
    if isinstance(value, bool):
        raise PaletteError('count must be a whole number from 3 to 8.')
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or not 3 <= value <= 8:
        raise PaletteError('count must be a whole number from 3 to 8.')
    return value


def palette(color, scheme=None, count=None, title=None):
    rgb = parse_color(color)
    scheme = (scheme or 'analogous')
    if not isinstance(scheme, str) or scheme.strip().lower().replace(' ', '-').replace('_', '-') not in SCHEMES:
        raise PaletteError(f'Unknown scheme. Use one of: {", ".join(SCHEMES)}.')
    scheme = scheme.strip().lower().replace(' ', '-').replace('_', '-')
    count = _count(count)
    if title is not None and not isinstance(title, str):
        raise PaletteError('title must be text.')
    title = (title or '').strip()[:80]
    entries = [(describe(c), role) for c, role in generate(rgb, scheme, count)]
    base_hex = hex_of(rgb)
    name = scheme.replace('-', ' ').capitalize()
    heading = title or f'{name} palette'
    subtitle = f'{count} colours from {base_hex} · {scheme}'
    lines = [f'{name} palette from {base_hex} ({count} colours):']
    for i, (info, role) in enumerate(entries, 1):
        r, g, b = info['rgb']
        h, s, l = info['hsl']
        checks = []
        for against in ('white', 'black'):
            aa, aaa = _passes(info[against])
            level = 'AAA' if aaa else 'AA' if aa else 'fails AA'
            checks.append(f'{against} text {_ratio_text(info[against])} ({level})')
        lines.append(f'{i}. {info["hex"]} [{role}] rgb({r}, {g}, {b}) hsl({h}, {s}%, {l}%); '
                     f'{", ".join(checks)}; best text: {info["best"]}')
    if rgb_to_hsl(rgb)[1] == 0 and scheme in KEY_SCHEMES or rgb_to_hsl(rgb)[1] == 0 and scheme == 'analogous':
        lines.append('Note: the base colour is a grey, so hue-based schemes repeat it; try monochromatic or shades.')
    return image_result('\n'.join(lines), render(entries, heading, subtitle))


def call(tool, arguments):
    if tool != 'color_palette':
        return _error(f'Unknown tool "{tool}".')
    if not isinstance(arguments, dict):
        return _error('Pass an object like {"color": "#2ff3d0", "scheme": "analogous"}.')
    extra = set(arguments) - {'color', 'scheme', 'count', 'title'}
    if extra:
        return _error(f'Unexpected argument(s): {", ".join(sorted(map(str, extra)))}. '
                      'Allowed: color, scheme, count, title.')
    color = arguments.get('color')
    if isinstance(color, str) and len(color) > 60:
        return _error('The colour text is too long (max 60 characters).')
    title = arguments.get('title')
    if isinstance(title, str) and len(title) > 80:
        title = title[:80]
    try:
        return palette(color, arguments.get('scheme'), arguments.get('count'), title)
    except PaletteError as error:
        return _error(error)
    except (ValueError, TypeError):
        return _error('I could not make that palette. Try {"color": "#2ff3d0", "scheme": "triadic", "count": 5}.')
