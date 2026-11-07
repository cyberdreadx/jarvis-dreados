import base64
import re
import time
import unittest
import xml.etree.ElementTree as ET

from builtin_tools import flowchart

SVG_NS = '{http://www.w3.org/2000/svg}'


def svg_of(result):
    return base64.b64decode(result['content'][1]['data']).decode()


def error_text(result):
    assert result.get('isError'), result
    return result['content'][0]['text']


def chain(*ids, direction='TB'):
    return {'direction': direction, 'nodes': [{'id': i, 'label': f'Step {i}'} for i in ids],
            'edges': [{'from': a, 'to': b} for a, b in zip(ids, ids[1:])]}


def layers_of(args):
    lay = flowchart.layout(flowchart.validate(args))
    return {n['id']: n['layer'] for n in lay['nodes']}, lay


LOGIN = {'title': 'Login', 'nodes': [
    {'id': 'start', 'label': 'Start', 'shape': 'ellipse'},
    {'id': 'creds', 'label': 'Enter email and password', 'shape': 'parallelogram'},
    {'id': 'ok', 'label': 'Credentials valid?', 'shape': 'diamond'},
    {'id': 'home', 'label': 'Dashboard', 'shape': 'round'},
    {'id': 'end', 'label': 'End', 'shape': 'ellipse'}],
    'edges': [{'from': 'start', 'to': 'creds'}, {'from': 'creds', 'to': 'ok'},
              {'from': 'ok', 'to': 'home', 'label': 'Yes'}, {'from': 'ok', 'to': 'creds', 'label': 'No, retry'},
              {'from': 'home', 'to': 'end'}, {'from': 'home', 'to': 'home', 'label': 'refresh'}]}


class LayoutTests(unittest.TestCase):
    def test_chain_layers_in_order(self):
        layers, _ = layers_of(chain('a', 'b', 'c', 'd'))
        self.assertEqual(layers, {'a': 0, 'b': 1, 'c': 2, 'd': 3})

    def test_longest_path_layering(self):
        args = chain('a', 'b', 'c')
        args['edges'].append({'from': 'a', 'to': 'c'})
        layers, lay = layers_of(args)
        self.assertEqual(layers['c'], 2)
        # the long edge a->c gets routed through a dummy (path with a straight segment)
        self.assertTrue(any(' L' in r['d'] for r in lay['routes']))

    def test_cycle_is_broken_and_drawn(self):
        args = chain('a', 'b', 'c')
        args['edges'].append({'from': 'c', 'to': 'a', 'label': 'again'})
        layers, lay = layers_of(args)
        self.assertEqual(layers, {'a': 0, 'b': 1, 'c': 2})
        kinds = sorted(e['kind'] for e in lay['edges'])
        self.assertEqual(kinds, ['back', 'forward', 'forward'])
        result = flowchart.call('draw_flowchart', args)
        self.assertIn('Loops: Step c -> Step a (again)', result['content'][0]['text'])
        ET.fromstring(svg_of(result))

    def test_tb_nodes_go_down_lr_nodes_go_right(self):
        _, lay = layers_of(chain('a', 'b', 'c'))
        ys = [n['y'] for n in lay['nodes']]
        self.assertEqual(ys, sorted(ys))
        self.assertLess(ys[0], ys[1])
        _, lay = layers_of(chain('a', 'b', 'c', direction='LR'))
        xs = [n['x'] for n in lay['nodes']]
        self.assertLess(xs[0], xs[1])
        self.assertLess(xs[1], xs[2])

    def test_nodes_in_a_layer_do_not_overlap(self):
        args = {'nodes': [{'id': 'r', 'label': 'Root'}] + [{'id': f'c{i}', 'label': f'A fairly long child label {i}'} for i in range(6)],
                'edges': [{'from': 'r', 'to': f'c{i}'} for i in range(6)]}
        _, lay = layers_of(args)
        kids = sorted((n for n in lay['nodes'] if n['id'] != 'r'), key=lambda n: n['x'])
        for a, b in zip(kids, kids[1:]):
            self.assertLessEqual(a['x'] + a['w'] / 2, b['x'] - b['w'] / 2)

    def test_crossing_reduction_untangles_simple_case(self):
        # a1->b2, a2->b1 would cross if b kept input order
        args = {'nodes': [{'id': x, 'label': x} for x in ('top', 'a1', 'a2', 'b1', 'b2')],
                'edges': [{'from': 'top', 'to': 'a1'}, {'from': 'top', 'to': 'a2'},
                          {'from': 'a1', 'to': 'b2'}, {'from': 'a2', 'to': 'b1'}]}
        _, lay = layers_of(args)
        pos = {n['id']: n['x'] for n in lay['nodes']}
        self.assertEqual(pos['a1'] < pos['a2'], pos['b2'] < pos['b1'])

    def test_wrap_and_decision_size(self):
        lines = flowchart.wrap('Check whether the uploaded file is a valid image', 16)
        self.assertTrue(all(len(line) <= 16 for line in lines))
        self.assertGreater(len(lines), 1)
        node = {'label': 'Is the payment authorised by the bank?', 'shape': 'diamond'}
        flowchart._size_node(node, 'TB')
        widest = max(flowchart.text_width(line, flowchart.FONT_SIZE) for line in node['lines'])
        text_h = len(node['lines']) * flowchart.LINE_H
        # the text block must fit inside the diamond: |x|/a + |y|/b <= 1 at its corners
        self.assertLessEqual(widest / node['w'] + text_h / node['h'], 1.0)

    def test_disconnected_components_side_by_side(self):
        args = {'nodes': [{'id': x, 'label': x} for x in 'abcd'],
                'edges': [{'from': 'a', 'to': 'b'}, {'from': 'c', 'to': 'd'}]}
        _, lay = layers_of(args)
        pos = {n['id']: n for n in lay['nodes']}
        self.assertLess(pos['a']['x'] + pos['a']['w'] / 2, pos['c']['x'] - pos['c']['w'] / 2)
        ET.fromstring(svg_of(flowchart.call('draw_flowchart', args)))


