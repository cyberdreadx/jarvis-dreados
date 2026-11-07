import base64
import random
import unittest
import xml.etree.ElementTree as ET

from builtin_tools import qrcode_tool as qr

ALIGNMENT_TABLE = {  # ISO/IEC 18004 Annex E, independent of the encoder's formula
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
    9: [6, 26, 46], 10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62],
    14: [6, 26, 46, 66], 15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78],
    18: [6, 30, 56, 82], 19: [6, 30, 58, 86], 20: [6, 34, 62, 90], 21: [6, 28, 50, 72, 94],
    22: [6, 26, 50, 74, 98], 23: [6, 30, 54, 78, 102], 24: [6, 28, 54, 80, 106], 25: [6, 32, 58, 84, 110],
    26: [6, 30, 58, 86, 114], 27: [6, 34, 62, 90, 118], 28: [6, 26, 50, 74, 98, 122],
    29: [6, 30, 54, 78, 102, 126], 30: [6, 26, 52, 78, 104, 130], 31: [6, 30, 56, 82, 108, 134],
    32: [6, 34, 60, 86, 112, 138], 33: [6, 30, 58, 86, 114, 142], 34: [6, 34, 62, 90, 118, 146],
    35: [6, 30, 54, 78, 102, 126, 150], 36: [6, 24, 50, 76, 102, 128, 154], 37: [6, 28, 54, 80, 106, 132, 158],
    38: [6, 32, 58, 84, 110, 136, 162], 39: [6, 26, 54, 82, 110, 138, 166], 40: [6, 30, 58, 86, 114, 142, 170],
}
# Data codeword capacities (L, M, Q, H) from the standard's Table 7 for a sample of versions.
DATA_CAPACITY = {1: (19, 16, 13, 9), 2: (34, 28, 22, 16), 3: (55, 44, 34, 26), 4: (80, 64, 48, 36),
                 5: (108, 86, 62, 46), 6: (136, 108, 76, 60), 7: (156, 124, 88, 66), 8: (194, 154, 110, 86),
                 9: (232, 182, 132, 100), 10: (274, 216, 154, 122), 40: (2956, 2334, 1666, 1276)}
# Total codewords per version (Table 1) for a sample.
TOTAL_CODEWORDS = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 10: 346, 14: 581, 20: 1085,
                   27: 1828, 40: 3706}

# ---------------- independent decoder ----------------
_EXP, _LOG = [0] * 512, [0] * 256
_v = 1
for _i in range(255):
    _EXP[_i], _LOG[_v] = _v, _i
    _v = (_v << 1) ^ (0x11D if _v & 0x80 else 0)
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def _syndromes(block, count):
    out = []
    for i in range(count):
        s = 0
        for c in block:      # Horner: highest-degree coefficient first
            s = _mul(s, _EXP[i]) ^ c
        out.append(s)
    return out


def _bch_format(ec_bits, mask):
    data = ec_bits << 3 | mask
    g, v = 0b10100110111, data << 10
    for shift in range(14, 9, -1):
        if v >> shift & 1:
            v ^= g << (shift - 10)
    return ((data << 10) | v) ^ 0b101010000010010


def _function_map(version):
    n = 4 * version + 17
    fn = [[False] * n for _ in range(n)]

    def box(x0, y0, w, h):
        for y in range(max(0, y0), min(n, y0 + h)):
            for x in range(max(0, x0), min(n, x0 + w)):
                fn[y][x] = True
    box(0, 0, 9, 9)
    box(n - 8, 0, 8, 9)
    box(0, n - 8, 9, 8)
    box(6, 0, 1, n)
    box(0, 6, n, 1)
    pos = ALIGNMENT_TABLE[version]
    for ay in pos:
        for ax in pos:
            if (ax <= 8 and ay <= 8) or (ax >= n - 9 and ay <= 8) or (ax <= 8 and ay >= n - 9):
                continue
            box(ax - 2, ay - 2, 5, 5)
    if version >= 7:
        box(n - 11, 0, 3, 6)
        box(0, n - 11, 6, 3)
    return fn


