import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from builtin_tools import projects
from builtin_tools import site_audit as sa

CLEAN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jazz Guitar Lessons - Home</title>
  <meta name="description" content="Friendly jazz guitar lessons for beginners and improvers, online and in person.">
  <meta property="og:title" content="Jazz Guitar Lessons">
  <meta property="og:description" content="Friendly jazz guitar lessons for all levels.">
  <link rel="icon" href="favicon.svg">
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header><nav><a href="about/">About</a> <a href="#contact">Contact</a></nav></header>
  <main>
    <h1>Jazz guitar lessons</h1>
    <img src="img/photo.png" alt="Guitar on a stand" width="400" height="300">
    <h2>Book a lesson</h2>
    <form>
      <label for="email">Email</label>
      <input id="email" type="email">
      <label>Name <input type="text" name="name"></label>
      <input type="hidden" name="token" value="x">
      <button type="submit">Send</button>
    </form>
    <a href="https://example.com" target="_blank" rel="noopener">Partner</a>
    <a href="mailto:hi@example.com">Mail us</a>
    <button aria-label="Close"><svg viewBox="0 0 1 1"></svg></button>
  </main>
  <footer id="contact"><p>Call us</p></footer>
</body>
</html>
"""

CLEAN_CSS = """:root { --ink: #1a1a1a; --paper: #ffffff; }
body { color: var(--ink); background: var(--paper); }
.button { color: #ffffff; background-color: #0050a0; }
.hero { background: linear-gradient(#000, #fff); color: #777; }
"""

ABOUT_HTML = """<!doctype html>
<html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>About our jazz guitar school</title>
<meta name="description" content="Who we are: a small jazz guitar school with friendly teachers since 2010.">
<meta property="og:title" content="About"><meta property="og:description" content="About us.">
<link rel="icon" href="../favicon.svg"><link rel="stylesheet" href="../css/style.css"></head>
<body><h1 id="team">About us</h1><a href="../">Home</a> <a href="../index.html#contact">Contact</a></body></html>
"""

# Each problem sits on a known line (1-based) so line numbers can be asserted.
BROKEN_HTML = """<!doctype html>
<html>
<head>
<title>Hi</title>
<meta name="viewport" content="width=device-width, user-scalable=no">
<link rel="stylesheet" href="missing.css">
<script src="https://cdn.example.com/lib.js"></script>
</head>
<body>
<h1>One</h1>
<h1>Two</h1>
<h4>Skipped</h4>
<img src="pic.png">
<a href="other.html"></a>
<a href="#">Nowhere</a>
<a href="nope.html">Broken</a>
<a href="#ghost">Ghost</a>
<a href="https://example.com" target="_blank">Out</a>
<button></button>
<input type="text" id="q">
<p id="dup">a</p>
<p id="dup">b</p>
<center>old</center>
<font>old</font>
<marquee>old</marquee>
<input type="search" placeholder="Search">
</body>
</html>
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'build-projects'
        self.root.mkdir()
        patcher = mock.patch.object(projects, 'PROJECTS', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def make(self, name, files):
        base = self.root / name
        base.mkdir()
        for rel, content in files.items():
            path = base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding='utf-8', newline='\n')
        return base

    def clean_site(self, name='clean', **extra):
        files = {'index.html': CLEAN_HTML, 'about/index.html': ABOUT_HTML, 'css/style.css': CLEAN_CSS,
                 'favicon.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>', 'img/photo.png': b'\x89PNG' + b'0' * 100}
        files.update(extra)
        self.make(name, files)
        return name

    @staticmethod
    def found(result, check):
        return [(i['file'], i['line'], i['severity']) for i in result['issues'] if i['check'] == check]


class CleanSiteTests(Fixture):
    def test_clean_site_scores_100(self):
        name = self.clean_site()
        result = sa.audit(name)
        self.assertEqual(result['counts']['error'], 0, result['issues'])
        self.assertEqual(result['counts']['warning'], 0, result['issues'])
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['pages'], ['index.html', 'about/index.html'])
        self.assertEqual(result['stats']['external_links'], ['https://example.com'])
        self.assertIn('mailto:hi@example.com', result['stats']['contact_links'])
        self.assertGreater(result['stats']['page_weight_bytes']['index.html'], len(CLEAN_HTML))

    def test_result_shape(self):
        result = sa.audit(self.clean_site())
        self.assertEqual(set(result), {'project', 'pages', 'score', 'counts', 'issues', 'stats'})
        self.assertEqual(set(result['counts']), {'error', 'warning', 'info'})

    def test_deterministic_and_fast(self):
        name = self.clean_site()
        start = time.perf_counter()
        first = sa.audit(name)
        self.assertLess(time.perf_counter() - start, 0.3)
        self.assertEqual(first, sa.audit(name))

    def test_read_only(self):
        name = self.clean_site()
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in (self.root / name).rglob('*')}
        sa.audit(name)
        sa.call('audit_site', {'project': name})
        after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in (self.root / name).rglob('*')}
        self.assertEqual(before, after)


class BrokenPageTests(Fixture):
    def setUp(self):
        super().setUp()
        self.make('broken', {'index.html': BROKEN_HTML, 'other.html': '<html lang="en"><title>x</title></html>'})
        self.result = sa.audit('broken', page='index.html')

    def assertIssue(self, check, line, severity, file='index.html'):
        self.assertIn((file, line, severity), self.found(self.result, check),
                      f'{check} expected at line {line}: {self.found(self.result, check)}')

    def test_document_checks(self):
        self.assertIssue('html-lang', 2, 'error')
        self.assertIssue('title', 4, 'warning')
        self.assertIssue('meta-description', 3, 'warning')
        self.assertIssue('viewport-zoom', 5, 'warning')
        self.assertIssue('favicon', 3, 'warning')
        self.assertEqual(len(self.found(self.result, 'open-graph')), 2)

    def test_heading_checks(self):
        self.assertIssue('h1', 11, 'warning')
        self.assertIssue('heading-order', 12, 'warning')

    def test_image_and_link_checks(self):
        self.assertIssue('img-alt', 13, 'error')
        self.assertIssue('img-size-attrs', 13, 'info')
        self.assertIssue('missing-asset', 13, 'error')
        self.assertIssue('link-text', 14, 'error')
        self.assertIssue('link-hash', 15, 'warning')
        self.assertIssue('broken-link', 16, 'error')
        self.assertIssue('broken-anchor', 17, 'error')
        self.assertIssue('target-blank', 18, 'warning')
        self.assertNotIn(('index.html', 14, 'error'), self.found(self.result, 'broken-link'))  # other.html exists

    def test_controls_and_markup(self):
        self.assertIssue('button-text', 19, 'error')
        self.assertIssue('form-label', 20, 'error')
        self.assertIssue('form-label', 26, 'warning')  # placeholder only
        self.assertIssue('duplicate-id', 22, 'error')
        for line in (23, 24, 25):
            self.assertIssue('deprecated-tag', line, 'warning')

    def test_assets(self):
        self.assertIssue('missing-asset', 6, 'error')
        self.assertIssue('external-asset', 7, 'info')
        self.assertFalse([i for i in self.result['issues'] if i['check'] == 'external-asset' and i['severity'] != 'info'])
        self.assertEqual(self.result['stats']['external_assets'], ['https://cdn.example.com/lib.js'])

    def test_score_formula(self):
        c = self.result['counts']
        self.assertEqual(self.result['score'], max(0, 100 - 8 * c['error'] - 3 * c['warning']))
        self.assertEqual(self.result['score'], 0)
        self.assertEqual(self.result['pages'], ['index.html'])

    def test_report_text(self):
        text = sa.call('audit_site', {'project': 'broken', 'page': 'index.html'})['content'][0]['text']
        self.assertIn('score 0/100', text)
        self.assertIn('index.html:13 - [img-alt]', text)
        self.assertIn('ERRORS', text)
        self.assertIn('->', text)


class LinkResolutionTests(Fixture):
    def test_relative_links_across_folders(self):
        self.make('links', {
            'index.html': '<html lang="en"><body><a href="./blog/">Blog</a> <a href="blog/post.html?x=1#intro">Post</a>'
                          ' <a href="docs">Docs</a> <a href="/blog/post.html">Abs</a></body></html>',
            'blog/index.html': '<html lang="en"><body><a href="../index.html">Home</a> <a href="post.html#nope">P</a>'
                               ' <a href="../../outside.html">Out</a> <a href="./sub/../post.html">ok</a></body></html>',
            'blog/post.html': '<html lang="en"><body><h2 id="intro">Intro</h2><a href="../missing/">x</a></body></html>',
            'docs.html': '<html lang="en"></html>',
        })
        result = sa.audit('links')
        broken = {(i['file'], i['line'], i['check']) for i in result['issues'] if i['check'].startswith('broken')}
        self.assertEqual(broken, {
            ('blog/index.html', 1, 'broken-anchor'),
            ('blog/index.html', 1, 'broken-link'),      # ../../outside.html escapes the project
            ('blog/post.html', 1, 'broken-link'),       # ../missing/ -> missing/index.html
        })
        messages = ' '.join(i['message'] for i in result['issues'])
        self.assertIn('outside the project', messages)
        self.assertIn('missing/index.html', messages)
        self.assertIn('#nope', messages)

    def test_anchor_ids(self):
        self.make('anchors', {'index.html': (
            '<html lang="en">\n<body>\n<a href="#a">A</a>\n<a href="#b">B</a>\n<a href="#top">Top</a>\n'
            '<a href="#named">N</a>\n<section id="a"></section>\n<a name="named"></a>\n</body></html>')})
        result = sa.audit('anchors')
        self.assertEqual(self.found(result, 'broken-anchor'), [('index.html', 4, 'error')])

    def test_case_mismatch_is_warning(self):
        self.make('case', {'index.html': '<html lang="en"><body><img src="Logo.PNG" alt="x"></body></html>',
                           'logo.png': b'x'})
        result = sa.audit('case')
        self.assertEqual(self.found(result, 'missing-asset'), [])
        self.assertEqual(len(self.found(result, 'path-case')), 1)


class AssetTests(Fixture):
    def test_missing_css_and_css_url_assets(self):
        self.make('assets', {
            'index.html': '<html lang="en">\n<head>\n<link rel="stylesheet" href="css/main.css">\n'
                          '<link rel="stylesheet" href="css/gone.css">\n</head></html>',
            'css/main.css': 'body { color: #111; }\n@font-face { src: url("../fonts/a.woff2"); }\n'
                            '.x { background: url(../img/bg.png) no-repeat; }\n',
            'img/bg.png': b'x',
        })
        result = sa.audit('assets')
        missing = self.found(result, 'missing-asset')
        self.assertIn(('index.html', 4, 'error'), missing)
        self.assertIn(('css/main.css', 2, 'error'), missing)   # font
        self.assertEqual(len(missing), 2)                    # bg.png resolves relative to the CSS file

    def test_oversized_images(self):
        self.make('big', {
            'index.html': '<html lang="en">\n<body>\n<img src="warn.jpg" alt="a" width="1" height="1">\n'
                          '<img src="huge.jpg" alt="b" width="1" height="1">\n</body></html>',
            'warn.jpg': b'0' * (400 * 1024),
            'huge.jpg': b'0' * (1100 * 1024),
        })
        result = sa.audit('big')
        sizes = {(i['file'], i['severity']) for i in result['issues'] if i['check'] == 'image-size'}
        self.assertEqual(sizes, {('warn.jpg', 'warning'), ('huge.jpg', 'error')})
        self.assertIn('index.html:4', next(i['message'] for i in result['issues'] if i['file'] == 'huge.jpg'))
        self.assertGreater(result['stats']['page_weight_bytes']['index.html'], 1_500_000)

    def test_page_weight_warning(self):
        imgs = ''.join(f'<img src="p{i}.jpg" alt="" width="1" height="1">' for i in range(3))
        self.make('heavy', {'index.html': f'<html lang="en"><body>{imgs}</body></html>',
                            **{f'p{i}.jpg': b'0' * (800 * 1024) for i in range(3)}})
        result = sa.audit('heavy')
        self.assertEqual(len(self.found(result, 'page-weight')), 1)

    def test_external_cdn_is_info(self):
        self.make('cdn', {'index.html': '<html lang="en"><head>'
                                        '<link rel="stylesheet" href="https://fonts.example.com/css">'
                                        '<script src="//cdn.example.com/x.js"></script></head></html>'})
        result = sa.audit('cdn')
        ext = [i for i in result['issues'] if i['check'] == 'external-asset']
        self.assertEqual(len(ext), 2)
        self.assertTrue(all(i['severity'] == 'info' for i in ext))
        self.assertEqual(self.found(result, 'missing-asset'), [])


class ContrastTests(Fixture):
    def audit_css(self, css, html_extra=''):
        name = 'c' + str(abs(hash(css)) % 10 ** 8)
        self.make(name, {'index.html': f'<html lang="en"><head><link rel="stylesheet" href="s.css"></head>'
                                       f'<body><p>Text</p>{html_extra}</body></html>', 's.css': css})
        return [i for i in sa.audit(name)['issues'] if i['check'] == 'contrast']

    def test_low_contrast_rule_detected_with_line(self):
        issues = self.audit_css('body { color: #000; background: #fff; }\n\n.muted {\n  color: #888;\n'
                                '  background-color: #fff;\n}\n.bad { color: #ccc; background: #fff; }\n')
        self.assertEqual(sorted((i['line'], i['severity']) for i in issues), [(4, 'warning'), (7, 'error')])
        self.assertIn('.muted', next(i['message'] for i in issues if i['line'] == 4))
        self.assertIn('#', issues[0]['fix'])

    def test_good_contrast_and_unknowns_not_flagged(self):
        issues = self.audit_css(
            ':root { --fg: #222; --bg: #fafafa; }\nbody { color: var(--fg); background: var(--bg); }\n'
            '.a { color: #fff; background: #000; }\n.b { color: #777; background: linear-gradient(#fff, #eee); }\n'
            '.c { color: rgba(0,0,0,.4); background: #fff; }\n.d { color: #aaa; background: transparent; }\n'
            '.e { color: var(--missing); background: #fff; }\n.f { color: #ddd; background: url(x.png) #fff; }\n'
            '@keyframes k { from { color: #eee; background: #fff; } }\n'
            'h1 { color: #888; background: #fff; }\n')  # large text: 3.5:1 passes 3:1
        self.assertEqual(issues, [])

    def test_variables_resolve_and_body_default(self):
        issues = self.audit_css(':root { --muted: #bbb; --paper: #fff; }\n.note { color: var(--muted); '
                                'background: var(--paper); }\n')
        self.assertEqual(len(issues), 1)
        issues = self.audit_css('body { background: #111; }\n')
        self.assertEqual(len(issues), 1)
        self.assertIn('browser default text black', issues[0]['message'])

    def test_inline_style_block_line_numbers(self):
        self.make('inline', {'index.html': '<html lang="en">\n<head>\n<style>\n.x { color: #eee; background: #fff; }\n'
                                           '</style>\n</head><body>hi</body></html>'})
        issues = [i for i in sa.audit('inline')['issues'] if i['check'] == 'contrast']
        self.assertEqual([(i['file'], i['line']) for i in issues], [('index.html', 4)])


class ToolTests(Fixture):
    def test_unknown_project_lists_existing(self):
        self.clean_site('alpha')
        result = sa.call('audit_site', {'project': 'nope'})
        self.assertTrue(result['isError'])
        self.assertIn('alpha', result['content'][0]['text'])

    def test_no_html_project(self):
        self.make('empty-app', {'src/main.js': 'x', 'package.json': '{}'})
        result = sa.call('audit_site', {'project': 'empty-app'})
        self.assertTrue(result['isError'])
        text = result['content'][0]['text']
        self.assertIn('no HTML', text)
        self.assertIn('dist/index.html', text)

    def test_page_restricts_to_one_file(self):
        name = self.clean_site()
        result = sa.audit(name, page='about/index.html')
        self.assertEqual(result['pages'], ['about/index.html'])
        self.assertTrue(all(i['file'] != 'index.html' for i in result['issues']))

    def test_built_dist_page(self):
        self.make('app', {'index.html': '<html lang="en"><script type="module" src="/src/main.jsx"></script></html>',
                          'src/main.jsx': 'x', 'package.json': '{}',
                          'dist/index.html': '<html lang="en"><script src="/assets/app.js"></script></html>',
                          'dist/assets/app.js': 'x'})
        self.assertEqual(self.found(sa.audit('app'), 'build-needed'), [('index.html', 1, 'info')])
        result = sa.audit('app', page='dist/index.html')
        self.assertEqual(self.found(result, 'missing-asset'), [])

    def test_path_traversal_rejected(self):
        name = self.clean_site()
        for bad in ('../../x.html', '..\\x.html', '/etc/x.html', 'C:/x.html', 'about/../../x.html', 'style.css'):
            result = sa.call('audit_site', {'project': name, 'page': bad})
            self.assertTrue(result.get('isError'), bad)
        with self.assertRaises(sa.AuditError):
            sa.audit(name, page='../../x.html')

    def test_missing_page(self):
        result = sa.call('audit_site', {'project': self.clean_site(), 'page': 'nope.html'})
        self.assertTrue(result['isError'])
        self.assertIn('index.html', result['content'][0]['text'])

    def test_bad_arguments(self):
        self.assertTrue(sa.call('audit_site', {})['isError'])
        self.assertTrue(sa.call('audit_site', {'project': 'Bad Name!'})['isError'])
        self.assertTrue(sa.call('audit_site', {'project': 'x', 'page': 5})['isError'])
        self.assertTrue(sa.call('other', {})['isError'])

    def test_tool_definition(self):
        self.assertEqual(len(sa.TOOLS), 1)
        tool = sa.TOOLS[0]
        self.assertEqual(tool['name'], 'audit_site')
        self.assertIs(tool['returnsImage'], False)
        self.assertEqual(tool['inputSchema']['required'], ['project'])

    def test_report_caps_issues(self):
        lines = '\n'.join(f'<img src="i{i}.png">' for i in range(40))
        self.make('many', {'index.html': f'<html lang="en"><body>{lines}</body></html>'})
        result = sa.call('audit_site', {'project': 'many'})
        text = result['content'][0]['text']
        self.assertNotIn('isError', result)
        self.assertIn('more issues not shown', text)
        self.assertLessEqual(sum(1 for line in text.splitlines() if line.startswith('- ') and ' [' in line), 60)


if __name__ == '__main__':
    unittest.main()
