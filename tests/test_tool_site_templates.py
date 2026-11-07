import base64
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from builtin_tools import palette, projects
from builtin_tools import site_templates as st

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
SVG_VOID_OK = {'path', 'circle', 'rect', 'line', 'polygon', 'stop'}  # may be self-closed inside inline SVG


class Page(HTMLParser):
    """Collects structure and checks that every element is closed in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.tags, self.ids = [], [], [], []
        self.attrs, self.text = [], []
        self.html_lang = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        self.attrs.append((tag, a))
        if 'id' in a:
            self.ids.append(a['id'])
        if tag == 'html':
            self.html_lang = a.get('lang')
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        self.attrs.append((tag, a))
        if 'id' in a:
            self.ids.append(a['id'])
        if tag not in VOID and tag not in SVG_VOID_OK:
            self.errors.append(f'self-closed <{tag}/>')

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f'unexpected </{tag}> (open: {self.stack[-3:]})')
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def parse(text):
    page = Page()
    page.feed(text)
    page.close()
    return page


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = Path(self.tmp.name) / 'build-projects'
        p = patch.object(projects, 'PROJECTS', self.projects)
        p.start()
        self.addCleanup(p.stop)
        # Never start a browser in tests; the tool must cope with capture failing.
        import preview_capture
        c = patch.object(preview_capture, 'capture', side_effect=ValueError('no browser in tests'))
        c.start()
        self.addCleanup(c.stop)

    def make(self, **args):
        result = st.call('new_site', args)
        self.assertFalse(result.get('isError'), result)
        return result


class TemplateOutputTests(Sandbox):
    SECTIONS = {
        'landing': ['Real-time dashboards', 'No cookies', 'API access'],
        'portfolio': ['Fintech app', 'Museum site', 'Brand book'],
        'blog': ['Hello world', 'Second thoughts'],
        'link_in_bio': ['YouTube', 'Shop', 'Newsletter'],
        'docs': ['Installation', 'Configuration', 'Deploying'],
    }

    def check_project(self, root, template):
        files = {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file()}
        for required in ('index.html', 'styles.css', 'script.js', 'favicon.svg', 'PROJECT_BRIEF.md'):
            self.assertIn(required, files)
        if template == 'blog':
            self.assertIn('posts/first-post.html', files)
        if template == 'docs':
            self.assertGreaterEqual(sum(1 for f in files if f.endswith('.html')), 3)
        css = files['styles.css'].read_text(encoding='utf-8')
        for token in ('--bg', '--surface', '--text', '--muted', '--accent', '--accent-contrast'):
            self.assertIn(token + ':', css)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn(':focus-visible', css)
        self.assertNotRegex(css, r'@import|url\(\s*["\']?(https?:)?//')
        self.assertNotRegex(files['script.js'].read_text(encoding='utf-8'), r'https?://')
        favicon = files['favicon.svg'].read_text(encoding='utf-8')
        self.assertTrue(favicon.startswith('<svg') and favicon.rstrip().endswith('</svg>'))
        brief = files['PROJECT_BRIEF.md'].read_text(encoding='utf-8')
        for heading in ('## File map', '## Design tokens', '## How to add a section', '## How to add a page', '## Rules'):
            self.assertIn(heading, brief)
        for rel in files:
            if rel.endswith('.html'):
                self.check_page(root, rel, files[rel].read_text(encoding='utf-8'))

    def check_page(self, root, rel, text):
        page = parse(text)
        where = f'{root.name}/{rel}'
        self.assertEqual(page.errors, [], where)
        self.assertEqual(page.stack, [], where)
        self.assertTrue(text.startswith('<!doctype html>'), where)
        self.assertEqual(page.html_lang, 'en', where)
        self.assertEqual(page.tags.count('h1'), 1, where)
        for landmark in ('header', 'nav', 'main', 'footer'):
            self.assertIn(landmark, page.tags, f'{where} lacks <{landmark}>')
        self.assertEqual(page.tags.count('main'), 1, where)
        metas = [a for t, a in page.attrs if t == 'meta']
        names = {a.get('name') or a.get('property') for a in metas}
        for meta in ('viewport', 'description', 'og:title', 'og:description'):
            self.assertIn(meta, names, where)
        self.assertTrue(any(a.get('charset') for a in metas), where)
        self.assertIn('title', page.tags, where)
        icons = [a for t, a in page.attrs if t == 'link' and a.get('rel') == 'icon']
        self.assertEqual(len(icons), 1, where)
        self.assertTrue(icons[0]['href'].endswith('favicon.svg'))
        for tag, a in page.attrs:
            if tag == 'img':
                self.assertIn('alt', a, where)
        self.assertEqual(len(page.ids), len(set(page.ids)), f'duplicate ids in {where}')
        # Skip link first, pointing at main.
        first_a = next(a for t, a in page.attrs if t == 'a')
        self.assertEqual(first_a.get('href'), '#main')
        mains = [a for t, a in page.attrs if t == 'main']
        self.assertEqual(mains[0].get('id'), 'main')
        # No external assets; every local reference exists.
        base = (root / rel).parent
        for tag, a in page.attrs:
            for attr in ('href', 'src'):
                ref = a.get(attr)
                if ref is None:
                    continue
                if re.match(r'(https?:)?//', ref):
                    self.assertEqual(tag, 'a', f'external asset {ref} in {where}')
                    self.assertRegex(ref, r'^https://example\.com/', where)
                    continue
                if ref.startswith('mailto:'):
                    continue
                path, _, frag = ref.partition('#')
                if not path:
                    self.assertIn(frag, page.ids, f'{where}: missing #{frag}')
                    continue
                target = (base / path).resolve()
                self.assertTrue(target.is_file(), f'{where}: missing {ref}')
                self.assertIn(root.resolve(), target.parents)
                if frag:
                    self.assertIn(f'id="{frag}"', target.read_text(encoding='utf-8'), f'{where}: missing {ref}')
            if tag == 'svg' and a.get('aria-hidden') != 'true':
                self.assertEqual(a.get('role'), 'img', f'{where}: unlabeled svg')
        self.assertNotRegex(text, r'style="[^"]*url\(')

    def test_every_template_and_theme(self):
        for template in st.TEMPLATES:
            for theme in st.THEMES:
                for with_sections in (False, True):
                    with self.subTest(template=template, theme=theme, sections=with_sections):
                        name = f'{template.replace("_", "-")}-{theme}-{int(with_sections)}'
                        args = dict(template=template, site_title=f'Test {template}', theme=theme, project_name=name,
                                    tagline='A tagline for testing.', color='#ff6b8a')
                        if with_sections:
                            args['sections'] = self.SECTIONS[template]
                        result = self.make(**args)
                        text = result['content'][0]['text']
                        self.assertIn(f'Open it in Build → {name} → Preview', text)
                        self.check_project(self.projects / name, template)

    def test_sections_fill_slots(self):
        self.make(template='landing', site_title='Nova', sections=['Zebra mode', 'Quantum sync'])
        html = (self.projects / 'nova' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('Zebra mode', html)
        self.assertIn('Quantum sync', html)
        self.make(template='blog', site_title='Notes', sections=['Hello world', 'Second post'])
        self.assertTrue((self.projects / 'notes' / 'posts' / 'first-post.html').is_file())
        self.assertTrue((self.projects / 'notes' / 'posts' / 'second-post.html').is_file())
        self.make(template='docs', site_title='Kit', sections=['Introduction', 'Install guide', 'API'])
        names = sorted(p.name for p in (self.projects / 'kit').glob('*.html'))
        self.assertEqual(names, ['api.html', 'index.html', 'install-guide.html'])
        sidebar_pages = (self.projects / 'kit' / 'api.html').read_text(encoding='utf-8')
        self.assertIn('href="install-guide.html"', sidebar_pages)

    def test_placeholder_copy_reads_as_sample(self):
        self.make(template='portfolio', site_title='Maya')
        html = (self.projects / 'maya' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('Describe this project here', html)
        self.assertNotIn('lorem', html.lower())


class ThemeTests(unittest.TestCase):
    COLORS = ['#2ff3d0', '#ffff00', '#000080', '#ffffff', '#000000', '#808080', 'coral', 'rgb(255, 0, 0)',
              'hsl(270, 80%, 50%)', '#0f0', '#6d4aff', '#ff6b8a', '#1e90ff', '#8b4513']

    def test_all_text_pairs_pass_aa(self):
        for color in self.COLORS:
            for theme in st.THEMES:
                with self.subTest(color=color, theme=theme):
                    tokens = st.build_theme(color, theme)
                    for fg, bg, ratio in st.theme_report(tokens):
                        self.assertGreaterEqual(ratio, 4.5, f'{fg} on {bg} = {ratio:.2f} for {color} {theme}')

    def test_css_tokens_match_theme(self):
        tokens = st.build_theme('#6d4aff', 'light')
        css = st.tokens_css(tokens, 'light')
        for key, value in tokens.items():
            self.assertIn(f'--{key}: {palette.hex_of(value)};', css)
        self.assertIn('color-scheme: light', css)
        self.assertGreater(palette.luminance(tokens['bg']), 0.8)
        self.assertLess(palette.luminance(st.build_theme('#6d4aff', 'dark')['bg']), 0.02)

    def test_brand_kept_when_it_already_passes(self):
        tokens = st.build_theme('#2ff3d0', 'dark')
        self.assertEqual(tokens['accent'], (47, 243, 208))
        self.assertEqual(tokens['brand'], (47, 243, 208))


class NamingAndInputTests(Sandbox):
    def test_default_name_and_collision_suffix(self):
        self.make(template='landing', site_title='Jazz Guitar Site!')
        self.assertTrue((self.projects / 'jazz-guitar-site').is_dir())
        result = self.make(template='landing', site_title='Jazz Guitar Site!')
        self.assertIn('"jazz-guitar-site-2"', result['content'][0]['text'])
        self.make(template='portfolio', site_title='x', project_name='jazz-guitar-site')
        self.assertTrue((self.projects / 'jazz-guitar-site-3').is_dir())
        for n in range(4, 10):
            self.make(template='landing', site_title='Jazz Guitar Site')
        self.assertTrue((self.projects / 'jazz-guitar-site-9').is_dir())
        result = st.call('new_site', {'template': 'landing', 'site_title': 'Jazz Guitar Site'})
        self.assertTrue(result['isError'])
        self.assertIn('project_name', result['content'][0]['text'])

    def test_existing_projects_never_overwritten(self):
        projects.write_files('mine', {'index.html': 'KEEP'})
        self.make(template='blog', site_title='Mine')
        self.assertEqual((self.projects / 'mine' / 'index.html').read_text(), 'KEEP')
        self.assertTrue((self.projects / 'mine-2' / 'posts' / 'first-post.html').is_file())

    def test_invalid_inputs(self):
        bad = [
            ({'site_title': 'X'}, 'template'),
            ({'template': 'shop', 'site_title': 'X'}, 'template'),
            ({'template': 'landing'}, 'site_title'),
            ({'template': 'landing', 'site_title': '   '}, 'site_title'),
            ({'template': 'landing', 'site_title': 'x' * 61}, 'too long'),
            ({'template': 'landing', 'site_title': 'X', 'tagline': 'y' * 141}, 'too long'),
            ({'template': 'landing', 'site_title': 'X', 'theme': 'neon'}, 'theme'),
            ({'template': 'landing', 'site_title': 'X', 'color': 'blurple'}, 'colour'),
            ({'template': 'landing', 'site_title': 'X', 'color': 5}, 'color'),
            ({'template': 'landing', 'site_title': 'X', 'sections': 'a,b'}, 'list'),
            ({'template': 'landing', 'site_title': 'X', 'sections': ['a'] * 9}, 'at most'),
            ({'template': 'landing', 'site_title': 'X', 'sections': ['a' * 61]}, 'at most'),
            ({'template': 'landing', 'site_title': 'X', 'sections': [3]}, 'text'),
            ({'template': 'landing', 'site_title': 'X', 'project_name': '../evil'}, 'project_name'),
            ({'template': 'landing', 'site_title': 'X', 'project_name': 'Bad Name'}, 'project_name'),
            ({'template': 'landing', 'site_title': 'X', 'extra': 1}, 'Unexpected'),
        ]
        for args, needle in bad:
            with self.subTest(args=args):
                result = st.call('new_site', args)
                self.assertTrue(result.get('isError'))
                self.assertIn(needle, result['content'][0]['text'])
        self.assertTrue(st.call('other_tool', {})['isError'])
        self.assertTrue(st.call('new_site', ['landing'])['isError'])
        self.assertFalse(self.projects.exists() and any(self.projects.iterdir()))

    def test_lenient_enums_and_defaults(self):
        self.make(template='Link-in-bio', site_title='Kai', theme='LIGHT')
        css = (self.projects / 'kai' / 'styles.css').read_text(encoding='utf-8')
        self.assertIn('color-scheme: light', css)
        self.make(template='landing', site_title='Def')
        css = (self.projects / 'def' / 'styles.css').read_text(encoding='utf-8')
        self.assertIn('--brand: #2FF3D0;', css)
        self.assertIn('color-scheme: dark', css)

    def test_user_text_is_escaped(self):
        evil = '<script>alert(1)</script> & "q"'
        for template in st.TEMPLATES:
            with self.subTest(template=template):
                name = 'esc-' + template.replace('_', '-')
                self.make(template=template, site_title=evil, tagline='<img src=x onerror=alert(1)>',
                          sections=['<b>bold</b>', 'ok'], project_name=name)
                for path in (self.projects / name).rglob('*'):
                    if path.suffix in ('.html', '.svg'):
                        text = path.read_text(encoding='utf-8')
                        self.assertNotIn('<script>alert', text)
                        self.assertNotIn('<img src=x', text)
                        self.assertNotIn('<b>bold', text)
                        if path.suffix == '.html':
                            self.assertIn('&lt;script&gt;', text)
                            self.assertEqual(parse(text).errors, [])

    def test_screenshot_attached_when_capture_works(self):
        fake = {'images': [{'type': 'image', 'mime': 'image/jpeg', 'name': 'desktop-preview.jpg',
                            'data': base64.b64encode(b'jpg').decode()},
                           {'type': 'image', 'mime': 'image/jpeg', 'name': 'mobile-preview.jpg', 'data': 'eA=='}]}
        import preview_capture
        with patch.object(preview_capture, 'capture', return_value=fake) as capture:
            result = self.make(template='landing', site_title='Shot')
        capture.assert_called_once()
        self.assertEqual(Path(capture.call_args[0][0]).name, 'shot')
        self.assertEqual(capture.call_args[0][1], 'index.html')
        images = [c for c in result['content'] if c['type'] == 'image']
        self.assertEqual(images, [{'type': 'image', 'mimeType': 'image/jpeg', 'data': fake['images'][0]['data']}])

    def test_capture_failure_still_creates_site(self):
        import preview_capture
        with patch.object(preview_capture, 'capture', side_effect=RuntimeError('boom')):
            result = self.make(template='docs', site_title='Docs Site')
        self.assertEqual([c['type'] for c in result['content']], ['text'])
        self.assertTrue((self.projects / 'docs-site' / 'index.html').is_file())

    def test_tool_schema(self):
        tool = st.TOOLS[0]
        self.assertEqual(tool['name'], 'new_site')
        schema = tool['inputSchema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['required'], ['template', 'site_title'])
        self.assertEqual(schema['properties']['template']['enum'], list(st.TEMPLATES))
        self.assertEqual(schema['properties']['sections']['maxItems'], 8)


if __name__ == '__main__':
    unittest.main()
