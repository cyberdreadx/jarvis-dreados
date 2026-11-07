"""Scales, modes and arpeggios on a guitar fretboard or piano keyboard, with correct note spelling.

Every scale is defined by its interval names (R, 2, b3, ...). Each interval names a scale degree,
so notes are spelled with the right letter (F major has Bb, not A#; E harmonic minor has D#).
"""
import re

from chord_diagrams import NOTE, TUNING
from . import svgkit

C = svgkit.COLORS
ROOT_COLOR = '#ff9a3c'
NOTE_COLOR = C['accent']

# scale id -> (display name, interval names in order)
SCALES = {
    'major': ('major', 'R 2 3 4 5 6 7'),
    'natural_minor': ('natural minor', 'R 2 b3 4 5 b6 b7'),
    'harmonic_minor': ('harmonic minor', 'R 2 b3 4 5 b6 7'),
    'melodic_minor': ('melodic minor', 'R 2 b3 4 5 6 7'),
    'dorian': ('dorian', 'R 2 b3 4 5 6 b7'),
    'phrygian': ('phrygian', 'R b2 b3 4 5 b6 b7'),
    'lydian': ('lydian', 'R 2 3 #4 5 6 7'),
    'mixolydian': ('mixolydian', 'R 2 3 4 5 6 b7'),
    'locrian': ('locrian', 'R b2 b3 4 b5 b6 b7'),
    'major_pentatonic': ('major pentatonic', 'R 2 3 5 6'),
    'minor_pentatonic': ('minor pentatonic', 'R b3 4 5 b7'),
    'blues': ('blues', 'R b3 4 b5 5 b7'),
    'whole_tone': ('whole tone', 'R 2 3 #4 #5 b7'),
    'chromatic': ('chromatic', None),
    'major_arpeggio': ('major arpeggio', 'R 3 5'),
    'minor_arpeggio': ('minor arpeggio', 'R b3 5'),
    'dominant7_arpeggio': ('dominant 7 arpeggio', 'R 3 5 b7'),
    'maj7_arpeggio': ('maj7 arpeggio', 'R 3 5 7'),
    'm7_arpeggio': ('m7 arpeggio', 'R b3 5 b7'),
}
DEGREE_SEMITONES = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
LETTERS = 'CDEFGAB'
CHROMATIC_SHARP = 'R b2 2 b3 3 4 b5 5 b6 6 b7 7'.split()
ROOT_RE = re.compile(r'^\s*([A-Ga-g])\s*(#|b|♯|♭|sharp|flat)?\s*$')
INLAYS = (3, 5, 7, 9, 12, 15, 17, 19, 21, 24)


def parse_root(root):
    """'F#' -> ('F', 1). Raises ValueError."""
    m = ROOT_RE.match(str(root or ''))
    if not m:
        raise ValueError(f'"{str(root)[:20]}" is not a note name. Use a letter A-G with optional # or b, e.g. "A", "F#", "Bb".')
    acc = m.group(2) or ''
    return m.group(1).upper(), (1 if acc in ('#', '♯', 'sharp') else -1 if acc in ('b', '♭', 'flat') else 0)


def note_name(letter, accidental):
    return letter + ('#' * accidental if accidental > 0 else 'b' * -accidental)


def interval_semitones(name):
    if name == 'R':
        return 0
    acc = name.count('#') - name.count('b')
    return DEGREE_SEMITONES[int(name.strip('#b'))] + acc


def spell(root, scale):
    """-> list of (note name, pitch class, interval name) in scale order."""
    letter, acc = parse_root(root)
    if scale not in SCALES:
        raise ValueError(f'Unknown scale "{str(scale)[:30]}". Try: ' + ', '.join(SCALES) + '.')
    root_pc = (NOTE[letter] + acc) % 12
    intervals = SCALES[scale][1]
    out = []
    if intervals is None:   # chromatic: flats for flat roots/F, sharps otherwise
        use_flats = acc < 0 or (letter == 'F' and acc == 0)
        sharp = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
        flat = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B')
        names = flat if use_flats else sharp
        for i, iv in enumerate(CHROMATIC_SHARP):
            pc = (root_pc + i) % 12
            out.append((note_name(letter, acc) if i == 0 else names[pc], pc, iv))
        return out
    for iv in intervals.split():
        degree = 1 if iv == 'R' else int(iv.strip('#b'))
        target = (root_pc + interval_semitones(iv)) % 12
        l = LETTERS[(LETTERS.index(letter) + degree - 1) % 7]
        a = (target - NOTE[l] + 6) % 12 - 6
        out.append((note_name(l, a), target, iv))
    return out


# ---------- drawing ----------
def _dot(cx, cy, label, root, r=12):
    fill = ROOT_COLOR if root else NOTE_COLOR
    size = 12 if len(label) <= 2 else 10
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="{size}" font-weight="700" '
            f'fill="{C["accent_text"]}">{svgkit.esc(label)}</text>')


