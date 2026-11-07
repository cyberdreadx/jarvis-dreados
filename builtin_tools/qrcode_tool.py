"""QR codes, encoded from scratch per ISO/IEC 18004 and drawn as crisp SVG.

Numeric, alphanumeric and byte (UTF-8) modes, error correction L/M/Q/H, versions 1-40 chosen
automatically, Reed-Solomon over GF(256), block interleaving, all function patterns, format and
version information, and all 8 masks scored with the four penalty rules.
"""
import itertools
import re

from . import svgkit

MAX_BYTES = 1000

# ---------- tables (index 0 unused; versions 1-40) ----------
EC_LEVELS = ('L', 'M', 'Q', 'H')
FORMAT_BITS = {'L': 1, 'M': 0, 'Q': 3, 'H': 2}
ECC_PER_BLOCK = {
    'L': (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    'M': (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    'Q': (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    'H': (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
}
NUM_BLOCKS = {
    'L': (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    'M': (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    'Q': (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    'H': (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
}
ALPHANUMERIC = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
MODE_BITS = {'numeric': 0b0001, 'alphanumeric': 0b0010, 'byte': 0b0100}
COUNT_BITS = {'numeric': (10, 12, 14), 'alphanumeric': (9, 11, 13), 'byte': (8, 16, 16)}

# ---------- GF(256) with primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D) ----------
EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a, b):
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def rs_generator(degree):
    """Coefficients (highest power first, leading 1 included) of prod_{i<degree} (x - a^i)."""
    poly = [1]
    for i in range(degree):
        nxt = poly + [0]
        for j, c in enumerate(poly):
            nxt[j + 1] ^= gf_mul(c, EXP[i])
        poly = nxt
    return poly


def rs_remainder(data, degree):
    """Error-correction codewords: data(x) * x^degree mod generator(x)."""
    gen = rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        if factor:
            for j in range(degree):
                rem[j] ^= gf_mul(gen[j + 1], factor)
    return rem


# ---------- structure ----------
def size_of(version):
    return version * 4 + 17


def alignment_positions(version):
    if version == 1:
        return []
    count = version // 7 + 2
    step = (version * 8 + count * 3 + 5) // (count * 4 - 4) * 2
    last = size_of(version) - 7
    return [6] + [last - i * step for i in range(count - 2, -1, -1)]


def raw_data_modules(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def total_codewords(version):
    return raw_data_modules(version) // 8


def data_codewords(version, ec):
    return total_codewords(version) - ECC_PER_BLOCK[ec][version] * NUM_BLOCKS[ec][version]


def block_layout(version, ec):
    """List of data-codeword counts per block (short blocks first) and EC codewords per block."""
    blocks, ecc = NUM_BLOCKS[ec][version], ECC_PER_BLOCK[ec][version]
    total = total_codewords(version)
    short_total = total // blocks
    long_count = total % blocks
    short_data = short_total - ecc
    return [short_data + (1 if i >= blocks - long_count else 0) for i in range(blocks)], ecc


def format_bits(ec, mask):
    data = FORMAT_BITS[ec] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | (rem & 0x3FF)) ^ 0x5412


def version_bits(version):
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return version << 12 | (rem & 0xFFF)


# ---------- data encoding ----------
def choose_mode(text):
    if text and all('0' <= c <= '9' for c in text):
        return 'numeric'
    if text and all(c in ALPHANUMERIC for c in text):
        return 'alphanumeric'
    return 'byte'


class _Bits(list):
    def put(self, value, length):
        self.extend((value >> i) & 1 for i in range(length - 1, -1, -1))


def _payload_bits(text, mode):
    bits = _Bits()
    if mode == 'numeric':
        for i in range(0, len(text), 3):
            chunk = text[i:i + 3]
            bits.put(int(chunk), 3 * len(chunk) + 1)
        return bits, len(text)
    if mode == 'alphanumeric':
        for i in range(0, len(text) - 1, 2):
            bits.put(ALPHANUMERIC.index(text[i]) * 45 + ALPHANUMERIC.index(text[i + 1]), 11)
        if len(text) % 2:
            bits.put(ALPHANUMERIC.index(text[-1]), 6)
        return bits, len(text)
    raw = text.encode('utf-8')
    for b in raw:
        bits.put(b, 8)
    return bits, len(raw)


def _count_bits(mode, version):
    return COUNT_BITS[mode][0 if version <= 9 else 1 if version <= 26 else 2]


def encode_data(text, ec='M', mode=None):
    """-> (version, mode, data codewords). Raises ValueError if it does not fit version 40."""
    mode = mode or choose_mode(text)
    payload, count = _payload_bits(text, mode)
    for version in range(1, 41):
        cbits = _count_bits(mode, version)
        capacity = data_codewords(version, ec) * 8
        if count < (1 << cbits) and 4 + cbits + len(payload) <= capacity:
            break
    else:
        raise ValueError('That text is too long for a QR code at this error-correction level.')
    bits = _Bits()
    bits.put(MODE_BITS[mode], 4)
    bits.put(count, cbits)
    bits.extend(payload)
    bits.extend([0] * min(4, capacity - len(bits)))
    bits.extend([0] * (-len(bits) % 8))
    words = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    for pad in itertools.cycle((0xEC, 0x11)):
        if len(words) >= capacity // 8:
            break
        words.append(pad)
    return version, mode, words


def add_ec_and_interleave(words, version, ec):
    sizes, ecc = block_layout(version, ec)
    blocks, pos = [], 0
    for n in sizes:
        blocks.append(words[pos:pos + n])
        pos += n
    eccs = [rs_remainder(b, ecc) for b in blocks]
    out = []
    for i in range(max(sizes)):
        out.extend(b[i] for b in blocks if i < len(b))
    for i in range(ecc):
        out.extend(e[i] for e in eccs)
    return out


# ---------- matrix ----------
MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def function_patterns(version):
    """-> (modules, is_function) with finders, separators, timing, alignment, dark module and
    reserved (blank) format/version areas. Indexed [y][x]."""
    n = size_of(version)
    mod = [[0] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def put(x, y, dark):
        mod[y][x] = 1 if dark else 0
        fn[y][x] = True

    for i in range(n):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < n and 0 <= y < n:
                    d = max(abs(dx), abs(dy))
                    put(x, y, d not in (2, 4))
    pos = alignment_positions(version)
    last = len(pos) - 1
    for i, ay in enumerate(pos):
        for j, ax in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
    _draw_format(mod, fn, 0)          # reserve
    if version >= 7:
        bits = version_bits(version)
        for i in range(18):
            dark = (bits >> i) & 1
            a, b = n - 11 + i % 3, i // 3
            put(a, b, dark)
            put(b, a, dark)
    return mod, fn


def _draw_format(mod, fn, bits):
    n = len(mod)

    def put(x, y, dark):
        mod[y][x] = 1 if dark else 0
        fn[y][x] = True

    bit = lambda i: (bits >> i) & 1
    for i in range(6):
        put(8, i, bit(i))
    put(8, 7, bit(6))
    put(8, 8, bit(7))
    put(7, 8, bit(8))
    for i in range(9, 15):
        put(14 - i, 8, bit(i))
    for i in range(8):
        put(n - 1 - i, 8, bit(i))
    for i in range(8, 15):
        put(8, n - 15 + i, bit(i))
    put(8, n - 8, 1)                   # dark module


def place_data(mod, fn, codewords):
    n = len(mod)
    i, total = 0, len(codewords) * 8
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vert in range(n):
            y = n - 1 - vert if upward else vert
            for x in (right, right - 1):
                if not fn[y][x] and i < total:
                    mod[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1
                    i += 1
        right -= 2


def apply_mask(mod, fn, mask):
    f = MASKS[mask]
    return [[m ^ 1 if (not fn[y][x] and f(x, y)) else m for x, m in enumerate(row)] for y, row in enumerate(mod)]


_FINDER = re.compile(r'(?=(10111010000|00001011101))')


def penalty(mod):
    n = len(mod)
    score = 0
    lines = [''.join(map(str, row)) for row in mod]
    lines += [''.join(str(mod[y][x]) for y in range(n)) for x in range(n)]
    for line in lines:
        for _, group in itertools.groupby(line):
            run = sum(1 for _ in group)
            if run >= 5:
                score += 3 + run - 5
        score += 40 * len(_FINDER.findall('0000' + line + '0000'))
    for y in range(n - 1):
        r0, r1 = mod[y], mod[y + 1]
        for x in range(n - 1):
            c = r0[x]
            if c == r0[x + 1] == r1[x] == r1[x + 1]:
                score += 3
    dark = sum(map(sum, mod))
    total = n * n
    score += 10 * (abs(dark * 100 - total * 50) // (total * 5))
    return score


def encode(text, ec='M', mask=None):
    """-> dict(matrix, version, mode, mask, ec). matrix is [y][x] with 1 = dark."""
    version, mode, words = encode_data(text, ec)
    codewords = add_ec_and_interleave(words, version, ec)
    base, fn = function_patterns(version)
    place_data(base, fn, codewords)
    best = None
    for m in (range(8) if mask is None else [mask]):
        trial = apply_mask(base, fn, m)
        _draw_format(trial, [row[:] for row in fn], format_bits(ec, m))
        score = penalty(trial) if mask is None else 0
        if best is None or score < best[0]:
            best = (score, m, trial)
    return {'matrix': best[2], 'version': version, 'mode': mode, 'mask': best[1], 'ec': ec}


# ---------- rendering ----------
def render_svg(matrix, title='', caption=''):
    n = len(matrix)
    quiet = 4
    scale = max(2, min(10, 420 // (n + 2 * quiet)))
    side = (n + 2 * quiet) * scale
    pad = 24
    top = 50 if title else pad
    cap_h = 34 if caption else 0
    w = max(side + 2 * pad, 300)
    h = top + side + cap_h + pad
    ox, oy = (w - side) // 2, top
    q = quiet * scale
    rects = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                rects.append(f'M{ox + q + start * scale} {oy + q + y * scale}h{(x - start) * scale}v{scale}h-{(x - start) * scale}z')
            else:
                x += 1
    body = [f'<rect x="{ox}" y="{oy}" width="{side}" height="{side}" fill="#ffffff"/>',
            f'<path d="{"".join(rects)}" fill="#000000" shape-rendering="crispEdges"/>']
    if caption:
        body.append(f'<text x="{w / 2}" y="{oy + side + 26}" text-anchor="middle" font-size="15" '
                    f'fill="{svgkit.COLORS["sub"]}">{svgkit.esc(caption)}</text>')
    return svgkit.svg_document(w, h, body, title)


# ---------- tool interface ----------
def _wifi_escape(value):
    return re.sub(r'([\\;,:"])', r'\\\1', value)


TOOLS = [{
    'name': 'make_qr_code',
    'description': ('Make a scannable QR code image. Free, offline. Give exactly one of: text (any text), url '
                    '(a web link), or wifi {ssid, password, security WPA|WEP|nopass, hidden} so phones can join '
                    'a network by scanning. Optional ec_level L/M/Q/H (default M; H survives more damage), '
                    'caption shown under the code, title. Use this instead of image generators for QR codes.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {
        'text': {'type': 'string', 'minLength': 1, 'maxLength': MAX_BYTES},
        'url': {'type': 'string', 'minLength': 1, 'maxLength': MAX_BYTES},
        'wifi': {'type': 'object', 'additionalProperties': False, 'required': ['ssid'], 'properties': {
            'ssid': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'password': {'type': 'string', 'maxLength': 128},
            'security': {'type': 'string', 'enum': ['WPA', 'WEP', 'nopass'], 'default': 'WPA'},
            'hidden': {'type': 'boolean', 'default': False}}},
        'ec_level': {'type': 'string', 'enum': list(EC_LEVELS), 'default': 'M'},
        'caption': {'type': 'string', 'maxLength': 80},
        'title': {'type': 'string', 'maxLength': 80}}},
}]


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


def _build(arguments):
    """-> (payload text, kind, default caption, summary detail) or raises ValueError."""
    given = [k for k in ('text', 'url', 'wifi') if arguments.get(k) not in (None, '', {})]
    if len(given) != 1:
        raise ValueError('Give exactly one of "text", "url" or "wifi" for the QR code.')
    kind = given[0]
    if kind == 'wifi':
        wifi = arguments['wifi']
        if not isinstance(wifi, dict) or set(wifi) - {'ssid', 'password', 'security', 'hidden'}:
            raise ValueError('wifi must be an object like {"ssid": "Home", "password": "...", "security": "WPA"}.')
        ssid, password = wifi.get('ssid'), wifi.get('password') or ''
        if not isinstance(ssid, str) or not ssid or len(ssid) > 64:
            raise ValueError('wifi.ssid (the network name) is required, up to 64 characters.')
        if not isinstance(password, str) or len(password) > 128:
            raise ValueError('wifi.password must be text, up to 128 characters.')
        security = wifi.get('security') or ('WPA' if password else 'nopass')
        if security not in ('WPA', 'WEP', 'nopass'):
            raise ValueError('wifi.security must be WPA, WEP or nopass.')
        if security != 'nopass' and not password:
            raise ValueError(f'A {security} network needs wifi.password (or use security "nopass").')
        hidden = wifi.get('hidden', False)
        if not isinstance(hidden, bool):
            raise ValueError('wifi.hidden must be true or false.')
        payload = f'WIFI:T:{security};S:{_wifi_escape(ssid)};'
        if security != 'nopass':
            payload += f'P:{_wifi_escape(password)};'
        if hidden:
            payload += 'H:true;'
        payload += ';'
        lock = 'open network' if security == 'nopass' else f'{security}, password hidden'
        detail = f'Wi-Fi network "{ssid}" ({lock}{", hidden SSID" if hidden else ""})'
        return payload, 'Wi-Fi login', f'Wi-Fi: {ssid}', detail
    value = arguments[kind]
    if not isinstance(value, str):
        raise ValueError(f'"{kind}" must be text.')
    if kind == 'url':
        value = value.strip()
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value):
            value = 'https://' + value
        return value, 'URL', value, value
    return value, 'text', '', ''


def call(tool, arguments):
    if tool != TOOLS[0]['name']:
        return _error('Unknown QR tool.')
    if not isinstance(arguments, dict):
        return _error('Pass an object with "text", "url" or "wifi".')
    try:
        payload, kind, default_caption, detail = _build(arguments)
    except ValueError as error:
        return _error(str(error))
    if len(payload.encode('utf-8')) > MAX_BYTES:
        return _error(f'That is too long for a QR code here (max {MAX_BYTES} bytes). Shorten it or use a link.')
    ec = str(arguments.get('ec_level') or 'M').upper()
    if ec not in EC_LEVELS:
        return _error('ec_level must be L, M, Q or H.')
    caption = arguments.get('caption')
    title = arguments.get('title') or ''
    if caption is not None and not isinstance(caption, str) or not isinstance(title, str):
        return _error('caption and title must be text.')
    caption = (default_caption if caption is None else caption)[:80]
    title = title[:80]
    if kind == 'Wi-Fi login':     # never show the password, even if the caller put it in a caption/title
        secret = (arguments['wifi'].get('password') or '')
        if secret:
            caption = caption.replace(secret, '••••')
            title = title.replace(secret, '••••')
    try:
        qr = encode(payload, ec)
    except ValueError as error:
        return _error(str(error))
    n = len(qr['matrix'])
    summary = (f'QR code ({kind}) — version {qr["version"]} ({n}x{n} modules), error correction {ec}, '
               f'mask {qr["mask"]}, {qr["mode"]} mode, {len(payload)} characters.')
    if detail:
        summary += f' Content: {detail}.' if kind == 'Wi-Fi login' else f' Content: {detail[:200]}'
    return svgkit.image_result(summary, render_svg(qr['matrix'], title, caption))
