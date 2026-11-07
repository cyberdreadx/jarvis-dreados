import base64
import re
import unittest
import xml.etree.ElementTree as ET

from builtin_tools import scales


def names(root, scale):
    return ' '.join(n for n, _, _ in scales.spell(root, scale))


def svg_of(result):
    return base64.b64decode(result['content'][1]['data']).decode()


class SpellingTest(unittest.TestCase):
    def test_major_keys(self):
        self.assertEqual(names('C', 'major'), 'C D E F G A B')
        self.assertEqual(names('F', 'major'), 'F G A Bb C D E')
        self.assertEqual(names('D', 'major'), 'D E F# G A B C#')
        self.assertEqual(names('Bb', 'major'), 'Bb C D Eb F G A')
        self.assertEqual(names('F#', 'major'), 'F# G# A# B C# D# E#')
        self.assertEqual(names('Eb', 'major'), 'Eb F G Ab Bb C D')

    def test_minors(self):
        self.assertEqual(names('A', 'natural_minor'), 'A B C D E F G')
        self.assertEqual(names('E', 'harmonic_minor'), 'E F# G A B C D#')
        self.assertEqual(names('A', 'melodic_minor'), 'A B C D E F# G#')
        self.assertEqual(names('C', 'natural_minor'), 'C D Eb F G Ab Bb')

    def test_modes_of_c(self):
        self.assertEqual(names('D', 'dorian'), 'D E F G A B C')
        self.assertEqual(names('E', 'phrygian'), 'E F G A B C D')
        self.assertEqual(names('F', 'lydian'), 'F G A B C D E')
        self.assertEqual(names('G', 'mixolydian'), 'G A B C D E F')
        self.assertEqual(names('B', 'locrian'), 'B C D E F G A')
        self.assertEqual(names('C', 'dorian'), 'C D Eb F G A Bb')
        self.assertEqual(names('C', 'lydian'), 'C D E F# G A B')
        self.assertEqual(names('C', 'locrian'), 'C Db Eb F Gb Ab Bb')

    def test_pentatonic_blues_arpeggios(self):
        self.assertEqual(names('A', 'minor_pentatonic'), 'A C D E G')
        self.assertEqual(names('G', 'major_pentatonic'), 'G A B D E')
        self.assertEqual(names('A', 'blues'), 'A C D Eb E G')
        self.assertEqual(names('E', 'blues'), 'E G A Bb B D')
        self.assertEqual(names('C', 'whole_tone'), 'C D E F# G# Bb')
        self.assertEqual(names('G', 'dominant7_arpeggio'), 'G B D F')
        self.assertEqual(names('Bb', 'maj7_arpeggio'), 'Bb D F A')
        self.assertEqual(names('F#', 'm7_arpeggio'), 'F# A C# E')
        self.assertEqual(names('Db', 'major_arpeggio'), 'Db F Ab')
        self.assertEqual(names('C#', 'minor_arpeggio'), 'C# E G#')

    def test_chromatic(self):
        self.assertEqual(names('C', 'chromatic'), 'C C# D D# E F F# G G# A A# B')
        self.assertEqual(names('Bb', 'chromatic'), 'Bb B C Db D Eb E F Gb G Ab A')
        self.assertEqual(len(scales.spell('F', 'chromatic')), 12)

    def test_root_variants(self):
        self.assertEqual(names('f#', 'major'), names('F♯', 'major'))
        self.assertEqual(names('bb', 'major'), 'Bb C D Eb F G A')

    def test_summary_intervals(self):
        res = scales.call('draw_scale', {'root': 'A', 'scale': 'minor_pentatonic'})
        self.assertTrue(res['content'][0]['text'].startswith('A minor pentatonic: A C D E G (R b3 4 5 b7)'))
        res = scales.call('draw_scale', {'root': 'A', 'scale': 'blues', 'instrument': 'piano'})
        self.assertIn('(R b3 4 b5 5 b7)', res['content'][0]['text'])