def decode(matrix):
    """Read a module matrix back to (text, version, ec, mask, mode). Raises AssertionError on damage."""
    n = len(matrix)
    version = (n - 17) // 4
    assert 4 * version + 17 == n and 1 <= version <= 40
    m = lambda x, y: matrix[y][x]
    # finder patterns
    for fx, fy in ((0, 0), (n - 7, 0), (0, n - 7)):
        for dy in range(7):
            for dx in range(7):
                d = max(abs(dx - 3), abs(dy - 3))
                assert m(fx + dx, fy + dy) == (0 if d == 2 else 1), 'finder pattern broken'
    for i in range(8, n - 8):
        assert m(6, i) == m(i, 6) == (1 if i % 2 == 0 else 0), 'timing pattern broken'
    assert m(8, n - 8) == 1, 'dark module missing'
    # format info, copy 1 (around the top-left finder) read MSB first per Figure 25
    coords = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    word1 = sum(m(x, y) << i for i, (x, y) in enumerate(coords))
    coords2 = [(n - 1 - i, 8) for i in range(8)] + [(8, n - 15 + i) for i in range(8, 15)]
    word2 = sum(m(x, y) << i for i, (x, y) in enumerate(coords2))
    assert word1 == word2, 'format copies differ'
    names = {1: 'L', 0: 'M', 3: 'Q', 2: 'H'}
    match = [(e, k) for e in range(4) for k in range(8) if _bch_format(e, k) == word1]
    assert len(match) == 1, 'invalid format info'
    ec, mask = names[match[0][0]], match[0][1]
    if version >= 7:
        bits = 0
        for i in range(18):
            a, b = n - 11 + i % 3, i // 3
            assert m(a, b) == m(b, a)
            bits |= m(a, b) << i
        assert bits >> 12 == version, 'version info wrong'
    fn = _function_map(version)
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (y // 2 + x // 3) % 2 == 0,
             lambda x, y: (x * y) % 2 + (x * y) % 3 == 0, lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0]
    bits = []
    x, upward = n - 1, True
    while x > 0:
        if x == 6:
            x -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for y in rows:
            for xx in (x, x - 1):
                if not fn[y][xx]:
                    bits.append(m(xx, y) ^ (1 if masks[mask](xx, y) else 0))
        upward = not upward
        x -= 2
    total = len(bits) // 8
    codewords = [int(''.join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(total)]
    # de-interleave using block structure
    nblocks, ecc = qr.NUM_BLOCKS[ec][version], qr.ECC_PER_BLOCK[ec][version]
    short = total // nblocks - ecc
    nlong = total % nblocks
    sizes = [short] * (nblocks - nlong) + [short + 1] * nlong
    blocks = [[] for _ in range(nblocks)]
    pos = 0
    for i in range(short + 1):
        for b in range(nblocks):
            if i < sizes[b]:
                blocks[b].append(codewords[pos])
                pos += 1
    for i in range(ecc):
        for b in range(nblocks):
            blocks[b].append(codewords[pos])
            pos += 1
    assert pos == total
    data = []
    for b in range(nblocks):
        assert _syndromes(blocks[b], ecc) == [0] * ecc, 'Reed-Solomon syndrome non-zero'
        data += blocks[b][:sizes[b]]
    stream = ''.join(f'{c:08b}' for c in data)
    p = 0

    def take(k):
        nonlocal p
        v = int(stream[p:p + k], 2)
        p += k
        return v
    mode_ind = take(4)
    mode = {1: 'numeric', 2: 'alphanumeric', 4: 'byte'}[mode_ind]
    cb = {'numeric': (10, 12, 14), 'alphanumeric': (9, 11, 13), 'byte': (8, 16, 16)}[mode][0 if version < 10 else 1 if version < 27 else 2]
    count = take(cb)
    alnum = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
    if mode == 'numeric':
        out = ''
        while len(out) < count:
            k = min(3, count - len(out))
            out += str(take({3: 10, 2: 7, 1: 4}[k])).zfill(k)
    elif mode == 'alphanumeric':
        out = ''
        while len(out) < count:
            if count - len(out) >= 2:
                v = take(11)
                out += alnum[v // 45] + alnum[v % 45]
            else:
                out += alnum[take(6)]
    else:
        out = bytes(take(8) for _ in range(count)).decode('utf-8')
    rest = stream[p:p + 4]
    assert set(rest) <= {'0'}, 'missing terminator'
    return out, version, ec, mask, mode


def _svg(result):
    return base64.b64decode(result['content'][1]['data']).decode()


class ReedSolomonTest(unittest.TestCase):
    def test_thonky_hello_world_1m(self):
        version, mode, words = qr.encode_data('HELLO WORLD', 'M')
        self.assertEqual((version, mode), (1, 'alphanumeric'))
        self.assertEqual(words, [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17])
        self.assertEqual(qr.rs_remainder(words, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])
        self.assertEqual(_syndromes(words + qr.rs_remainder(words, 10), 10), [0] * 10)

    def test_generator_polynomial_degree_7(self):
        # Thonky: alpha exponents 0 87 229 146 149 238 102 21
        self.assertEqual([qr.LOG[c] for c in qr.rs_generator(7)], [0, 87, 229, 146, 149, 238, 102, 21])


class StructureTest(unittest.TestCase):
    def test_format_info_table(self):
        self.assertEqual(f'{qr.format_bits("M", 0):015b}', '101010000010010')
        self.assertEqual(f'{qr.format_bits("L", 0):015b}', '111011111000100')
        self.assertEqual(f'{qr.format_bits("Q", 0):015b}', '011010101011111')
        self.assertEqual(f'{qr.format_bits("H", 0):015b}', '001011010001001')
        self.assertEqual(f'{qr.format_bits("L", 4):015b}', '110011000101111')
        self.assertEqual(f'{qr.format_bits("H", 7):015b}', '000100000111011')
        for ec in 'LMQH':
            for mask in range(8):
                self.assertEqual(qr.format_bits(ec, mask), _bch_format(qr.FORMAT_BITS[ec], mask))

    def test_version_info(self):
        self.assertEqual(f'{qr.version_bits(7):018b}', '000111110010010100')
        self.assertEqual(f'{qr.version_bits(8):018b}', '001000010110111100')
        self.assertEqual(f'{qr.version_bits(40):018b}', '101000110001101001')

    def test_alignment_and_capacity_tables(self):
        for v in range(1, 41):
            self.assertEqual(qr.alignment_positions(v), ALIGNMENT_TABLE[v], v)
        for v, caps in DATA_CAPACITY.items():
            self.assertEqual(tuple(qr.data_codewords(v, e) for e in 'LMQH'), caps, v)
        for v, total in TOTAL_CODEWORDS.items():
            self.assertEqual(qr.total_codewords(v), total, v)
        for v in range(1, 41):
            for e in 'LMQH':
                sizes, ecc = qr.block_layout(v, e)
                self.assertEqual(sum(sizes) + ecc * len(sizes), qr.total_codewords(v))
                self.assertLessEqual(max(sizes) - min(sizes), 1)

    def test_hello_world_1m_layout(self):
        res = qr.encode('HELLO WORLD', 'M')
        self.assertEqual((res['version'], len(res['matrix'])), (1, 21))
        self.assertEqual(decode(res['matrix'])[0], 'HELLO WORLD')


class RoundTripTest(unittest.TestCase):
    def check(self, text, ec, expect_mode=None):
        res = qr.encode(text, ec)
        out, version, dec_ec, mask, mode = decode(res['matrix'])
        self.assertEqual(out, text)
        self.assertEqual((version, dec_ec, mask, mode), (res['version'], ec, res['mask'], res['mode']))
        if expect_mode:
            self.assertEqual(mode, expect_mode)
        return version

    def test_modes_and_levels(self):
        samples = [('01234567', 'numeric'), ('8675309', 'numeric'), ('1', 'numeric'),
                   ('HELLO WORLD', 'alphanumeric'), ('AC-42 $%*+./:', 'alphanumeric'), ('A', 'alphanumeric'),
                   ('hello world', 'byte'), ('https://example.com/a?b=c', 'byte'),
                   ('GrÃ¼ÃŸe, ä¸–ç•Œ! ðŸŽ¸', 'byte'), ('WIFI:T:WPA;S:My\\;Net;P:p\\:w;;', 'byte')]
        for text, mode in samples:
            for ec in 'LMQH':
                self.check(text, ec, mode)

    def test_every_version_1_to_40_and_all_masks(self):
        rng = random.Random(1804)
        seen = set()
        alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789 Ã©Ã¼â‚¬æ¼¢'
        for ec in 'LMQH':
            for v in range(1, 41):
                cap = qr.data_codewords(v, ec) - 3
                n = max(1, min(qr.MAX_BYTES, cap))
                text = ''.join(rng.choice(alphabet) for _ in range(n))
                while len(text.encode()) > min(cap, qr.MAX_BYTES):
                    text = text[:-1]
                seen.add(self.check(text, ec))
        self.assertTrue(set(range(1, 30)) <= seen, sorted(seen))
        # forced masks
        for mask in range(8):
            for text in ('HELLO WORLD', '0123456789' * 9, 'mask test Ã¼nÃ¯code'):
                res = qr.encode(text, 'Q', mask=mask)
                self.assertEqual(decode(res['matrix'])[:4], (text, res['version'], 'Q', mask))

    def test_random_numeric_and_alphanumeric_large(self):
        rng = random.Random(7)
        for length in (40, 120, 300, 700, 1000):
            self.check(''.join(rng.choice('0123456789') for _ in range(length)), rng.choice('LMQH'), 'numeric')
            self.check(''.join(rng.choice(qr.ALPHANUMERIC) for _ in range(length)), rng.choice('LMQH'), 'alphanumeric')

    def test_smallest_version(self):
        self.assertEqual(qr.encode('A' * 25, 'L')['version'], 1)   # 1-L alnum capacity 25
        self.assertEqual(qr.encode('A' * 26, 'L')['version'], 2)
        self.assertEqual(qr.encode('1' * 41, 'L')['version'], 1)   # 1-L numeric capacity 41
        self.assertEqual(qr.encode('a' * 17, 'L')['version'], 1)   # 1-L byte capacity 17
        self.assertEqual(qr.encode('a' * 18, 'L')['version'], 2)
        self.assertEqual(qr.encode('a' * 14, 'M')['version'], 1)


class ToolTest(unittest.TestCase):
    def test_text_result_and_svg(self):
        res = qr.call('make_qr_code', {'text': 'hello <dreados> & "co"', 'title': 'T <x>', 'caption': 'c&d'})
        self.assertNotIn('isError', res)
        svg = _svg(res)
        ET.fromstring(svg)
        self.assertIn('T &lt;x&gt;', svg)
        self.assertIn('c&amp;d', svg)
        self.assertIn('crispEdges', svg)
        self.assertIn('#ffffff', svg)
        self.assertIn('version 2', res['content'][0]['text'])

    def test_url(self):
        res = qr.call('make_qr_code', {'url': 'example.com/x', 'ec_level': 'H'})
        self.assertIn('https://example.com/x', res['content'][0]['text'])
        self.assertIn('error correction H', res['content'][0]['text'])

    def test_wifi_payload_and_masking(self):
        args = {'wifi': {'ssid': 'Cafe;"Net"', 'password': 'pa:ss\\word,1', 'security': 'WPA', 'hidden': True},
                'caption': 'join with pa:ss\\word,1'}
        res = qr.call('make_qr_code', args)
        summary, svg = res['content'][0]['text'], _svg(res)
        self.assertNotIn('pa:ss', summary)
        self.assertNotIn('pa:ss', svg)
        payload = qr._build(args)[0]
        self.assertEqual(payload, 'WIFI:T:WPA;S:Cafe\\;\\"Net\\";P:pa\\:ss\\\\word\\,1;H:true;;')
        # decode the image matrix and confirm payload
        self.assertEqual(decode(qr.encode(payload, 'M')['matrix'])[0], payload)
        self.assertEqual(qr._build({'wifi': {'ssid': 'Open'}})[0], 'WIFI:T:nopass;S:Open;;')

    def test_errors(self):
        for args in ({}, {'text': 'a', 'url': 'b'}, {'text': 'x' * 1001}, {'text': 'Ã©' * 600},
                     {'text': 'a', 'ec_level': 'Z'}, {'wifi': {'ssid': ''}}, {'wifi': {'ssid': 'a', 'security': 'WPA'}},
                     {'wifi': 'nope'}, {'text': 5}):
            res = qr.call('make_qr_code', args)
            self.assertTrue(res.get('isError'), args)

    def test_schema(self):
        tool = qr.TOOLS[0]
        self.assertEqual(tool['name'], 'make_qr_code')
        self.assertLessEqual(len(tool['description']), 450)
        self.assertFalse(tool['inputSchema']['additionalProperties'])

    def test_speed(self):
        import time
        t = time.perf_counter()
        qr.call('make_qr_code', {'text': 'z' * 1000, 'ec_level': 'H'})
        self.assertLess(time.perf_counter() - t, 3.0)


if __name__ == '__main__':
    unittest.main()
