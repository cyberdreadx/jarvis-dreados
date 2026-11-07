"""Exact guitar chord diagrams, computed from music theory and drawn as SVG.

Image generators can't count strings or frets, so chord charts are worked out here instead:
chord name -> notes -> best playable shape in standard tuning -> crisp vector diagram.
No network, no credits, no dependencies.
"""
import base64
import itertools
import re
from html import escape

TUNING = (40, 45, 50, 55, 59, 64)          # E2 A2 D3 G3 B3 E4, low to high
STRING_NAMES = ('E', 'A', 'D', 'G', 'B', 'e')
NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SHARP_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

CHORD_RE = re.compile(r'^([A-G])([#b♯♭]?)(.*?)(?:/([A-G])([#b♯♭]?))?$')
EXAMPLES = 'e.g. C, Am, G7, Cmaj9, Dm7b5, F#m11, G7#11, E7alt, C7(b9#11), A13, Bb6/9, Dsus4, Fadd9, C/E'
# Altered/added tones: interval in semitones from the root.
ALTERATIONS = {'b5': 6, '#5': 8, 'b9': 1, '#9': 3, '#11': 6, 'b13': 8}
ADDS = {'2': 2, '9': 2, '4': 5, '11': 5, '6': 9, '13': 9}


def _intervals(suffix, name):
    """Read a chord suffix ('m7b5', 'maj9#11', '7(b9,#11)', '6/9', 'alt', ...) into
    (all tones, required tones) as intervals from the root."""
    s = suffix.replace('♯', '#').replace('♭', 'b').replace('Δ', 'maj').replace('°', 'dim').replace('ø', 'm7b5')
    s = re.sub(r'[()\s,]', '', s)
    third, fifth, seventh, sixth, ext = 4, 7, None, None, 0
    extras, req_extras, sus, power, fifth_required = set(), set(), None, False, False

    def take(pattern):
        nonlocal s
        m = re.match(pattern, s)
        if m:
            s = s[m.end():]
        return m

    # 1. quality
    if take(r'(mMaj|mM|minMaj|-maj|mmaj)'):
        third, seventh = 3, 11
    elif take(r'(maj|Maj|ma|M)(?=\d|$|[#b]|add|sus)'):
        seventh = 'maj'                       # resolved below: 'Cmaj' alone is a major triad
    elif take(r'(min|m|-)(?!aj)'):
        third = 3
    elif take(r'dim'):
        third, fifth, fifth_required = 3, 6, True
        if take(r'7'):
            seventh = 9
    elif take(r'o'):
        third, fifth, fifth_required = 3, 6, True
        if take(r'7'):
            seventh = 9
    elif take(r'(aug|\+)'):
        fifth, fifth_required = 8, True
    # 2. number: 5 (power), 6, 6/9, 7, 9, 11, 13
    m = take(r'(6/9|69|5|6|7|9|11|13)')
    if m:
        num = m.group(1)
        if num == '5':
            power = True
        elif num in ('6/9', '69'):
            sixth, req_extras = 9, req_extras | {2}
        elif num == '6':
            sixth = 9
        else:
            ext = int(num)
            if seventh is None:
                seventh = 10
            elif seventh == 'maj':
                seventh = 11
    if seventh == 'maj':                      # 'Cmaj' / 'CM' with no number is just a major triad
        seventh = None
    # 3. modifiers in any order
    while s:
        if take(r'sus2'):
            sus = 2
        elif take(r'sus4?'):
            sus = 5
        elif (m := take(r'add([24]|9|11|6|13)')):
            req_extras.add(ADDS[m.group(1)])
        elif (m := take(r'(b5|#5|b9|#9|#11|b13)')):
            val = ALTERATIONS[m.group(1)]
            if m.group(1) in ('b5', '#5'):
                fifth, fifth_required = val, True
            else:
                req_extras.add(val)
        elif take(r'-5'):
            fifth, fifth_required = 6, True
        elif take(r'\+5'):
            fifth, fifth_required = 8, True
        elif take(r'alt'):
            seventh = seventh or 10
            req_extras.add(3)               # #9 defines the sound; b9/#11/b13 may appear too
            extras |= {1, 6, 8}
            fifth = None
        elif take(r'no3'):
            third = None
        elif take(r'no5'):
            fifth = None
        else:
            raise ValueError(f'Can\'t read "{s}" in "{name}". Use standard chord symbols, {EXAMPLES}.')
    if power:
        return frozenset({0, 7}), frozenset({0, 7})
    if sus:
        third = sus
    # extensions implied by 9/11/13 chords: the top one is required, lower ones optional
    if ext >= 9:
        extras.add(2)
        if ext == 9:
            req_extras.add(2)
    if ext >= 11 and not (ext == 13 and third == 4):
        extras.add(5)
        if ext == 11:
            req_extras.add(5)
            if third == 4:                     # a major 3rd clashes with the 11th: play it as sus
                third = None
    if ext == 13:
        req_extras.add(9)
    tones = {0} | extras | req_extras
    required = {0} | req_extras
    for t, needed in ((third, True), (seventh, True), (sixth, True), (fifth, fifth_required)):
        if isinstance(t, int):
            tones.add(t)
            if needed:
                required.add(t)
    return frozenset(tones), frozenset(required)
