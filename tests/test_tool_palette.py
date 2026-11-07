import base64
import unittest

from builtin_tools import palette as p


def svg_of(result):
    images = [item for item in result['content'] if item['type'] == 'image']
    assert images and images[0]['mimeType'] == 'image/svg+xml'
    return base64.b64decode(images[0]['data']).decode()


class ParseTests(unittest.TestCase):
    def test_hex_forms(self):
        self.assertEqual(p.parse_color('#2ff3d0'), (47, 243, 208))
        self.assertEqual(p.parse_color('2FF3D0'), (47, 243, 208))
        self.assertEqual(p.parse_color('#abc'), (0xaa, 0xbb, 0xcc))
        self.assertEqual(p.parse_color('fff'), (255, 255, 255))

    def test_rgb_and_names(self):
        self.assertEqual(p.parse_color('rgb(47, 243, 208)'), (47, 243, 208))
        self.assertEqual(p.parse_color('rgb(100%, 0%, 0%)'), (255, 0, 0))
        self.assertEqual(p.parse_color('Coral'), (255, 127, 80))
        self.assertEqual(p.parse_color('teal'), (0, 128, 128))
        self.assertGreaterEqual(len(p.NAMES), 30)

    def test_bad_colours(self):
        for bad in ('#12', 'notacolour', 'rgb(300, 0, 0)', '#ggg', ''):
            with self.assertRaises(p.PaletteError):
                p.parse_color(bad)
        result = p.call('color_palette', {'color': 'blurple-ish'})
        self.assertTrue(result['isError'])
        self.assertIn('hex', result['content'][0]['text'])


class MathTests(unittest.TestCase):
    def test_complementary_of_red_is_cyan(self):
        colours = [c for c, role in p.generate((255, 0, 0), 'complementary', 3)]
        self.assertIn((255, 0, 0), colours)
        self.assertIn((0, 255, 255), colours)

    def test_triadic_and_tetradic_hues(self):
        colours = [c for c, _ in p.generate((255, 0, 0), 'triadic', 3)]
        self.assertEqual(colours, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        colours = [c for c, _ in p.generate((255, 0, 0), 'tetradic', 4)]
        self.assertEqual(colours, [(255, 0, 0), (128, 255, 0), (0, 255, 255), (127, 0, 255)])

    def test_contrast(self):
        self.assertAlmostEqual(p.contrast((255, 255, 255), (0, 0, 0)), 21.0, places=6)
        self.assertAlmostEqual(p.contrast((0x77, 0x77, 0x77), (255, 255, 255)), 4.48, places=2)
        info = p.describe((0x77, 0x77, 0x77))
        self.assertEqual(info['best'], 'black')
        self.assertEqual(p.describe((0, 0, 128))['best'], 'white')

    def test_scheme_counts_include_base(self):
        for scheme in p.SCHEMES:
            for count in range(3, 9):
                palette = p.generate((47, 243, 208), scheme, count)
                self.assertEqual(len(palette), count, (scheme, count))
                self.assertIn((47, 243, 208), [c for c, _ in palette], (scheme, count))
                self.assertEqual(sum(role == 'Base' for _, role in palette), 1, (scheme, count))

    def test_hsl(self):
        self.assertEqual(p.describe((255, 0, 0))['hsl'], (0, 100, 50))
        self.assertEqual(p.describe((0, 255, 255))['hsl'], (180, 100, 50))


class ToolTests(unittest.TestCase):
    def test_schema(self):
        tool = p.TOOLS[0]
        self.assertEqual(tool['name'], 'color_palette')
        self.assertLessEqual(len(tool['description']), 450)
        schema = tool['inputSchema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['required'], ['color'])
        self.assertEqual(set(schema['properties']['scheme']['enum']), set(p.SCHEMES))

    def test_result_and_svg(self):
        result = p.call('color_palette', {'color': '#2ff3d0', 'scheme': 'triadic', 'count': 6,
                                          'title': '<script>alert(1)</script> & "x"'})
        self.assertFalse(result.get('isError'))
        summary = result['content'][0]['text']
        self.assertIn('#2FF3D0', summary)
        self.assertEqual(summary.count('\n'), 6)
        svg = svg_of(result)
        self.assertTrue(svg.startswith('<svg'))
        self.assertNotIn('<script', svg.lower())
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;x&quot;', svg)
        self.assertIn('#2FF3D0', svg)

    def test_default_scheme_and_count(self):
        result = p.call('color_palette', {'color': 'red'})
        self.assertIn('Analogous', result['content'][0]['text'])
        self.assertEqual(result['content'][0]['text'].count('\n'), 5)

    def test_bad_arguments(self):
        for args in ({'color': '#fff', 'scheme': 'rainbow'}, {'color': '#fff', 'count': 2},
                     {'color': '#fff', 'count': 9}, {'color': '#fff', 'count': True}, {},
                     {'color': '#fff', 'extra': 1}, None, {'color': 'x' * 61}):
            result = p.call('color_palette', args)
            self.assertTrue(result.get('isError'), args)


if __name__ == '__main__':
    unittest.main()
