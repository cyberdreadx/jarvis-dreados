import base64
import time
import unittest
import xml.etree.ElementTree as ET

from builtin_tools import charts

SVG_NS = '{http://www.w3.org/2000/svg}'


def svg_of(result):
    return base64.b64decode(result['content'][1]['data']).decode()


def error_text(result):
    assert result.get('isError'), result
    return result['content'][0]['text']


class NiceTicksTests(unittest.TestCase):
    def test_simple_range(self):
        self.assertEqual(charts.nice_ticks(0, 95), [0, 20, 40, 60, 80, 100])

    def test_steps_are_1_2_5(self):
        for lo, hi in ((0, 1), (3, 17), (-42, 87), (0.001, 0.0093), (12500, 31200), (-1e6, 1e6), (7, 7)):
            ticks = charts.nice_ticks(lo, hi)
            self.assertLessEqual(ticks[0], min(lo, hi))
            self.assertGreaterEqual(ticks[-1], max(lo, hi))
            step = ticks[1] - ticks[0]
            mantissa = step / 10 ** __import__('math').floor(__import__('math').log10(step))
            self.assertTrue(any(abs(mantissa - m) < 1e-6 for m in (1, 2, 5, 10)), (lo, hi, ticks))
            self.assertLessEqual(len(ticks), 12)

    def test_include_zero_and_negatives(self):
        ticks = charts.nice_ticks(12, 31, include_zero=True)
        self.assertEqual(ticks[0], 0)
        ticks = charts.nice_ticks(-10, 18)
        self.assertIn(0, ticks)
        self.assertEqual((ticks[0], ticks[-1]), (-10, 20))

    def test_nice_step(self):
        self.assertEqual(charts.nice_step(19), 20)
        self.assertEqual(charts.nice_step(0.3), 0.5)
        self.assertEqual(charts.nice_step(6), 10)

    def test_number_formatting(self):
        self.assertEqual(charts.fmt_value(12500, '$'), '$12,500')
        self.assertEqual(charts.fmt_value(-1234.5, '$'), '-$1,234.5')
        self.assertEqual(charts.fmt_value(42, '%'), '42%')
        self.assertEqual(charts.fmt_value(3.5, 'kg'), '3.5 kg')
        self.assertEqual(charts.fmt_value(2500000), '2.5M')
        self.assertEqual(charts.fmt_tick(20000, 10000, 40000, '$'), '$20k')
        self.assertEqual(charts.fmt_tick(1500000, 500000, 2000000), '1.5M')
        self.assertEqual(charts.fmt_tick(2500, 500, 5000), '2,500')


class ValidationTests(unittest.TestCase):
    def call(self, **args):
        return charts.call('draw_chart', args)

    def test_length_mismatch(self):
        msg = error_text(self.call(type='bar', labels=['a', 'b'], series=[{'name': 's', 'values': [1, 2, 3]}]))
        self.assertIn('must match', msg)

    def test_bad_type_and_numbers(self):
        self.assertIn('type', error_text(self.call(type='radar', labels=['a'], series=[{'values': [1]}])))
        self.assertIn('number', error_text(self.call(type='bar', labels=['a'], series=[{'values': ['abc']}])))
        self.assertIn('finite', error_text(self.call(type='bar', labels=['a'], series=[{'values': [float('nan')]}])))
        self.assertIn('finite', error_text(self.call(type='line', labels=['a'], series=[{'values': [float('inf')]}])))
        self.assertIn('true/false', error_text(self.call(type='bar', labels=['a'], series=[{'values': [True]}])))

    def test_pie_rules(self):
        self.assertIn('negative', error_text(self.call(type='pie', labels=['a', 'b'], series=[{'values': [1, -1]}])))
        self.assertIn('more than zero', error_text(self.call(type='donut', labels=['a', 'b'], series=[{'values': [0, 0]}])))
        self.assertIn('one series', error_text(self.call(type='pie', labels=['a'], series=[{'values': [1]}, {'values': [2]}])))

    def test_scatter_needs_pairs(self):
        self.assertIn('[x, y]', error_text(self.call(type='scatter', series=[{'values': [1, 2]}])))
        self.assertIn('scatter', error_text(self.call(type='bar', labels=['a'], series=[{'values': [[1, 2]]}])))

    def test_size_limits(self):
        self.assertIn('limit', error_text(self.call(type='bar', labels=[str(i) for i in range(51)], series=[{'values': [1] * 51}])))
        self.assertIn('limit', error_text(self.call(type='line', series=[{'values': [1] * 201}])))
        self.assertIn('limit', error_text(self.call(type='line', labels=['a'], series=[{'values': [1]}] * 9)))
        self.assertIn('too long', error_text(self.call(type='bar', title='x' * 121, labels=['a'], series=[{'values': [1]}])))
        self.assertIn('Unknown field', error_text(self.call(type='bar', labels=['a'], series=[{'values': [1]}], colour='red')))

    def test_garbage_never_raises(self):
        for args in (None, [], 'bar', {'type': 'bar'}, {'type': 'bar', 'series': 'x'}, {'type': 'bar', 'series': [5]},
                     {'type': 'pie', 'series': [{'values': []}]}, {'type': 'bar', 'labels': 'abc', 'series': [{'values': [1]}]}):
            result = charts.call('draw_chart', args)
            self.assertTrue(result.get('isError'), args)

    def test_unknown_tool(self):
        self.assertTrue(charts.call('nope', {}).get('isError'))