FRETS_RE = re.compile(r'^[x0-9]{6}$', re.I)


def pitch(letter, accidental):
    return (NOTE[letter] + (1 if accidental in '#♯' and accidental else -1 if accidental in 'b♭' and accidental else 0)) % 12


def parse(name):
    """'Dm7' -> (root pc, bass pc, chord tones, required tones) as pitch classes."""
    m = CHORD_RE.match(name.strip())
    if not m:
        raise ValueError(f'"{name}" is not a chord name (try Dm7, G7, Cmaj7, F#m7b5, C/E).')
    root = pitch(m.group(1), m.group(2))
    tones, required = _intervals(m.group(3).strip(), name)
    pcs = frozenset((root + t) % 12 for t in tones)
    req = frozenset((root + t) % 12 for t in required)
    bass = pitch(m.group(4), m.group(5)) if m.group(4) else root
    return root, bass, pcs | {bass}, req | {bass}


def _fingers(frets):
    """Finger numbers (0 = open/muted) and the barre fret if one is used."""
    fretted = [(f, s) for s, f in enumerate(frets) if isinstance(f, int) and f > 0]
    if not fretted:
        return [0] * 6, None
    low = min(f for f, _ in fretted)
    at_low = [s for f, s in fretted if f == low]
    barre = None
    if len(at_low) >= 2:
        span = range(at_low[0], at_low[-1] + 1)
        # A barre presses every string under it, so each must sound at or above the barre fret
        # (an open or muted string inside the span would be fretted by the barre).
        if all(isinstance(frets[s], int) and frets[s] >= low for s in span):
            barre = low
    out, finger = [0] * 6, 1
    if barre:
        for s in at_low:
            out[s] = 1
        finger = 2
    for f, s in sorted(fretted):
        if barre and f == barre:
            continue
        out[s] = finger
        finger += 1
    return out, barre


def _playable(frets):
    fingers, barre = _fingers(frets)
    return max(fingers) <= 4, fingers, barre


def _score(frets, pcs, style, fingers, barre):
    sounded = [s for s, f in enumerate(frets) if f != 'x']
    fretted = [f for f in frets if isinstance(f, int) and f > 0]
    low_s, high_s = sounded[0], sounded[-1]
    internal_mutes = sum(1 for s in range(low_s, high_s) if frets[s] == 'x')
    pos = min(fretted) if fretted else 0
    span = (max(fretted) - min(fretted)) if fretted else 0
    opens = sum(1 for f in frets if f == 0)
    played = {(TUNING[s] + frets[s]) % 12 for s in sounded}
    top_mutes = 5 - high_s                           # muting the thin strings takes extra damping
    score = 0.0
    score += internal_mutes * (0.6 if style == 'movable' else 2.5)
    score += (6 - len(sounded)) * (0.25 if style == 'movable' else 0.6)
    score += top_mutes * (0.35 if style == 'movable' else 0.7)
    score += max(0, pos - 1) * (0.3 if style == 'movable' else 0.35)
    score += span * 0.4 + max(fingers) * 0.3 + (0.8 if barre else 0)
    score -= opens * 0.4
    score += 0.2 * (len(pcs) - len(played))        # small preference for complete chords
    if style == 'movable':
        score += 0 if low_s in (0, 1) else 1.5        # root on the E or A string, like jazz shapes
        score += 0.4 if len(sounded) > 4 else 0       # 4-note shells are the norm
        # Shell voicings skip the string right above the bass (x5x565, 3x343x), not one in the middle.
        score += sum(1.0 for s in range(low_s + 2, high_s) if frets[s] == 'x')
    return score


def voice(name, style='open'):
    """Best playable shape for a chord: list of 6 frets ('x' = muted, 0 = open)."""
    _, bass, pcs, required = parse(name)
    # Normal reach first (4 frets); big extended chords may need a 5-fret stretch, then the
    # other style (e.g. an open string can make a 6-note jazz chord playable).
    for reach, mode in ((3, style), (4, style), (3, 'open' if style == 'movable' else 'movable'), (4, 'open')):
        best = _search(pcs, required, bass, mode, reach, style)
        if best:
            return best
    raise ValueError(f'No playable shape found for {name} in standard tuning. Give it as Name=x5x565 if you know a shape.')


