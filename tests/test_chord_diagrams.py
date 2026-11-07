import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chord_diagrams as c
import mcp_client
import media_library


def shape(name, style='open'):
    return ''.join(str(f) for f in c.voice(name, style))


class TheoryTests(unittest.TestCase):
    def test_open_chords_match_the_standard_shapes(self):
        expected = {'C': 'x32010', 'Am': 'x02210', 'E': '022100', 'D': 'xx0232', 'Em': '022000', 'A': 'x02220',
                    'Dm': 'xx0231', 'F': '133211', 'Dm7': 'xx0211', 'G7': '320001', 'Cmaj7': 'x32000',
                    'A7': 'x02020', 'E7': '020100', 'C/E': '032010'}
        for name, frets in expected.items():
            with self.subTest(chord=name):
                self.assertEqual(shape(name), frets)
        self.assertIn(shape('G'), ('320003', '320033'))

    def test_movable_jazz_shapes(self):
        self.assertEqual(shape('Dm7', 'movable'), 'x5x565')
        self.assertEqual(shape('F#m7b5', 'movable'), '2x221x')
        self.assertIn(shape('Cmaj7', 'movable'), ('x3x453', 'x35453', 'x3545x'))
        self.assertTrue(all(f != 0 for f in c.voice('G7', 'movable')))  # no open strings

    def test_every_shape_contains_exactly_the_chord_tones_with_the_right_bass(self):
        for name in ('Dm7', 'G7', 'Cmaj7', 'Bbmaj7', 'F#m7b5', 'Ebdim7', 'Aaug', 'Dsus4', 'E9', 'C/G', 'Am/C'):
            for style in ('open', 'movable'):
                with self.subTest(chord=name, style=style):
                    _, bass, pcs, required = c.parse(name)
                    frets = c.voice(name, style)
                    sounded = [(s, f) for s, f in enumerate(frets) if f != 'x']
                    notes = {(c.TUNING[s] + f) % 12 for s, f in sounded}
                    self.assertTrue(required <= notes <= pcs)
                    self.assertEqual((c.TUNING[sounded[0][0]] + sounded[0][1]) % 12, bass)
                    fretted = [f for f in frets if isinstance(f, int) and f > 0]
                    self.assertLessEqual(max(fretted) - min(fretted) if fretted else 0, 3)
                    self.assertLessEqual(max(c._fingers(frets)[0]), 4)

    def test_barre_never_lies_across_a_muted_string(self):
        self.assertIsNone(c._fingers([3, 'x', 3, 4, 3, 'x'])[1])
        self.assertEqual(c._fingers([1, 3, 3, 2, 1, 1])[1], 1)

    def test_bad_names_explain_themselves(self):
        with self.assertRaisesRegex(ValueError, 'not a chord name'):
            c.parse('H7')
        with self.assertRaisesRegex(ValueError, "Can't read \"whatever\""):
            c.parse('Cwhatever')

    def test_extended_and_altered_chord_symbols(self):
        def tones(name):
            root, _, pcs, req = c.parse(name)
            return sorted((p - root) % 12 for p in pcs), sorted((p - root) % 12 for p in req)
        self.assertEqual(tones('G7#11'), ([0, 4, 6, 7, 10], [0, 4, 6, 10]))
        self.assertEqual(tones('Cmaj9')[1], [0, 2, 4, 11])
        self.assertEqual(tones('A13')[1], [0, 4, 9, 10])          # 13 chords skip the 11th
        self.assertEqual(tones('Bb6/9')[1], [0, 2, 4, 9])
        self.assertEqual(tones('C7(b9,#11)')[1], [0, 1, 4, 6, 10])
        self.assertEqual(tones('D11')[1], [0, 5, 10])              # 11th replaces the major 3rd
        self.assertEqual(tones('Cø'), tones('Cm7b5'))
        self.assertEqual(tones('CΔ7'), tones('Cmaj7'))
        self.assertEqual(tones('Cmaj'), tones('C'))
        for name in ('Cmaj9', 'Am9', 'G7#11', 'Fm6', 'Dm9', 'Emaj7', 'E7alt', 'A13', 'F#m11', 'G9sus4', 'Cm13'):
            for style in ('open', 'movable'):
                with self.subTest(chord=name, style=style):
                    _, bass, pcs, required = c.parse(name)
                    frets = c.voice(name, style)
                    notes = {(c.TUNING[s] + f) % 12 for s, f in enumerate(frets) if f != 'x'}
                    self.assertTrue(required <= notes <= pcs)

    def test_one_bad_chord_does_not_sink_the_batch(self):
        out = c.call('draw_chord_diagrams', {'chords': ['Cmaj9', 'Cfoo', 'G7#11']})
        self.assertFalse(out.get('isError'))
        self.assertIn('Not drawn', out['content'][0]['text'])
        self.assertIn('G7#11', base64.b64decode(out['content'][1]['data']).decode())