def _legend(notes, x, y):
    out = []
    for i, (name, _, iv) in enumerate(notes):
        cx = x + i * 46
        out.append(_dot(cx, y, name, iv == 'R'))
        out.append(f'<text x="{cx}" y="{y + 30}" text-anchor="middle" font-size="12" fill="{C["sub"]}">{svgkit.esc(iv)}</text>')
    return out


def guitar_svg(notes, lo, hi, title):
    names = {pc: name for name, pc, _ in notes}
    root_pc = notes[0][1]
    fw, ss = 58, 34                      # fret width, string spacing
    left = 64
    open_col = lo == 0
    first = max(lo, 1)
    nfrets = hi - first + 1
    top = 56 if title else 24
    gx = left + (fw if open_col else 0)  # x of the nut / first fret line
    width = gx + nfrets * fw + 30
    width = max(width, 120 + len(notes) * 46)
    gy = top + 20
    height = gy + 5 * ss + 50 + 64
    y_of = lambda s: gy + (5 - s) * ss   # string 0 = low E at the bottom
    body = [f'<rect x="{left - 40}" y="{gy - 22}" width="{gx + nfrets * fw - left + 58}" height="{5 * ss + 44}" rx="12" fill="{C["panel"]}"/>']
    mid = gy + 2.5 * ss
    for f in range(first, hi + 1):       # inlays
        if f in INLAYS:
            cx = gx + (f - first + 0.5) * fw
            ys = (gy + 1.5 * ss, gy + 3.5 * ss) if f % 12 == 0 else (mid,)
            body += [f'<circle cx="{cx}" cy="{y}" r="6" fill="{C["line"]}" fill-opacity="0.55"/>' for y in ys]
    for i in range(nfrets + 1):          # fret lines
        x = gx + i * fw
        nut = open_col and i == 0
        body.append(f'<line x1="{x}" y1="{gy}" x2="{x}" y2="{gy + 5 * ss}" stroke="{"#ffffff" if nut else C["line"]}" '
                    f'stroke-width="{6 if nut else 2}"/>')
    for s in range(6):                   # strings
        body.append(f'<line x1="{gx - (fw if open_col else 0) + 8}" y1="{y_of(s)}" x2="{gx + nfrets * fw}" y2="{y_of(s)}" '
                    f'stroke="#c9d6ff" stroke-width="{1.0 + (5 - s) * 0.3:.1f}"/>')
        body.append(f'<text x="{left - 22}" y="{y_of(s) + 5}" text-anchor="middle" font-size="13" font-weight="700" '
                    f'fill="{C["sub"]}">{"EADGBe"[s]}</text>')
    for f in range(lo, hi + 1):          # fret numbers
        cx = gx - fw / 2 if f == 0 else gx + (f - first + 0.5) * fw
        body.append(f'<text x="{cx}" y="{gy + 5 * ss + 30}" text-anchor="middle" font-size="12" '
                    f'fill="{C["text"] if f in INLAYS else C["sub"]}">{f}</text>')
    for s in range(6):
        for f in range(lo, hi + 1):
            pc = (TUNING[s] + f) % 12
            if pc in names:
                cx = gx - fw / 2 if f == 0 else gx + (f - first + 0.5) * fw
                body.append(_dot(cx, y_of(s), names[pc], pc == root_pc))
    body += _legend(notes, left, gy + 5 * ss + 66)
    return svgkit.svg_document(width, height, body, title)


WHITE_PCS = (0, 2, 4, 5, 7, 9, 11)
BLACK_AFTER = {0: 1, 2: 3, 5: 6, 7: 8, 9: 10}   # white pc -> black key above it