SAMPLES = {
    'bar': {'labels': ['Jan', 'Feb', 'Mar'], 'series': [{'name': 'Revenue', 'values': [12500, 14200, -3100]}], 'unit': '$'},
    'horizontal_bar': {'labels': ['A', 'B', 'C'], 'series': [{'name': 'x', 'values': [5, -3, 12]}, {'name': 'y', 'values': [1, 2, 3]}]},
    'stacked_bar': {'labels': ['2020', '2021'], 'series': [{'name': 'Coal', 'values': [40, 36]}, {'name': 'Gas', 'values': [-5, 31]}]},
    'line': {'labels': ['Q1', 'Q2', 'Q3', 'Q4'], 'series': [{'name': 'N', 'values': [3, -4, 8, 1]}, {'name': 'S', 'values': [1, 2, 3, 4]}]},
    'area': {'labels': ['a', 'b', 'c'], 'series': [{'name': 'DAU', 'values': [1200, 1500, 1100]}]},
    'pie': {'labels': ['Search', 'Direct', 'Tiny'], 'series': [{'values': [70, 29, 1]}]},
    'donut': {'labels': ['Rent', 'Food'], 'series': [{'values': [1400, 0]}], 'unit': '$'},
    'scatter': {'labels': ['p', 'q', 'r'], 'series': [{'name': 'pts', 'values': [[1, 2], [3, 4.5], [-2, 7]]}]},
}


class RenderTests(unittest.TestCase):
    def test_every_type_renders_well_formed_svg(self):
        for kind, args in SAMPLES.items():
            with self.subTest(kind=kind):
                result = charts.call('draw_chart', dict(args, type=kind, title=f'{kind} chart', x_label='X', y_label='Y'))
                self.assertFalse(result.get('isError'), result)
                self.assertIn(kind.replace('_', ' ').capitalize(), result['content'][0]['text'])
                root = ET.fromstring(svg_of(result))
                self.assertEqual(root.tag, SVG_NS + 'svg')
                self.assertGreaterEqual(int(root.get('width')), 700)
                self.assertTrue(list(root.iter(SVG_NS + 'text')))

    def test_summary_has_min_max_total(self):
        result = charts.call('draw_chart', dict(SAMPLES['bar'], type='bar'))
        text = result['content'][0]['text']
        self.assertIn('min -$3,100 (Mar)', text)
        self.assertIn('max $14,200 (Feb)', text)
        self.assertIn('total $23,600', text)

    def test_text_is_escaped(self):
        evil = '<script>alert(1)</script>'
        result = charts.call('draw_chart', {'type': 'bar', 'title': evil, 'labels': [evil, 'b&c'], 'x_label': evil,
                                            'y_label': evil, 'unit': '<b>',
                                            'series': [{'name': evil, 'values': [1, 2]}, {'name': 'x"y', 'values': [3, 4]}]})
        svg = svg_of(result)
        self.assertNotIn('<script', svg)
        self.assertNotIn('<b>', svg)
        self.assertIn('&lt;script&gt;', svg)
        ET.fromstring(svg)
        for kind in ('pie', 'scatter', 'horizontal_bar'):
            args = {'type': kind, 'title': evil, 'labels': [evil]}
            args['series'] = [{'name': evil, 'values': [[1, 2]] if kind == 'scatter' else [5]}]
            svg = svg_of(charts.call('draw_chart', args))
            self.assertNotIn('<script', svg)
            ET.fromstring(svg)

    def test_many_values_are_fast_and_bounded(self):
        labels = [f'Category number {i}' for i in range(50)]
        series = [{'name': f's{k}', 'values': [(i * 37 % 23 - 6) * 1000.5 for i in range(50)]} for k in range(8)]
        start = time.perf_counter()
        for kind in ('bar', 'stacked_bar', 'horizontal_bar', 'line', 'area'):
            result = charts.call('draw_chart', {'type': kind, 'labels': labels, 'series': series, 'show_values': True})
            ET.fromstring(svg_of(result))
        big_scatter = [{'values': [[i, (i * 7) % 13] for i in range(200)]} for _ in range(8)]
        ET.fromstring(svg_of(charts.call('draw_chart', {'type': 'scatter', 'series': big_scatter})))
        self.assertLess(time.perf_counter() - start, 1.5)

    def test_pie_with_many_slices_and_single_slice(self):
        result = charts.call('draw_chart', {'type': 'pie', 'labels': [f'i{i}' for i in range(50)],
                                            'series': [{'values': list(range(1, 51))}]})
        ET.fromstring(svg_of(result))
        result = charts.call('draw_chart', {'type': 'donut', 'labels': ['all'], 'series': [{'values': [5]}]})
        self.assertIn('<circle', svg_of(result))

    def test_labels_optional_and_numeric(self):
        result = charts.call('draw_chart', {'type': 'line', 'series': [{'values': [1, 2, 3]}]})
        self.assertFalse(result.get('isError'))
        result = charts.call('draw_chart', {'type': 'bar', 'labels': [2024, 2025], 'series': [{'values': ['1,200', 3]}]})
        self.assertFalse(result.get('isError'), result)

    def test_tool_schema(self):
        tool = charts.TOOLS[0]
        self.assertEqual(tool['name'], 'draw_chart')
        self.assertLessEqual(len(tool['description']), 450)
        self.assertFalse(tool['inputSchema']['additionalProperties'])


if __name__ == '__main__':
    unittest.main()