class ToolTests(unittest.TestCase):
    def test_tool_returns_text_and_svg(self):
        out = c.call('draw_chord_diagrams', {'chords': ['Dm7', 'G7', 'Cmaj7'], 'style': 'movable', 'title': 'ii-V-I'})
        self.assertFalse(out.get('isError'))
        self.assertIn('Dm7: x 5 x 5 6 5', out['content'][0]['text'])
        image = out['content'][1]
        self.assertEqual(image['mimeType'], 'image/svg+xml')
        svg = base64.b64decode(image['data']).decode()
        self.assertTrue(svg.startswith('<svg') and '<script' not in svg)
        self.assertIn('Cmaj7', svg)

    def test_explicit_shapes_and_errors(self):
        out = c.call('draw_chord_diagrams', {'chords': ['Dm9=x5355x', 'X=x-10-x-10-11-10']})
        self.assertIn('Dm9: x 5 3 5 5 x', out['content'][0]['text'])
        self.assertIn('X: x 10 x 10 11 10', out['content'][0]['text'])
        self.assertTrue(c.call('draw_chord_diagrams', {'chords': ['Q7']})['isError'])
        self.assertTrue(c.call('draw_chord_diagrams', {'chords': []})['isError'])
        self.assertTrue(c.call('draw_chord_diagrams', {'chords': ['C=x32']})['isError'])

    def test_names_are_escaped_in_svg(self):
        svg = base64.b64decode(c.call('draw_chord_diagrams', {'chords': ['<b>=x32010']})['content'][1]['data']).decode()
        self.assertNotIn('<b>', svg)


class IntegrationTests(unittest.TestCase):
    def test_builtin_service_is_always_connected_and_callable(self):
        conns = mcp_client.public_connections()
        builtin = next(x for x in conns if x['id'] == 'dreados-tools')
        self.assertEqual(builtin['status'], 'connected')
        result = mcp_client.call({'id': 'dreados-tools', 'tool': 'draw_chord_diagrams', 'arguments': {'chords': ['C']}})
        self.assertEqual(result['connection'], 'DreadOS Tools')
        self.assertEqual(mcp_client.connect('dreados-tools')['connections'][-1]['id'], 'dreados-tools')
        with self.assertRaisesRegex(mcp_client.MCPError, 'built in'):
            mcp_client.remove('dreados-tools')
        with self.assertRaises(mcp_client.MCPError):
            mcp_client.call({'id': 'dreados-tools', 'tool': 'rm_rf', 'arguments': {}})

    def test_media_library_keeps_the_svg(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(media_library, 'DB', Path(tmp) / 'media.sqlite3'):
            call = {'tool': 'draw_chord_diagrams', 'arguments': {'chords': ['Dm7', 'G7'], 'title': 'Jazz'}}
            item = media_library.capture(call, mcp_client.call({'id': 'dreados-tools', **call}))
            self.assertEqual(item['status'], 'complete')
            self.assertTrue(item['assets'][0]['url'].startswith('data:image/svg+xml;base64,'))
            self.assertEqual(item['prompt'], 'Jazz: Dm7, G7')


if __name__ == '__main__':
    unittest.main()