class DrawingTest(unittest.TestCase):
    def test_tuning_positions(self):
        from chord_diagrams import TUNING
        pc = lambda s, f: (TUNING[s] + f) % 12
        self.assertEqual(pc(0, 5), 9)    # low E fret 5 = A
        self.assertEqual(pc(1, 7), 4)    # A string fret 7 = E
        self.assertEqual(pc(4, 1), 0)    # B string fret 1 = C
        self.assertEqual(pc(5, 12), 4)

    def _dots(self, svg):
        root = ET.fromstring(svg)
        ns = '{http://www.w3.org/2000/svg}'
        circles = [c for c in root.iter(ns + 'circle') if c.get('fill') in (scales.ROOT_COLOR, scales.NOTE_COLOR)]
        return root, circles

    def test_guitar_a_minor_pentatonic(self):
        res = scales.call('draw_scale', {'root': 'A', 'scale': 'minor_pentatonic', 'title': 'Pent <&> "x"'})
        svg = svg_of(res)
        root, circles = self._dots(svg)
        self.assertIn('Pent &lt;&amp;&gt; &quot;x&quot;', svg)
        # count expected notes in frets 0-12 on 6 strings, plus 5 legend dots
        from chord_diagrams import TUNING
        expected = sum(1 for s in range(6) for f in range(13) if (TUNING[s] + f) % 12 in {9, 0, 2, 4, 7})
        self.assertEqual(len(circles), expected + 5)
        # the low E string is drawn lowest: its fret-5 dot (A, root) is at the bottom string y
        roots = [c for c in circles if c.get('fill') == scales.ROOT_COLOR]
        self.assertTrue(roots)
        string_ys = sorted({float(l.get('y1')) for l in root.iter('{http://www.w3.org/2000/svg}line')
                            if l.get('y1') == l.get('y2')})
        texts = {(t.text, round(float(t.get('x'))), round(float(t.get('y')) - 4)) for t in root.iter('{http://www.w3.org/2000/svg}text')}
        low_e_y = round(string_ys[-1])
        fret5_x = [round(float(c.get('cx'))) for c in roots if round(float(c.get('cy'))) == low_e_y]
        self.assertTrue(any(('A', x, low_e_y) in texts for x in fret5_x))

    def test_guitar_window_and_piano(self):
        res = scales.call('draw_scale', {'root': 'G', 'scale': 'major', 'frets': {'from': 5, 'to': 9}})
        self.assertIn('frets 5-9', res['content'][0]['text'])
        ET.fromstring(svg_of(res))
        res = scales.call('draw_scale', {'root': 'D', 'scale': 'dorian', 'instrument': 'piano'})
        svg = svg_of(res)
        root = ET.fromstring(svg)
        keys = [r for r in root.iter('{http://www.w3.org/2000/svg}rect') if r.get('fill') in (scales.ROOT_COLOR, scales.NOTE_COLOR)]
        self.assertEqual(len(keys), 7 * 2 + 1)          # two octaves of 7 notes + the top root
        roots = [r for r in keys if r.get('fill') == scales.ROOT_COLOR]
        self.assertEqual(len(roots), 3)
        res = scales.call('draw_scale', {'root': 'F#', 'scale': 'major', 'instrument': 'piano'})
        keys = [r for r in ET.fromstring(svg_of(res)).iter('{http://www.w3.org/2000/svg}rect')
                if r.get('fill') == scales.ROOT_COLOR]
        self.assertEqual(len(keys), 3)
        self.assertIn('E#', svg_of(res))

    def test_every_scale_renders(self):
        for scale in scales.SCALES:
            for inst in ('guitar', 'piano'):
                res = scales.call('draw_scale', {'root': 'Eb', 'scale': scale, 'instrument': inst})
                self.assertNotIn('isError', res, (scale, inst))
                ET.fromstring(svg_of(res))


class ErrorTest(unittest.TestCase):
    def test_errors(self):
        bad = [{'root': 'H', 'scale': 'major'}, {'root': 'A', 'scale': 'bebop'}, {'scale': 'major'},
               {'root': 'A'}, {'root': 'A', 'scale': 'major', 'instrument': 'banjo'},
               {'root': 'A', 'scale': 'major', 'frets': {'from': 3, 'to': 4}},
               {'root': 'A', 'scale': 'major', 'frets': {'from': 13, 'to': 16}},
               {'root': 'A', 'scale': 'major', 'frets': {'from': 0, 'to': 20}},
               {'root': 'A', 'scale': 'major', 'frets': 'all'}, {'root': 5, 'scale': 'major'}]
        for args in bad:
            res = scales.call('draw_scale', args)
            self.assertTrue(res.get('isError'), args)
            self.assertTrue(res['content'][0]['text'])

    def test_schema(self):
        tool = scales.TOOLS[0]
        self.assertEqual(tool['name'], 'draw_scale')
        self.assertLessEqual(len(tool['description']), 450)
        self.assertFalse(tool['inputSchema']['additionalProperties'])
        self.assertEqual(set(tool['inputSchema']['properties']['scale']['enum']), set(scales.SCALES))


if __name__ == '__main__':
    unittest.main()