class ValidationTests(unittest.TestCase):
    def call(self, args):
        return flowchart.call('draw_flowchart', args)

    def test_unknown_id(self):
        msg = error_text(self.call({'nodes': [{'id': 'a', 'label': 'A'}], 'edges': [{'from': 'a', 'to': 'zzz'}]}))
        self.assertIn('zzz', msg)
        self.assertIn('unknown node id', msg)

    def test_duplicate_id(self):
        msg = error_text(self.call({'nodes': [{'id': 'a', 'label': 'A'}, {'id': 'a', 'label': 'B'}], 'edges': []}))
        self.assertIn('Duplicate', msg)

    def test_bad_shape_and_direction(self):
        self.assertIn('shape', error_text(self.call({'nodes': [{'id': 'a', 'label': 'A', 'shape': 'star'}], 'edges': []})))
        self.assertIn('direction', error_text(self.call({'nodes': [{'id': 'a', 'label': 'A'}], 'edges': [], 'direction': 'XY'})))

    def test_size_limits(self):
        nodes = [{'id': f'n{i}', 'label': 'x'} for i in range(41)]
        self.assertIn('limit', error_text(self.call({'nodes': nodes, 'edges': []})))
        nodes = nodes[:2]
        edges = [{'from': 'n0', 'to': 'n1'}] * 81
        self.assertIn('limit', error_text(self.call({'nodes': nodes, 'edges': edges})))
        self.assertIn('too long', error_text(self.call({'nodes': [{'id': 'a', 'label': 'x' * 81}], 'edges': []})))
        self.assertIn('too long', error_text(self.call({'nodes': [{'id': 'a' * 41, 'label': 'x'}], 'edges': []})))

    def test_garbage_never_raises(self):
        for args in (None, [], 'x', {}, {'nodes': []}, {'nodes': 'a'}, {'nodes': [5]}, {'nodes': [{'label': 'no id'}]},
                     {'nodes': [{'id': 'a'}], 'edges': 'a->b'}, {'nodes': [{'id': 'a'}], 'edges': [{'from': 'a'}]},
                     {'nodes': [{'id': 'a', 'label': 'A', 'color': 'red'}], 'edges': []}):
            self.assertTrue(self.call(args).get('isError'), args)

    def test_unknown_tool(self):
        self.assertTrue(flowchart.call('draw_chart', {}).get('isError'))


