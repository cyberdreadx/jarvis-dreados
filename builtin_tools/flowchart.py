"""draw_flowchart: layered (Sugiyama-style) flowchart layout drawn as DreadOS-styled SVG.

Steps: break cycles with a DFS (back edges are drawn curving around the side), longest-path
layering, dummy vertices for long edges, barycentric crossing reduction, then coordinate
assignment by weighted isotonic regression (keeps order, pulls nodes toward their neighbours).
Pure standard library, deterministic, all user text escaped with svgkit.esc.
"""
import math

from . import svgkit
from .svgkit import COLORS, esc

MAX_NODES = 40
MAX_EDGES = 80
SHAPES = ('box', 'round', 'diamond', 'ellipse', 'parallelogram')
SHAPE_ALIASES = {
    'rect': 'box', 'rectangle': 'box', 'process': 'box', 'square': 'box', 'step': 'box',
    'rounded': 'round', 'roundrect': 'round', 'rounded_box': 'round', 'pill': 'round',
    'decision': 'diamond', 'rhombus': 'diamond', 'condition': 'diamond', 'question': 'diamond',
    'oval': 'ellipse', 'circle': 'ellipse', 'start': 'ellipse', 'end': 'ellipse', 'terminal': 'ellipse',
    'terminator': 'ellipse', 'stop': 'ellipse',
    'io': 'parallelogram', 'input': 'parallelogram', 'output': 'parallelogram', 'data': 'parallelogram',
}
STROKE = {'box': '#2ff3d0', 'round': '#5fe8ff', 'diamond': '#ff9a3c', 'ellipse': '#8a7dff', 'parallelogram': '#ff3bd4'}
FILL = {'box': '#111a33', 'round': '#111a33', 'diamond': '#1d1a2a', 'ellipse': '#17163a', 'parallelogram': '#1c1433'}
EDGE = '#7d89b0'
FONT_SIZE, LINE_H = 13, 17
LABEL_SIZE = 11
MARGIN = 30
ARROW_ID = 'dreados-flow-arrow'

TOOLS = [{
    'name': 'draw_flowchart',
    'description': (
        'Draw a flowchart / process diagram as an image. Use this instead of image generation for any '
        'flowchart, workflow, decision tree or pipeline. Pass nodes: [{id, label, shape}] (shape: box, '
        'round, diamond for decisions, ellipse for start/end, parallelogram for input/output) and edges: '
        '[{from, to, label}] using node ids (label e.g. "Yes"/"No"). Optional direction TB or LR, title.'),
    'inputSchema': {
        'type': 'object', 'additionalProperties': False, 'required': ['nodes', 'edges'],
        'properties': {
            'title': {'type': 'string', 'maxLength': 120},
            'direction': {'type': 'string', 'enum': ['TB', 'LR'], 'description': 'TB = top to bottom (default), LR = left to right.'},
            'nodes': {'type': 'array', 'minItems': 1, 'maxItems': MAX_NODES, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['id', 'label'],
                'properties': {
                    'id': {'type': 'string', 'maxLength': 40, 'description': 'Short unique id, e.g. "start".'},
                    'label': {'type': 'string', 'maxLength': 80},
                    'shape': {'type': 'string', 'enum': list(SHAPES)},
                }}},
            'edges': {'type': 'array', 'maxItems': MAX_EDGES, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['from', 'to'],
                'properties': {
                    'from': {'type': 'string', 'maxLength': 40},
                    'to': {'type': 'string', 'maxLength': 40},
                    'label': {'type': 'string', 'maxLength': 40},
                }}},
        }},
}]


class InputError(ValueError):
    """Bad user input: reported back as a friendly message, never raised out of call()."""


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


def _f(v):
    text = f'{v:.1f}'
    return text[:-2] if text.endswith('.0') else text


def text_width(text, size):
    total = 0.0
    for ch in str(text):
        if ch in "il.,:;|!'`jtfr()[] ":
            total += 0.32
        elif ch in 'mwMW@%':
            total += 0.86
        elif ch.isupper() or ch in '&#':
            total += 0.66
        elif ch.isdigit():
            total += 0.56
        else:
            total += 0.54
    return total * size


def wrap(text, max_chars, max_lines=4):
    """Greedy word wrap; very long words are split; overflow ends with an ellipsis."""
    words = []
    for word in str(text).split():
        while len(word) > max_chars:
            words.append(word[:max_chars - 1] + '-')
            word = word[max_chars - 1:]
        words.append(word)
    lines, line = [], ''
    for word in words:
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= max_chars:
            line += ' ' + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last[:max_chars - 1].rstrip() if len(last) >= max_chars else last) + '…'
    return lines or ['']


# ---------------------------------------------------------------- validation

def _clean(value, what, limit, required=True):
    if value is None or value == '':
        if required:
            raise InputError(f'{what} is missing.')
        return ''
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InputError(f'{what} must be text.')
    value = ' '.join(str(value).split())
    if len(value) > limit:
        raise InputError(f'{what} is too long (max {limit} characters).')
    return value