def _search(pcs, required, bass, mode, reach, style):
    allow_open = mode != 'movable'
    best = None
    for base in range(1, 13):
        options = []
        for s in range(6):
            opts = ['x']
            for f in ([0] if allow_open else []) + list(range(base, base + reach + 1)):
                if (TUNING[s] + f) % 12 in pcs:
                    opts.append(f)
            options.append(opts)
        for frets in itertools.product(*options):
            sounded = [s for s, f in enumerate(frets) if f != 'x']
            if len(sounded) < 4 and not (len(pcs) <= 3 and len(sounded) == 3):
                continue
            if (TUNING[sounded[0]] + frets[sounded[0]]) % 12 != bass:
                continue
            played = {(TUNING[s] + frets[s]) % 12 for s in sounded}
            if not required <= played:
                continue
            fretted = [f for f in frets if isinstance(f, int) and f > 0]
            if fretted and max(fretted) - min(fretted) > reach:
                continue
            ok, fingers, barre = _playable(list(frets))
            if not ok:
                continue
            score = _score(list(frets), pcs, style, fingers, barre) + (1.5 if reach > 3 else 0)
            if best is None or score < best[0]:
                best = (score, list(frets))
    return best[1] if best else None


def frets_text(frets):
    return ' '.join(str(f) for f in frets)


def parse_spec(spec, style):
    """'Dm7' or 'Dm7=x5x565' (or frets with dashes for 10+: x-10-x-10-11-10)."""
    if '=' in spec:
        name, raw = (p.strip() for p in spec.split('=', 1))
        parts = raw.split('-') if '-' in raw else list(raw)
        if len(parts) != 6 or not all(re.fullmatch(r'x|X|\d{1,2}', p) for p in parts):
            raise ValueError(f'Shape for {name} must be 6 frets low E to high e, like x5x565 or x-10-x-10-11-10.')
        frets = ['x' if p.lower() == 'x' else int(p) for p in parts]
        if all(f == 'x' for f in frets):
            raise ValueError(f'Shape for {name} mutes every string.')
        return name or 'Chord', frets
    return spec.strip(), voice(spec.strip(), style)


# ---------- drawing ----------
CELL_W, CELL_H, PER_ROW = 190, 270, 4
COLORS = {'bg': '#0b1020', 'panel': '#111a33', 'string': '#c9d6ff', 'fret': '#5d6a8f', 'nut': '#ffffff',
          'dot': '#2ff3d0', 'dot_text': '#06121a', 'mute': '#ff6b8a', 'name': '#ffffff', 'sub': '#8f9bc4'}


def _diagram(name, frets, x0, y0):
    fingers, barre = _fingers(frets)
    fretted = [f for f in frets if isinstance(f, int) and f > 0]
    # Shapes that sit up the neck start at their lowest fret with an "Nfr" label, like printed charts.
    start = 1 if not fretted or max(fretted) <= 4 else min(fretted)
    gx, gy, sx, fy = x0 + 40, y0 + 78, 22, 30          # grid origin, string spacing, fret spacing
    out = [f'<rect x="{x0 + 8}" y="{y0 + 8}" width="{CELL_W - 16}" height="{CELL_H - 16}" rx="14" fill="{COLORS["panel"]}"/>',
           f'<text x="{x0 + CELL_W / 2}" y="{y0 + 40}" text-anchor="middle" font-size="22" font-weight="700" fill="{COLORS["name"]}">{escape(name)}</text>']
    for i in range(6):   # strings
        out.append(f'<line x1="{gx + i * sx}" y1="{gy}" x2="{gx + i * sx}" y2="{gy + 5 * fy}" stroke="{COLORS["string"]}" stroke-width="{1.2 + (5 - i) * 0.25:.2f}"/>')
    for r in range(6):   # frets
        out.append(f'<line x1="{gx}" y1="{gy + r * fy}" x2="{gx + 5 * sx}" y2="{gy + r * fy}" stroke="{COLORS["fret"]}" stroke-width="1.5"/>')
    if start == 1:
        out.append(f'<rect x="{gx - 1}" y="{gy - 5}" width="{5 * sx + 2}" height="6" fill="{COLORS["nut"]}"/>')
    else:
        out.append(f'<text x="{gx - 10}" y="{gy + fy / 2 + 5}" text-anchor="end" font-size="13" fill="{COLORS["sub"]}">{start}fr</text>')
    for s, f in enumerate(frets):   # open / muted markers above the nut
        cx = gx + s * sx
        if f == 'x':
            out.append(f'<text x="{cx}" y="{gy - 12}" text-anchor="middle" font-size="15" font-weight="700" fill="{COLORS["mute"]}">×</text>')
        elif f == 0:
            out.append(f'<circle cx="{cx}" cy="{gy - 17}" r="5.5" fill="none" stroke="{COLORS["string"]}" stroke-width="1.6"/>')
    if barre:
        strings = [s for s, f in enumerate(frets) if f == barre]
        y = gy + (barre - start + 0.5) * fy
        out.append(f'<rect x="{gx + strings[0] * sx - 10}" y="{y - 10}" width="{(strings[-1] - strings[0]) * sx + 20}" height="20" rx="10" fill="{COLORS["dot"]}"/>')
        out.append(f'<text x="{gx + (strings[0] + strings[-1]) / 2 * sx}" y="{y + 5}" text-anchor="middle" font-size="13" font-weight="700" fill="{COLORS["dot_text"]}">1</text>')
    for s, f in enumerate(frets):   # finger dots
        if isinstance(f, int) and f > 0 and f != barre:
            cx, cy = gx + s * sx, gy + (f - start + 0.5) * fy
            out.append(f'<circle cx="{cx}" cy="{cy}" r="10" fill="{COLORS["dot"]}"/>')
            out.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="13" font-weight="700" fill="{COLORS["dot_text"]}">{fingers[s]}</text>')
    for s, n in enumerate(STRING_NAMES):
        out.append(f'<text x="{gx + s * sx}" y="{gy + 5 * fy + 18}" text-anchor="middle" font-size="11" fill="{COLORS["sub"]}">{n}</text>')
    out.append(f'<text x="{x0 + CELL_W / 2}" y="{gy + 5 * fy + 40}" text-anchor="middle" font-size="13" font-family="Consolas,monospace" fill="{COLORS["sub"]}">{frets_text(frets)}</text>')
    return out