class RenderTests(unittest.TestCase):
    def test_login_flow_renders(self):
        result = flowchart.call('draw_flowchart', LOGIN)
        self.assertFalse(result.get('isError'), result)
        text = result['content'][0]['text']
        self.assertIn('1. Start; 2. Enter email and password; 3. Credentials valid?', text)
        self.assertIn('Loops:', text)
        root = ET.fromstring(svg_of(result))
        self.assertEqual(root.tag, SVG_NS + 'svg')
        self.assertTrue(root.findall(f'.//{SVG_NS}marker'))
        self.assertTrue(root.findall(f'.//{SVG_NS}polygon'))  # diamond / parallelogram
        self.assertTrue(root.findall(f'.//{SVG_NS}ellipse'))
        paths = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
        self.assertEqual(len(paths), len(LOGIN['edges']))

    def test_forward_arrows_end_on_node_border(self):
        result = flowchart.call('draw_flowchart', chain('a', 'b'))
        svg = svg_of(result)
        _, lay = layers_of(chain('a', 'b'))
        b = next(n for n in lay['nodes'] if n['id'] == 'b')
        d = next(r['d'] for r in lay['routes'])
        end_x, end_y = map(float, re.findall(r'(-?[\d.]+),(-?[\d.]+)$', d)[0])
        self.assertAlmostEqual(end_y, b['y'] - b['h'] / 2, delta=0.2)
        self.assertAlmostEqual(end_x, b['x'], delta=0.2)
        ET.fromstring(svg)

    def test_lr_and_self_loop(self):
        args = dict(LOGIN, direction='LR')
        root = ET.fromstring(svg_of(flowchart.call('draw_flowchart', args)))
        self.assertGreater(int(root.get('width')), int(root.get('height')))

    def test_text_is_escaped(self):
        evil = '<script>alert(1)</script>'
        args = {'title': evil, 'nodes': [{'id': '<a>', 'label': evil}, {'id': 'b&', 'label': 'x "y" & z'}],
                'edges': [{'from': '<a>', 'to': 'b&', 'label': evil}]}
        svg = svg_of(flowchart.call('draw_flowchart', args))
        self.assertNotIn('<script', svg)
        self.assertIn('&lt;script&gt;', svg)
        ET.fromstring(svg)

    def test_max_size_is_fast(self):
        nodes = [{'id': f'n{i}', 'label': f'Step {i} with a label long enough to wrap onto lines',
                  'shape': flowchart.SHAPES[i % 5]} for i in range(40)]
        edges = [{'from': f'n{i}', 'to': f'n{(i * 7 + 3) % 40}', 'label': 'go'} for i in range(40)]
        edges += [{'from': f'n{i}', 'to': f'n{(i * 11 + 5) % 40}'} for i in range(40)]
        for direction in ('TB', 'LR'):
            start = time.perf_counter()
            result = flowchart.call('draw_flowchart', {'nodes': nodes, 'edges': edges, 'direction': direction})
            self.assertLess(time.perf_counter() - start, 0.5)
            self.assertFalse(result.get('isError'), result)
            ET.fromstring(svg_of(result))

    def test_tool_schema(self):
        tool = flowchart.TOOLS[0]
        self.assertEqual(tool['name'], 'draw_flowchart')
        self.assertLessEqual(len(tool['description']), 450)
        self.assertFalse(tool['inputSchema']['additionalProperties'])


if __name__ == '__main__':
    unittest.main()