def validate(arguments):
    if not isinstance(arguments, dict):
        raise InputError('Pass an object like {"nodes": [{"id": "a", "label": "Start"}], "edges": [{"from": "a", "to": "b"}]}.')
    unknown = sorted(set(arguments) - {'nodes', 'edges', 'direction', 'title'})
    if unknown:
        raise InputError(f'Unknown field(s): {", ".join(unknown)}. Allowed: nodes, edges, direction, title.')
    title = _clean(arguments.get('title'), '"title"', 120, required=False)
    direction = str(arguments.get('direction') or 'TB').strip().upper()
    direction = {'TD': 'TB', 'DOWN': 'TB', 'VERTICAL': 'TB', 'TOP-BOTTOM': 'TB', 'RIGHT': 'LR',
                 'HORIZONTAL': 'LR', 'LEFT-RIGHT': 'LR'}.get(direction, direction)
    if direction not in ('TB', 'LR'):
        raise InputError('"direction" must be "TB" (top to bottom) or "LR" (left to right).')

    nodes = arguments.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        raise InputError('"nodes" must be a non-empty list like [{"id": "start", "label": "Start", "shape": "ellipse"}].')
    if len(nodes) > MAX_NODES:
        raise InputError(f'Too many nodes ({len(nodes)}); the limit is {MAX_NODES}. Split the diagram into parts.')
    clean_nodes, seen = [], {}
    for i, node in enumerate(nodes):
        if isinstance(node, str):
            node = {'id': node, 'label': node}
        if not isinstance(node, dict):
            raise InputError(f'Node {i + 1} must be an object like {{"id": "a", "label": "Do something"}}.')
        extra = sorted(set(node) - {'id', 'label', 'shape'})
        if extra:
            raise InputError(f'Node {i + 1} has unknown field(s): {", ".join(extra)}. Use id, label, shape.')
        nid = _clean(node.get('id'), f'Node {i + 1} "id"', 40)
        if nid in seen:
            raise InputError(f'Duplicate node id "{nid}" (nodes {seen[nid] + 1} and {i + 1}). Every id must be unique.')
        seen[nid] = i
        label = _clean(node.get('label'), f'Node "{nid}" label', 80, required=False) or nid
        shape = node.get('shape')
        if shape in (None, ''):
            shape = 'diamond' if label.endswith('?') else 'box'
        else:
            shape = str(shape).strip().lower()
            shape = SHAPE_ALIASES.get(shape, shape)
            if shape not in SHAPES:
                raise InputError(f'Node "{nid}" has unknown shape "{_clip(node.get("shape"), 20)}". Use one of: {", ".join(SHAPES)}.')
        clean_nodes.append({'id': nid, 'label': label, 'shape': shape})

    edges = arguments.get('edges')
    if edges is None:
        edges = []
    if not isinstance(edges, list):
        raise InputError('"edges" must be a list like [{"from": "a", "to": "b", "label": "Yes"}].')
    if len(edges) > MAX_EDGES:
        raise InputError(f'Too many edges ({len(edges)}); the limit is {MAX_EDGES}.')
    clean_edges, missing = [], []
    for i, edge in enumerate(edges):
        if isinstance(edge, (list, tuple)) and len(edge) in (2, 3):
            edge = dict(zip(('from', 'to', 'label'), edge))
        if not isinstance(edge, dict):
            raise InputError(f'Edge {i + 1} must be an object like {{"from": "a", "to": "b"}}.')
        extra = sorted(set(edge) - {'from', 'to', 'label'})
        if extra:
            raise InputError(f'Edge {i + 1} has unknown field(s): {", ".join(extra)}. Use from, to, label.')
        src = _clean(edge.get('from'), f'Edge {i + 1} "from"', 40)
        dst = _clean(edge.get('to'), f'Edge {i + 1} "to"', 40)
        for end in (src, dst):
            if end not in seen and end not in missing:
                missing.append(end)
        label = _clean(edge.get('label'), f'Edge {i + 1} label', 40, required=False)
        clean_edges.append({'from': src, 'to': dst, 'label': label})
    if missing:
        known = ', '.join(n['id'] for n in clean_nodes[:20]) + (', ...' if len(clean_nodes) > 20 else '')
        raise InputError(f'Edges refer to unknown node id(s): {", ".join(missing[:10])}. '
                         f'Edge "from"/"to" must be node ids (known ids: {known}).')
    return {'title': title, 'direction': direction, 'nodes': clean_nodes, 'edges': clean_edges}