def render_svg(chords, title=''):
    rows = (len(chords) + PER_ROW - 1) // PER_ROW
    cols = min(PER_ROW, len(chords))
    top = 46 if title else 6
    w, h = cols * CELL_W + 12, rows * CELL_H + top + 6
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="Segoe UI,Arial,sans-serif"><rect width="{w}" height="{h}" fill="{COLORS["bg"]}"/>']
    if title:
        body.append(f'<text x="18" y="32" font-size="20" font-weight="700" fill="{COLORS["name"]}">{escape(title)}</text>')
    for i, (name, frets) in enumerate(chords):
        body += _diagram(name, frets, 6 + (i % PER_ROW) * CELL_W, top + (i // PER_ROW) * CELL_H)
    body.append('</svg>')
    return ''.join(body)


# ---------- tool interface (used by mcp_client as a built-in service) ----------
TOOL = {
    'name': 'draw_chord_diagrams',
    'description': ('Draw exact guitar chord diagrams (standard tuning) as an image. Free and instant, no credits. '
                    'Pass chord names such as "Dm7", "G7", "Cmaj7", "F#m7b5", "C/E"; DreadOS works out correct, playable '
                    'fingerings from music theory, so do not invent fret numbers. Only when the user gives an exact shape, '
                    'pass it as "Name=x5x565" (6 frets, low E to high e, x = muted). style "open" = open-position shapes '
                    'for beginners (default); "movable" = no open strings, jazz/barre shapes. Prefer this over image '
                    'generators for any chord chart.'),
    'inputSchema': {'type': 'object', 'required': ['chords'], 'additionalProperties': False, 'properties': {
        'chords': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {'type': 'string', 'maxLength': 40}},
        'style': {'type': 'string', 'enum': ['open', 'movable'], 'default': 'open'},
        'title': {'type': 'string', 'maxLength': 80}}},
}


def call(tool, arguments):
    """MCP-style result: a text summary plus the SVG image."""
    if tool != TOOL['name']:
        raise ValueError('Unknown diagram tool.')
    chords = arguments.get('chords')
    style = arguments.get('style', 'open')
    title = str(arguments.get('title') or '')[:80]
    if style not in ('open', 'movable'):
        style = 'open'
    if not isinstance(chords, list) or not 1 <= len(chords) <= 12 or not all(isinstance(c, str) and c.strip() for c in chords):
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Pass 1-12 chord names, e.g. ["Dm7","G7","Cmaj7"].'}]}
    shapes, problems = [], []
    for spec in chords:     # draw everything that works; one unknown chord shouldn't sink the rest
        try:
            shapes.append(parse_spec(spec, style))
        except ValueError as error:
            problems.append(str(error))
    if not shapes:
        return {'isError': True, 'content': [{'type': 'text', 'text': '\n'.join(problems)}]}
    lines = [f'{name}: {frets_text(frets)}  (strings E A D G B e, x = muted, 0 = open)' for name, frets in shapes]
    if problems:
        lines.append('Not drawn: ' + ' '.join(problems))
    svg = render_svg(shapes, title)
    return {'content': [{'type': 'text', 'text': ('Chord diagrams' + (f' — {title}' if title else '') + ':\n' + '\n'.join(lines))},
                        {'type': 'image', 'mimeType': 'image/svg+xml', 'data': base64.b64encode(svg.encode()).decode('ascii')}]}