def piano_svg(notes, title):
    names = {pc: name for name, pc, _ in notes}
    root_pc = notes[0][1]
    start = root_pc if root_pc in WHITE_PCS else root_pc - 1   # white key at or below the root
    end = root_pc + 24                                          # two octaves, ending on the root again
    end += 0 if end % 12 in WHITE_PCS else 1                    # a black-key root needs the white key above it
    whites = [p for p in range(start, end + 1) if p % 12 in WHITE_PCS]
    kw, kh, bw, bh = 40, 170, 26, 106
    left = 24
    top = 56 if title else 24
    width = max(left * 2 + len(whites) * kw, 120 + len(notes) * 46)
    height = top + kh + 104
    body = []
    xs = {}
    for i, p in enumerate(whites):
        x = left + i * kw
        xs[p] = x
        hit = p % 12 in names
        fill = '#ffffff'
        if hit:
            fill = ROOT_COLOR if p % 12 == root_pc else NOTE_COLOR
        body.append(f'<rect x="{x}" y="{top}" width="{kw}" height="{kh}" rx="4" fill="{fill}" stroke="{C["bg"]}" stroke-width="2"/>')
        if hit:
            body.append(f'<text x="{x + kw / 2}" y="{top + kh - 14}" text-anchor="middle" font-size="14" font-weight="700" '
                        f'fill="{C["accent_text"]}">{svgkit.esc(names[p % 12])}</text>')
    for p in whites:
        b = p + 1
        if p % 12 not in BLACK_AFTER or (p + 2) not in xs:
            continue
        x = xs[p] + kw - bw / 2
        hit = b % 12 in names
        fill = '#1b2238'
        if hit:
            fill = ROOT_COLOR if b % 12 == root_pc else NOTE_COLOR
        body.append(f'<rect x="{x}" y="{top}" width="{bw}" height="{bh}" rx="3" fill="{fill}" stroke="{C["bg"]}" stroke-width="2"/>')
        if hit:
            label = names[b % 12]
            body.append(f'<text x="{x + bw / 2}" y="{top + bh - 10}" text-anchor="middle" font-size="{11 if len(label) <= 2 else 9}" '
                        f'font-weight="700" fill="{C["accent_text"]}">{svgkit.esc(label)}</text>')
    body += _legend(notes, left + 12, top + kh + 40)
    return svgkit.svg_document(width, height, body, title)


# ---------- tool interface ----------
TOOLS = [{
    'name': 'draw_scale',
    'description': ('Draw a scale, mode or arpeggio on a guitar fretboard or piano keyboard as an image, with '
                    'correctly spelled note names and roots highlighted. Free, instant. root e.g. "A", "F#", "Bb"; '
                    'scale e.g. major, natural_minor, dorian, minor_pentatonic, blues, m7_arpeggio; instrument '
                    'guitar (default) or piano; guitar frets window {from, to} (default 0-12). Use for any '
                    'scale/mode/arpeggio chart instead of image generators.'),
    'inputSchema': {'type': 'object', 'required': ['root', 'scale'], 'additionalProperties': False, 'properties': {
        'root': {'type': 'string', 'minLength': 1, 'maxLength': 8},
        'scale': {'type': 'string', 'enum': list(SCALES)},
        'instrument': {'type': 'string', 'enum': ['guitar', 'piano'], 'default': 'guitar'},
        'frets': {'type': 'object', 'additionalProperties': False, 'required': ['from', 'to'], 'properties': {
            'from': {'type': 'integer', 'minimum': 0, 'maximum': 12},
            'to': {'type': 'integer', 'minimum': 3, 'maximum': 24}}},
        'title': {'type': 'string', 'maxLength': 80}}},
}]


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


def _frets(value):
    if value is None:
        return 0, 12
    if not isinstance(value, dict) or set(value) - {'from', 'to'}:
        raise ValueError('frets must look like {"from": 5, "to": 9}.')
    lo, hi = value.get('from', 0), value.get('to')
    if hi is None and isinstance(lo, int):
        hi = min(lo + 12, 24)
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi)):
        raise ValueError('frets.from and frets.to must be whole numbers.')
    if not 0 <= lo <= 12:
        raise ValueError('frets.from must be between 0 and 12.')
    if not lo + 3 <= hi <= lo + 12:
        raise ValueError(f'frets.to must be between {lo + 3} and {lo + 12} (a window of 4-13 frets).')
    return lo, hi


def call(tool, arguments):
    if tool != TOOLS[0]['name']:
        return _error('Unknown scale tool.')
    if not isinstance(arguments, dict):
        return _error('Pass an object like {"root": "A", "scale": "minor_pentatonic"}.')
    scale = arguments.get('scale')
    instrument = arguments.get('instrument') or 'guitar'
    title = arguments.get('title') or ''
    if not isinstance(title, str):
        return _error('title must be text.')
    if instrument not in ('guitar', 'piano'):
        return _error('instrument must be "guitar" or "piano".')
    if not isinstance(scale, str) or scale not in SCALES:
        return _error('Unknown scale. Choose one of: ' + ', '.join(SCALES) + '.')
    try:
        notes = spell(arguments.get('root'), scale)
        lo, hi = _frets(arguments.get('frets'))
    except ValueError as error:
        return _error(str(error))
    label = f'{notes[0][0]} {SCALES[scale][0]}'
    title = title[:80] or label
    summary = f'{label}: {" ".join(n for n, _, _ in notes)} ({" ".join(iv for _, _, iv in notes)})'
    if instrument == 'guitar':
        summary += f' — guitar, standard tuning, frets {lo}-{hi}; low E string at the bottom, roots in orange.'
        svg = guitar_svg(notes, lo, hi, title)
    else:
        summary += ' — piano, two octaves from the root, roots in orange.'
        svg = piano_svg(notes, title)
    return svgkit.image_result(summary, svg)