def _clip(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ---------------------------------------------------------------- node geometry

def _size_node(node, direction):
    shape = node['shape']
    chars = {'diamond': 16, 'ellipse': 18}.get(shape, 20 if direction == 'TB' else 17)
    lines = wrap(node['label'], chars)
    tw = max(text_width(line, FONT_SIZE) for line in lines)
    th = len(lines) * LINE_H
    skew = 0.0
    if shape == 'diamond':
        k = 1.6
        b = tw / (2 * k) + th / 2 + 9
        a = k * b + 6
        w, h = max(110.0, 2 * a), max(64.0, 2 * b)
    elif shape == 'ellipse':
        w, h = max(96.0, tw * 1.42 + 26), max(44.0, th * 1.42 + 16)
    else:
        h = max(42.0, th + 20)
        if shape == 'parallelogram':
            skew = min(18.0, h * 0.36)
            w = max(110.0, tw + 28 + skew * 1.7)
        else:
            w = max(96.0, tw + 30)
    node.update(lines=lines, w=w, h=h, skew=skew, rr=min(18.0, h / 2) if shape == 'round' else 6.0)


def border_point(node, side, offset):
    """Point on the node outline: side top/bottom (offset along x) or left/right (offset along y)."""
    cx, cy, w2, h2, shape = node['x'], node['y'], node['w'] / 2, node['h'] / 2, node['shape']
    if side in ('top', 'bottom'):
        d = max(-w2 * 0.9, min(w2 * 0.9, offset))
        if shape == 'diamond':
            dist = h2 * (1 - abs(d) / w2)
        elif shape == 'ellipse':
            dist = h2 * math.sqrt(max(0.0, 1 - (d / w2) ** 2))
        elif shape == 'round' and abs(d) > w2 - node['rr']:
            rr = node['rr']
            dist = h2 - rr + math.sqrt(max(0.0, rr * rr - (abs(d) - (w2 - rr)) ** 2))
        else:
            dist = h2
        return (cx + d, cy + dist) if side == 'bottom' else (cx + d, cy - dist)
    d = max(-h2 * 0.9, min(h2 * 0.9, offset))
    if shape == 'diamond':
        dist = w2 * (1 - abs(d) / h2)
    elif shape == 'ellipse':
        dist = w2 * math.sqrt(max(0.0, 1 - (d / h2) ** 2))
    elif shape == 'round' and abs(d) > h2 - node['rr']:
        rr = node['rr']
        dist = w2 - rr + math.sqrt(max(0.0, rr * rr - (abs(d) - (h2 - rr)) ** 2))
    elif shape == 'parallelogram':
        frac = d / (2 * h2)
        dist = w2 - node['skew'] * (0.5 + frac if side == 'right' else 0.5 - frac)
    else:
        dist = w2
    return (cx + dist, cy + d) if side == 'right' else (cx - dist, cy + d)


# ---------------------------------------------------------------- layout

def layout(spec):
    """Lay out each connected component separately, then place them side by side."""
    direction = spec['direction']
    tb = direction == 'TB'
    ids = [n['id'] for n in spec['nodes']]
    parent = {i: i for i in ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in spec['edges']:
        parent[find(e['from'])] = find(e['to'])
    groups = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    edges = [dict(e, i=k) for k, e in enumerate(spec['edges'])]
    if len(groups) == 1:
        return _layout_one(spec['nodes'], edges, direction)
    merged = {'nodes': [], 'routes': [], 'pill': {}, 'edges': [], 'layers': 0}
    cursor = 0.0
    bounds = None
    for members in groups.values():  # dict keeps first-seen (input) order
        member_set = set(members)
        sub_nodes = [n for n in spec['nodes'] if n['id'] in member_set]
        sub_edges = [e for e in edges if e['from'] in member_set]
        lay = _layout_one(sub_nodes, sub_edges, direction)
        x0, y0, x1, y1 = lay['bounds']
        sx, sy = (cursor - x0, 0.0) if tb else (0.0, cursor - y0)
        cursor += ((x1 - x0) if tb else (y1 - y0)) + 60
        for n in lay['nodes']:
            n['x'] += sx
            n['y'] += sy
            n['o'] += sx if tb else sy
        for r in lay['routes']:
            r['shift'] = (sx, sy)
            if r['label_at']:
                r['label_at'] = [(x + sx, y + sy) for x, y in r['label_at']]
        b = (x0 + sx, y0 + sy, x1 + sx, y1 + sy)
        bounds = b if bounds is None else (min(bounds[0], b[0]), min(bounds[1], b[1]),
                                           max(bounds[2], b[2]), max(bounds[3], b[3]))
        merged['nodes'] += lay['nodes']
        merged['routes'] += lay['routes']
        merged['pill'].update(lay['pill'])
        merged['edges'] += lay['edges']
        merged['layers'] = max(merged['layers'], lay['layers'])
    merged['bounds'] = bounds
    return merged


def _layout_one(spec_nodes, spec_edges, direction):
    tb = direction == 'TB'
    nodes = [dict(n) for n in spec_nodes]
    for node in nodes:
        _size_node(node, direction)
    index = {n['id']: i for i, n in enumerate(nodes)}
    count = len(nodes)
    edges = [{'u': index[e['from']], 'v': index[e['to']], 'label': e['label'], 'i': e['i'],
              'from': e['from'], 'to': e['to']} for e in spec_edges]

    # 1. break cycles: DFS from sources in input order; edges to a node on the stack are back edges
    out = [[] for _ in range(count)]
    indeg = [0] * count
    for e in edges:
        if e['u'] != e['v']:
            out[e['u']].append(e)
            indeg[e['v']] += 1
    state = [0] * count

    def dfs(u):
        state[u] = 1
        for e in out[u]:
            if state[e['v']] == 1:
                e['kind'] = 'back'
            elif state[e['v']] == 0:
                dfs(e['v'])
        state[u] = 2

    for root in [i for i in range(count) if indeg[i] == 0] + list(range(count)):
        if state[root] == 0:
            dfs(root)
    for e in edges:
        e.setdefault('kind', 'self' if e['u'] == e['v'] else 'forward')
    forward = [e for e in edges if e['kind'] == 'forward']

    # 2. longest-path layering (Kahn order over forward edges)
    layer = [0] * count
    deg = [0] * count
    for e in forward:
        deg[e['v']] += 1
    queue = [i for i in range(count) if deg[i] == 0]
    succ = [[] for _ in range(count)]
    for e in forward:
        succ[e['u']].append(e['v'])
    while queue:
        u = queue.pop(0)
        for v in succ[u]:
            layer[v] = max(layer[v], layer[u] + 1)
            deg[v] -= 1
            if deg[v] == 0:
                queue.append(v)
    layers_n = max(layer) + 1

    # 3. vertices: real nodes plus dummies along long edges
    vlayer = list(layer)
    vreal = [True] * count
    vsize_o = [n['w'] if tb else n['h'] for n in nodes]
    vsize_r = [n['h'] if tb else n['w'] for n in nodes]
    ext_hi = [0.0] * count
    pill = {}
    for e in edges:
        if e['label']:
            pill[e['i']] = (text_width(e['label'], LABEL_SIZE) + 14, 18.0)
    for e in edges:
        if e['kind'] == 'self':
            pw, ph = pill.get(e['i'], (0.0, 0.0))
            ext_hi[e['u']] = max(ext_hi[e['u']], 30 + ((pw + 8) if tb else (ph + 8) if pw else 0))
    for e in forward:
        chain = [e['u']]
        span = layer[e['v']] - layer[e['u']]
        mid = (span - 1) // 2 + 1 if span > 1 else None
        for step in range(1, span):
            d = len(vlayer)
            vlayer.append(layer[e['u']] + step)
            vreal.append(False)
            size_o, size_r = 0.0, 0.0
            if step == mid and e['i'] in pill:
                pw, ph = pill[e['i']]
                size_o, size_r = (pw, ph) if tb else (ph, pw)
                e['label_vertex'] = d
            vsize_o.append(size_o)
            vsize_r.append(size_r)
            ext_hi.append(0.0)
            chain.append(d)
        chain.append(e['v'])
        e['chain'] = chain
    nv = len(vlayer)
    up = [[] for _ in range(nv)]
    down = [[] for _ in range(nv)]
    for e in forward:
        for a, b in zip(e['chain'], e['chain'][1:]):
            down[a].append(b)
            up[b].append(a)
    rows = [[] for _ in range(layers_n)]
    for v in range(nv):
        rows[vlayer[v]].append(v)

    # 4. ordering: initial barycentres from the layer above, then sweeps keeping the best
    pos = [0.0] * nv
    for row in rows:
        for k, v in enumerate(row):
            pos[v] = k
    for li in range(1, layers_n):
        rows[li].sort(key=lambda v: (sum(pos[u] for u in up[v]) / len(up[v]) if up[v] else pos[v], v))
        for k, v in enumerate(rows[li]):
            pos[v] = k

    def crossings():
        total = 0
        for li in range(layers_n - 1):
            segs = [(pos[a], pos[b]) for a in rows[li] for b in down[a]]
            for i in range(len(segs)):
                a1, b1 = segs[i]
                for j in range(i + 1, len(segs)):
                    a2, b2 = segs[j]
                    if (a1 - a2) * (b1 - b2) < 0:
                        total += 1
        return total

    best = (crossings(), [list(r) for r in rows])
    for it in range(12):
        if best[0] == 0:
            break
        order = range(1, layers_n) if it % 2 == 0 else range(layers_n - 2, -1, -1)
        for li in order:
            nb = up if it % 2 == 0 else down
            rows[li].sort(key=lambda v: (sum(pos[u] for u in nb[v]) / len(nb[v]) if nb[v] else pos[v], pos[v]))
            for k, v in enumerate(rows[li]):
                pos[v] = k
        c = crossings()
        if c < best[0]:
            best = (c, [list(r) for r in rows])
    rows = best[1]

    # 5. coordinates along the order axis: weighted isotonic regression per layer
    def sep(a, b):
        if vreal[a] and vreal[b]:
            return 44.0
        return 22.0 if (vreal[a] or vreal[b]) else 14.0

    def place(row, desired, weights):
        offsets = [0.0]
        for k in range(1, len(row)):
            a, b = row[k - 1], row[k]
            offsets.append(offsets[-1] + vsize_o[a] / 2 + ext_hi[a] + sep(a, b) + vsize_o[b] / 2)
        blocks = []  # [weighted sum, weight, count]
        for k in range(len(row)):
            blocks.append([weights[k] * (desired[k] - offsets[k]), weights[k], 1])
            while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                s, w, c = blocks.pop()
                blocks[-1][0] += s
                blocks[-1][1] += w
                blocks[-1][2] += c
        k = 0
        for s, w, c in blocks:
            for _ in range(c):
                pos[row[k]] = s / w + offsets[k]
                k += 1

    for row in rows:
        place(row, [0.0] * len(row), [1.0] * len(row))
    for it in range(10):
        if it < 8:
            sweep = range(1, layers_n) if it % 2 == 0 else range(layers_n - 2, -1, -1)
            neighbours = up if it % 2 == 0 else down
        else:
            sweep = range(layers_n)
            neighbours = None
        for li in sweep:
            row = rows[li]
            desired, weights = [], []
            for v in row:
                nb = neighbours[v] if neighbours is not None else up[v] + down[v]
                if nb:
                    desired.append(sum(pos[u] for u in nb) / len(nb))
                    weights.append(1.0 if vreal[v] else 1.6)
                else:
                    desired.append(pos[v])
                    weights.append(0.25)
            place(row, desired, weights)

    # 6. coordinates along the rank axis
    thick = [max([vsize_r[v] for v in row] or [0.0]) for row in rows]
    gaps = []
    for li in range(layers_n - 1):
        gap = 52.0 if tb else 60.0
        for e in forward:
            if e['i'] in pill and len(e['chain']) == 2 and layer[e['u']] == li:
                pw, ph = pill[e['i']]
                gap = max(gap, (ph + 46) if tb else (pw + 34))
        gaps.append(gap)
    rank_c, cursor = [], 0.0
    for li in range(layers_n):
        rank_c.append(cursor + thick[li] / 2)
        cursor += thick[li] + (gaps[li] if li < layers_n - 1 else 0)

    def real_xy(o, r):
        return (o, r) if tb else (r, o)

    for i, node in enumerate(nodes):
        node['x'], node['y'] = real_xy(pos[i], rank_c[layer[i]])
        node['layer'] = layer[i]
        node['o'] = pos[i]

    # 7. route edges
    side_fwd, side_back = ('bottom', 'top') if tb else ('right', 'left')
    side_hi, side_lo = ('right', 'left') if tb else ('bottom', 'top')
    slots_out = {}
    slots_in = {}
    for e in forward:
        slots_out.setdefault(e['u'], []).append(e)
        slots_in.setdefault(e['v'], []).append(e)

    def spread(node_i, group, key):
        group.sort(key=lambda e: (pos[key(e)], e['i']))
        m = len(group)
        size = vsize_o[node_i]
        step = min(16.0, size * 0.44 / (m - 1)) if m > 1 else 0
        return {e['i']: (k - (m - 1) / 2) * step for k, e in enumerate(group)}

    out_off, in_off = {}, {}
    for u, group in slots_out.items():
        out_off.update({(u, k): v for k, v in spread(u, group, lambda e: e['chain'][1]).items()})
    for v, group in slots_in.items():
        in_off.update({(v, k): o for k, o in spread(v, group, lambda e: e['chain'][-2]).items()})

    def vpoint(v, rank_edge):
        """Point of a dummy vertex at the start (-1) or end (+1) of its layer band."""
        r = rank_c[vlayer[v]] + rank_edge * thick[vlayer[v]] / 2
        return real_xy(pos[v], r)

    routes = []
    for e in forward:
        u, v, chain = e['u'], e['v'], e['chain']
        p0 = border_point(nodes[u], side_fwd, out_off[(u, e['i'])])
        p1 = border_point(nodes[v], side_back, in_off[(v, e['i'])])
        pts = [p0]
        for d in chain[1:-1]:
            pts.append(vpoint(d, -1))
            pts.append(vpoint(d, +1))
        pts.append(p1)
        d_attr = f'M{_f(pts[0][0])},{_f(pts[0][1])}'
        segments = []
        for k in range(0, len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            if k % 2 == 0:  # gap between layers: smooth S-curve along the rank axis
                if tb:
                    m = (a[1] + b[1]) / 2
                    c1, c2 = (a[0], m), (b[0], m)
                else:
                    m = (a[0] + b[0]) / 2
                    c1, c2 = (m, a[1]), (m, b[1])
                d_attr += f' C{_f(c1[0])},{_f(c1[1])} {_f(c2[0])},{_f(c2[1])} {_f(b[0])},{_f(b[1])}'
                segments.append((a, c1, c2, b))
            else:  # straight through a dummy's layer band
                d_attr += f' L{_f(b[0])},{_f(b[1])}'
        label_at = None
        if e['label']:
            if 'label_vertex' in e:
                label_at = [real_xy(pos[e['label_vertex']], rank_c[vlayer[e['label_vertex']]])]
            else:
                a, c1, c2, b = segments[len(segments) // 2]
                label_at = [_bezier(a, c1, c2, b, t) for t in (0.5, 0.36, 0.64, 0.25, 0.75)]
        routes.append({'d': d_attr, 'label': e['label'], 'label_at': label_at, 'edge': e})

    # back edges: around the side of everything they span, in separate lanes
    lanes = {'hi': [], 'lo': []}  # (rank_lo, rank_hi, extent)
    for e in sorted((e for e in edges if e['kind'] == 'back'),
                    key=lambda e: (layer[e['u']] - layer[e['v']], e['i'])):
        u, v = e['u'], e['v']
        lu, lv = layer[u], layer[v]
        row_u, row_v = rows[lu], rows[lv]
        real_u = [x for x in row_u if vreal[x]]
        real_v = [x for x in row_v if vreal[x]]
        beyond_hi = sum(1 for x in real_u if pos[x] > pos[u]) + sum(1 for x in real_v if pos[x] > pos[v])
        beyond_lo = sum(1 for x in real_u if pos[x] < pos[u]) + sum(1 for x in real_v if pos[x] < pos[v])
        side = 'hi' if beyond_hi <= beyond_lo else 'lo'
        sgn = 1 if side == 'hi' else -1
        span_vs = [x for li in range(lv, lu + 1) for x in rows[li]]
        if side == 'hi':
            extreme = max(pos[x] + vsize_o[x] / 2 + ext_hi[x] for x in span_vs)
        else:
            extreme = min(pos[x] - vsize_o[x] / 2 for x in span_vs)
        r_lo, r_hi = rank_c[lv] - thick[lv] / 2, rank_c[lu] + thick[lu] / 2
        for a, b, ext in lanes[side]:
            if a < r_hi + 30 and b > r_lo - 30:
                extreme = max(extreme, ext) if side == 'hi' else min(extreme, ext)
        pw = pill.get(e['i'], (0.0, 18.0))
        half_label = (pw[0] / 2 if tb else pw[1] / 2) if e['label'] else 0
        lane = extreme + sgn * (26 + half_label)
        lanes[side].append((r_lo, r_hi, lane + sgn * (half_label + 4)))
        side_name = side_hi if side == 'hi' else side_lo
        nu, nvv = nodes[u], nodes[v]
        u_extreme = all(sgn * (pos[x] - pos[u]) <= 0 for x in real_u)
        v_extreme = all(sgn * (pos[x] - pos[v]) <= 0 for x in real_v)
        pts = []
        if u_extreme:
            p = border_point(nu, side_name, 0)
            pts.append(_to_or(p, tb))
        else:
            off = sgn * vsize_o[u] * 0.36
            p = border_point(nu, side_fwd, off)
            pts.append(_to_or(p, tb))
            pts.append((pos[u] + off, rank_c[lu] + thick[lu] / 2 + 15))
        pts.append((lane, pts[-1][1]))
        if v_extreme:
            p = border_point(nvv, side_name, 0)
            q = _to_or(p, tb)
            pts.append((lane, q[1]))
            pts.append(q)
        else:
            off = sgn * vsize_o[v] * 0.36
            r_top = rank_c[lv] - thick[lv] / 2 - 15
            pts.append((lane, r_top))
            pts.append((pos[v] + off, r_top))
            pts.append(_to_or(border_point(nvv, side_back, off), tb))
        real_pts = [real_xy(o, r) for o, r in pts]
        lane_rs = [p[1] for p in pts if p[0] == lane]
        mid_r = (lane_rs[0] + lane_rs[-1]) / 2
        label_at = [real_xy(lane, mid_r)] if e['label'] else None
        routes.append({'d': _rounded(real_pts, 12), 'label': e['label'], 'label_at': label_at, 'edge': e})

    for e in edges:
        if e['kind'] != 'self':
            continue
        n = nodes[e['u']]
        if tb:
            a = border_point(n, 'right', -9)
            b = border_point(n, 'right', 9)
            xr = n['x'] + n['w'] / 2
            d = (f'M{_f(a[0])},{_f(a[1])} C{_f(xr + 34)},{_f(a[1] - 22)} {_f(xr + 34)},{_f(b[1] + 22)} '
                 f'{_f(b[0])},{_f(b[1])}')
            label_at = [(xr + 30 + pill.get(e['i'], (0, 0))[0] / 2 + 4, n['y'])]
        else:
            a = border_point(n, 'bottom', -9)
            b = border_point(n, 'bottom', 9)
            yb = n['y'] + n['h'] / 2
            d = (f'M{_f(a[0])},{_f(a[1])} C{_f(a[0] - 22)},{_f(yb + 34)} {_f(b[0] + 22)},{_f(yb + 34)} '
                 f'{_f(b[0])},{_f(b[1])}')
            label_at = [(n['x'], yb + 30 + 13)]
        routes.append({'d': d, 'label': e['label'], 'label_at': label_at if e['label'] else None, 'edge': e})

    # 8. bounds
    xs, ys = [], []
    for n in nodes:
        xs += [n['x'] - n['w'] / 2, n['x'] + n['w'] / 2]
        ys += [n['y'] - n['h'] / 2, n['y'] + n['h'] / 2]
        if tb:
            xs.append(n['x'] + n['w'] / 2 + ext_hi[nodes.index(n)])
        else:
            ys.append(n['y'] + n['h'] / 2 + ext_hi[nodes.index(n)])
    for side in lanes.values():
        for _, _, ext in side:
            (xs if tb else ys).append(ext)
    for v in range(count, nv):
        x, y = real_xy(pos[v], rank_c[vlayer[v]])
        xs += [x - (vsize_o[v] / 2 if tb else vsize_r[v] / 2), x + (vsize_o[v] / 2 if tb else vsize_r[v] / 2)]
        ys += [y]
    for route in routes:
        if route['label_at']:
            pw, ph = pill.get(route['edge']['i'], (0, 0))
            x, y = route['label_at'][0]
            xs += [x - pw / 2, x + pw / 2]
            ys += [y - ph / 2, y + ph / 2]
    return {'nodes': nodes, 'routes': routes, 'pill': pill, 'rows': rows, 'vreal': vreal,
            'bounds': (min(xs), min(ys), max(xs), max(ys)), 'layers': layers_n, 'edges': edges}


def _to_or(p, tb):
    return (p[0], p[1]) if tb else (p[1], p[0])


def _bezier(a, c1, c2, b, t):
    s = 1 - t
    return (s ** 3 * a[0] + 3 * s * s * t * c1[0] + 3 * s * t * t * c2[0] + t ** 3 * b[0],
            s ** 3 * a[1] + 3 * s * s * t * c1[1] + 3 * s * t * t * c2[1] + t ** 3 * b[1])


def _rounded(points, radius):
    """SVG path through an orthogonal polyline with rounded corners."""
    pts = [points[0]]
    for p in points[1:]:  # drop zero-length steps
        if abs(p[0] - pts[-1][0]) > 0.01 or abs(p[1] - pts[-1][1]) > 0.01:
            pts.append(p)
    d = f'M{_f(pts[0][0])},{_f(pts[0][1])}'
    for k in range(1, len(pts) - 1):
        prev, cur, nxt = pts[k - 1], pts[k], pts[k + 1]
        l1 = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        l2 = math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
        r = min(radius, l1 / 2, l2 / 2)
        a = (cur[0] - (cur[0] - prev[0]) / l1 * r, cur[1] - (cur[1] - prev[1]) / l1 * r)
        b = (cur[0] + (nxt[0] - cur[0]) / l2 * r, cur[1] + (nxt[1] - cur[1]) / l2 * r)
        d += f' L{_f(a[0])},{_f(a[1])} Q{_f(cur[0])},{_f(cur[1])} {_f(b[0])},{_f(b[1])}'
    d += f' L{_f(pts[-1][0])},{_f(pts[-1][1])}'
    return d


# ---------------------------------------------------------------- drawing

def _shape_svg(n):
    x, y, w, h, shape = n['x'], n['y'], n['w'], n['h'], n['shape']
    stroke, fill = STROKE[shape], FILL[shape]
    common = f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"'
    if shape == 'diamond':
        pts = f'{_f(x)},{_f(y - h / 2)} {_f(x + w / 2)},{_f(y)} {_f(x)},{_f(y + h / 2)} {_f(x - w / 2)},{_f(y)}'
        return f'<polygon points="{pts}" {common} stroke-linejoin="round"/>'
    if shape == 'ellipse':
        return f'<ellipse cx="{_f(x)}" cy="{_f(y)}" rx="{_f(w / 2)}" ry="{_f(h / 2)}" {common}/>'
    if shape == 'parallelogram':
        s, x0, x1, y0, y1 = n['skew'], x - w / 2, x + w / 2, y - h / 2, y + h / 2
        pts = f'{_f(x0 + s)},{_f(y0)} {_f(x1)},{_f(y0)} {_f(x1 - s)},{_f(y1)} {_f(x0)},{_f(y1)}'
        return f'<polygon points="{pts}" {common} stroke-linejoin="round"/>'
    return (f'<rect x="{_f(x - w / 2)}" y="{_f(y - h / 2)}" width="{_f(w)}" height="{_f(h)}" '
            f'rx="{_f(n["rr"])}" {common}/>')


def _label_svg(n):
    lines = n['lines']
    top = n['y'] - len(lines) * LINE_H / 2
    out = []
    for i, line in enumerate(lines):
        out.append(f'<text x="{_f(n["x"])}" y="{_f(top + i * LINE_H + 12.5)}" font-size="{FONT_SIZE}" '
                   f'fill="{COLORS["text"]}" text-anchor="middle">{esc(line)}</text>')
    return ''.join(out)


def render(spec):
    lay = layout(spec)
    x0, y0, x1, y1 = lay['bounds']
    head = 50 if spec['title'] else 0
    dx, dy = MARGIN - x0, MARGIN + head - y0
    width = max(320.0, x1 - x0 + 2 * MARGIN)
    if spec['title']:
        width = max(width, text_width(_clip(spec['title'], 80), 20) + 40)
    dx += (width - (x1 - x0 + 2 * MARGIN)) / 2
    height = y1 - y0 + 2 * MARGIN + head
    body = [f'<defs><marker id="{ARROW_ID}" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="10" markerHeight="10" '
            f'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0.8 L10,5 L0,9.2 z" fill="{EDGE}"/></marker></defs>',
            f'<g transform="translate({_f(dx)},{_f(dy)})">']
    for route in lay['routes']:
        sx, sy = route.get('shift', (0, 0))
        move = f' transform="translate({_f(sx)},{_f(sy)})"' if (sx or sy) else ''
        body.append(f'<path d="{route["d"]}"{move} fill="none" stroke="{EDGE}" stroke-width="1.7" '
                    f'stroke-linecap="round" marker-end="url(#{ARROW_ID})"/>')
    for n in lay['nodes']:
        body.append(_shape_svg(n))
        body.append(_label_svg(n))
    boxes = [(n['x'] - n['w'] / 2, n['y'] - n['h'] / 2, n['x'] + n['w'] / 2, n['y'] + n['h'] / 2) for n in lay['nodes']]
    for route in lay['routes']:
        if not route['label_at']:
            continue
        pw, ph = lay['pill'][route['edge']['i']]
        choice = route['label_at'][0]
        for cand in route['label_at']:
            box = (cand[0] - pw / 2, cand[1] - ph / 2, cand[0] + pw / 2, cand[1] + ph / 2)
            if not any(box[0] < b[2] + 2 and box[2] > b[0] - 2 and box[1] < b[3] + 2 and box[3] > b[1] - 2 for b in boxes):
                choice = cand
                break
        x, y = choice
        boxes.append((x - pw / 2, y - ph / 2, x + pw / 2, y + ph / 2))
        body.append(f'<rect x="{_f(x - pw / 2)}" y="{_f(y - ph / 2)}" width="{_f(pw)}" height="{_f(ph)}" rx="9" '
                    f'fill="{COLORS["bg"]}" stroke="{COLORS["grid"]}"/>')
        body.append(f'<text x="{_f(x)}" y="{_f(y + 4)}" font-size="{LABEL_SIZE}" fill="{COLORS["sub"]}" '
                    f'text-anchor="middle">{esc(route["label"])}</text>')
    body.append('</g>')
    return svgkit.svg_document(math.ceil(width), math.ceil(height), body, _clip(spec['title'], 80)), lay


def _summary(spec, lay):
    nodes = lay['nodes']
    by_layer = {}
    for n in nodes:
        by_layer.setdefault(n['layer'], []).append(n)
    parts = []
    for li in sorted(by_layer):
        row = sorted(by_layer[li], key=lambda n: n['o'])
        parts.append(f'{li + 1}. ' + ' | '.join(n['label'] for n in row))
    loops = [e for e in lay['edges'] if e['kind'] in ('back', 'self')]
    label_of = {n['id']: n['label'] for n in nodes}
    head = 'Flowchart' + (f' "{spec["title"]}"' if spec['title'] else '')
    head += f' ({"top to bottom" if spec["direction"] == "TB" else "left to right"}): {len(nodes)} steps, ' \
            f'{len(lay["edges"])} connections, {lay["layers"]} layers.'
    text = head + ' Steps by layer: ' + '; '.join(parts) + '.'
    if loops:
        text += ' Loops: ' + '; '.join(
            f'{label_of[e["from"]]} -> {label_of[e["to"]]}' + (f' ({e["label"]})' if e['label'] else '')
            for e in loops) + '.'
    return text


def call(tool, arguments):
    if tool != 'draw_flowchart':
        return _error(f'Unknown flowchart tool "{tool}". Use draw_flowchart.')
    try:
        spec = validate(arguments)
    except InputError as error:
        return _error(str(error))
    svg, lay = render(spec)
    return svgkit.image_result(_summary(spec, lay), svg)
