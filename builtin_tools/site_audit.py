"""Website audit for DreadOS Build projects: a deterministic, read-only checklist to fix from.

Static analysis only (stdlib html.parser + small regex CSS parser). Never modifies files, never
fetches anything: external URLs are listed, not requested. File access goes through
builtin_tools.projects (validated project folder, read-only).

    audit(name, page=None) -> {'project', 'pages', 'score', 'counts', 'issues', 'stats'}

raises AuditError (a ValueError) with a friendly message for unknown projects, projects without
HTML and unsafe/missing `page` values.
"""
import bisect
import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import unquote

from . import projects
from .palette import NAMES, PaletteError, contrast, hex_of, parse_color

MAX_PAGES = 50
MAX_FILES = 2000
MAX_REPORT_ISSUES = 60
MAX_ISSUES = 1000
MAX_HTML_BYTES = 2_000_000
MAX_CSS_BYTES = 1_000_000
IMAGE_WARN = 300 * 1024
IMAGE_ERROR = 1024 * 1024
PAGE_WEIGHT_WARN = 2 * 1024 * 1024
INLINE_STYLE_LIMIT = 10
WEIGHTS = {'error': 8, 'warning': 3, 'info': 0}
SEVERITIES = ('error', 'warning', 'info')

IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.svg', '.bmp', '.ico')
SOURCE_EXT = ('.jsx', '.tsx', '.ts', '.vue', '.svelte')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
CAPTURE = {'a', 'button', 'label', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
DEPRECATED = {'center', 'font', 'marquee', 'blink', 'big', 'strike', 'tt', 'acronym', 'applet', 'frame', 'frameset'}
NO_LABEL_INPUTS = {'hidden', 'submit', 'button', 'reset', 'image'}
BUILD_ROOTS = {'dist', 'build', 'out', '_site'}

TOOLS = [{
    'name': 'audit_site',
    'description': ('Audit a DreadOS Build website project (read-only) and get a precise checklist to fix: '
                    'SEO (title, meta description, Open Graph), accessibility (lang, alt text, labels, headings, '
                    'link/button text, colour contrast), broken internal links/anchors, missing CSS/JS/images, '
                    'oversized images, page weight, external CDN use. Returns a score 0-100 and issues as '
                    'file:line - message -> fix. Pass project (the Build project name) and optionally page '
                    '(one .html file, e.g. "about.html" or "dist/index.html" for built framework apps).'),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'project': {'type': 'string', 'minLength': 1, 'maxLength': 50,
                        'description': 'Build project name (lowercase letters, digits, hyphens), e.g. "jazz-portfolio".'},
            'page': {'type': 'string', 'maxLength': 240,
                     'description': 'Optional: audit only this .html file (project-relative path).'},
        },
        'required': ['project'],
        'additionalProperties': False,
    },
    'returnsImage': False,
}]


class AuditError(ValueError):
    pass


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': str(message)[:2000]}]}


# ---------------------------------------------------------------- HTML parsing

class _Capture:
    __slots__ = ('tag', 'attrs', 'line', 'text', 'in_label')

    def __init__(self, tag, attrs, line):
        self.tag, self.attrs, self.line, self.text, self.in_label = tag, attrs, line, [], False


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_lines = {}
        self.lang = None
        self.title = None            # (text, line)
        self.metas = []              # (attrs, line)
        self.links = []              # <link> (attrs, line)
        self.headings = []           # (level, line, text)
        self.imgs = []               # (attrs, line)
        self.anchors = []            # (attrs, line, text)
        self.buttons = []            # (attrs, line, text)
        self.inputs = []             # (tag, attrs, line, inside_label)
        self.label_for = set()
        self.ids = {}                # id -> first line
        self.names = set()           # <a name=...> targets
        self.dup_ids = []            # (id, line, first_line)
        self.scripts = []            # (attrs, line)
        self.media = []              # (tag, attrs, line) for source/video/audio/input[type=image]
        self.styles = []             # [css text, start line]
        self.inline_styles = []      # lines
        self.deprecated = []         # (tag, line)
        self._stack = []
        self._svg = 0
        self._raw = None             # 'style' | 'script' while inside one
        self.text_chars = 0          # visible text characters (outside script/style/title)

    # helpers
    def _line(self):
        return self.getpos()[0]

    def _add_text(self, text):
        for cap in self._stack:
            cap.text.append(text)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else '') for k, v in attrs}
        line = self._line()
        self.tag_lines.setdefault(tag, line)
        ident = a.get('id', '').strip()
        if ident:
            if ident in self.ids:
                self.dup_ids.append((ident, line, self.ids[ident]))
            else:
                self.ids[ident] = line
        if 'style' in a and a['style'].strip():
            self.inline_styles.append(line)
        if self._stack and tag not in CAPTURE:
            label = a.get('aria-label', '').strip() or (a.get('alt', '').strip() if tag == 'img' else '')
            if label:
                self._add_text(' ' + label + ' ')
        if tag in DEPRECATED:
            self.deprecated.append((tag, line))
        if tag == 'svg':
            self._svg += 1
        elif tag == 'html':
            self.lang = a.get('lang', '').strip()
        elif tag == 'meta':
            self.metas.append((a, line))
        elif tag == 'link':
            self.links.append((a, line))
        elif tag == 'img':
            self.imgs.append((a, line))
        elif tag == 'script':
            self.scripts.append((a, line))
            self._raw = 'script'
        elif tag == 'style':
            self._raw = 'style'
            self.styles.append(['', None])
        elif tag == 'a' and 'name' in a:
            self.names.add(a['name'].strip())
        elif tag in ('source', 'video', 'audio'):
            self.media.append((tag, a, line))
        if tag in ('input', 'select', 'textarea'):
            inside = any(c.tag == 'label' for c in self._stack)
            self.inputs.append((tag, a, line, inside))
            if tag == 'input' and a.get('type', '').lower() == 'image':
                self.media.append(('input', a, line))
        if tag == 'label' and a.get('for', '').strip():
            self.label_for.add(a['for'].strip())
        if tag in CAPTURE and not (tag == 'title' and self._svg):
            self._stack.append(_Capture(tag, a, line))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'svg' and self._svg:
            self._svg -= 1
        if tag in ('script', 'style'):
            self._raw = None
        if tag in CAPTURE and not (tag == 'title' and self._svg):
            for i in range(len(self._stack) - 1, -1, -1):
                if self._stack[i].tag == tag:
                    for cap in reversed(self._stack[i:]):
                        self._finish(cap)
                    del self._stack[i:]
                    break

    def handle_data(self, data):
        if self._raw == 'style':
            block = self.styles[-1]
            if block[1] is None:
                block[1] = self._line()
            block[0] += data
            return
        if self._raw == 'script':
            return
        if not (self._stack and self._stack[-1].tag == 'title'):
            self.text_chars += len(data.strip())
        if self._stack:
            self._add_text(data)

    def close(self):
        super().close()
        for cap in reversed(self._stack):
            self._finish(cap)
        self._stack = []

    def _finish(self, cap):
        text = ' '.join(''.join(cap.text).split())
        tag = cap.tag
        if tag == 'title':
            if self.title is None:
                self.title = (text, cap.line)
        elif tag == 'a':
            self.anchors.append((cap.attrs, cap.line, text))
        elif tag == 'button':
            self.buttons.append((cap.attrs, cap.line, text))
        elif tag[0] == 'h':
            self.headings.append((int(tag[1]), cap.line, text))
        # labels only matter through label_for / in_label


def _parse_html(text):
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # html.parser is lenient; never let odd markup crash the audit
        pass
    parser.headings.sort(key=lambda h: h[1])
    parser.anchors.sort(key=lambda h: h[1])
    parser.buttons.sort(key=lambda h: h[1])
    return parser


# ---------------------------------------------------------------- CSS parsing

_COMMENT = re.compile(r'/\*.*?\*/', re.S)
_URL = re.compile(r'url\(\s*([\'"]?)([^\'")]*)\1\s*\)', re.I)
_IMPORT = re.compile(r'@import\s+([\'"])([^\'"]+)\1', re.I)


def _blank_comments(css):
    return _COMMENT.sub(lambda m: re.sub(r'[^\n]', ' ', m.group()), css)


def _line_finder(text, offset):
    newlines = [i for i, ch in enumerate(text) if ch == '\n']
    return lambda pos: bisect.bisect_left(newlines, pos) + offset


def _parse_css(css, first_line=1):
    """{'rules': [(selector, {prop: (value, line)}, line, context)], 'urls': [(url, line)], 'imports': [...]}"""
    css = _blank_comments(css)
    line_of = _line_finder(css, first_line)
    rules, stack = [], []
    last, leaf_open = 0, None
    for m in re.finditer(r'[{}]', css):
        i = m.start()
        if m.group() == '{':
            prelude = css[last:i]
            stripped = prelude.lstrip()
            stack.append((stripped.strip(), last + (len(prelude) - len(stripped))))
            leaf_open = i
        else:
            if not stack:
                last = i + 1
                continue
            prelude, start = stack.pop()
            if leaf_open is not None and leaf_open > start:
                body_start = leaf_open + 1
                decls = {}
                pos = body_start
                for part in css[body_start:i].split(';'):
                    if ':' in part:
                        prop, _, value = part.partition(':')
                        prop = prop.strip().lower()
                        lead = len(part) - len(part.lstrip())
                        if prop:
                            decls[prop] = (value.strip(), line_of(pos + lead))
                    pos += len(part) + 1
                context = ' '.join(p for p, _ in stack)
                if prelude and not prelude.startswith('@'):
                    rules.append((' '.join(prelude.split()), decls, line_of(start), context))
            leaf_open = None
        last = i + 1
    urls = [(m.group(2).strip(), line_of(m.start())) for m in _URL.finditer(css) if m.group(2).strip()]
    imports = [(m.group(2).strip(), line_of(m.start())) for m in _IMPORT.finditer(css)]
    return {'rules': rules, 'urls': urls, 'imports': imports}


# ---------------------------------------------------------------- colours

_VAR = re.compile(r'var\(\s*(--[\w-]+)\s*(?:,\s*((?:[^()]|\([^()]*\))*))?\)')
_HEX = re.compile(r'#([0-9a-f]{3,8})')
_BG_KEYWORDS = {'no-repeat', 'repeat', 'repeat-x', 'repeat-y', 'space', 'round', 'center', 'top', 'left', 'right',
                'bottom', 'fixed', 'scroll', 'local', 'cover', 'contain', 'auto', 'padding-box', 'border-box',
                'content-box', 'none'}


def _resolve_vars(value, variables):
    for _ in range(6):
        if 'var(' not in value:
            return value
        missing = []

        def sub(m):
            name, fallback = m.group(1), m.group(2)
            if name in variables:
                return variables[name]
            if fallback is not None:
                return fallback
            missing.append(name)
            return ''
        value = _VAR.sub(sub, value)
        if missing:
            return None
    return None if 'var(' in value else value


def _clean(value):
    return re.sub(r'\s*!important\s*$', '', value.strip(), flags=re.I).strip().lower()


def _solid(value):
    """(r, g, b) for an opaque colour, None for anything else (transparent, unknown names, keywords...)."""
    if not value:
        return None
    m = _HEX.fullmatch(value)
    if m:
        digits = m.group(1)
        if len(digits) == 4:
            if digits[3] != 'f':
                return None
            digits = digits[:3]
        elif len(digits) == 8:
            if digits[6:] != 'ff':
                return None
            digits = digits[:6]
        elif len(digits) not in (3, 6):
            return None
        return parse_color('#' + digits)
    if value.startswith(('rgb', 'hsl')):
        alpha = re.search(r'(?:,|/)\s*([\d.]+)(%?)\s*\)$', value)
        commas = value.count(',')
        if alpha and (value.count('/') or commas == 3):
            number = float(alpha.group(1)) / (100 if alpha.group(2) else 1)
            if number < 1:
                return None
    elif not re.fullmatch(r'[a-z]+', value) or value not in NAMES:
        return None
    try:
        return parse_color(value)
    except (PaletteError, ValueError):
        return None


def _fg(value, variables):
    resolved = _resolve_vars(_clean(value), variables)
    return _solid(resolved) if resolved else None


def _bg(value, variables):
    """('color', rgb) | ('none', None) | ('unknown', None)"""
    resolved = _resolve_vars(_clean(value), variables)
    if resolved is None:
        return 'unknown', None
    if resolved in ('none', 'transparent'):
        return 'none', None
    if any(word in resolved for word in ('url(', 'gradient', 'image-set', 'element(')):
        return 'unknown', None
    rgb = _solid(resolved)
    if rgb:
        return 'color', rgb
    colours, other = [], False
    for token in re.findall(r'#[0-9a-f]{3,8}\b|(?:rgba?|hsla?)\([^)]*\)|[a-z][a-z-]*|\S+', resolved):
        if token.startswith(('#', 'rgb', 'hsl')) or token in NAMES or token == 'transparent':
            colours.append(token)
        elif token not in _BG_KEYWORDS and not re.fullmatch(r'[-\d.]+(px|%|em|rem|vh|vw)?|/', token):
            other = True
    if other or len(colours) != 1:
        return 'unknown', None
    if colours[0] == 'transparent':
        return 'none', None
    rgb = _solid(colours[0])
    return ('color', rgb) if rgb else ('unknown', None)


def _is_large(selector, decls):
    size = decls.get('font-size', ('', 0))[0].lower()
    weight = decls.get('font-weight', ('', 0))[0].lower()
    bold = weight in ('bold', 'bolder') or (weight.isdigit() and int(weight) >= 700)
    m = re.fullmatch(r'([\d.]+)(px|rem|em|pt)', size)
    if m:
        px = float(m.group(1)) * {'px': 1, 'rem': 16, 'em': 16, 'pt': 4 / 3}[m.group(2)]
        return px >= 24 or (bold and px >= 18.66)
    if size:
        return False
    parts = [p.strip() for p in selector.split(',')]
    return all(p in ('h1', 'h2', 'h3') for p in parts)


def _suggest(fg, bg, target):
    """Nearest text colour (mixing toward black or white) that reaches the target ratio."""
    toward = (0, 0, 0) if contrast((0, 0, 0), bg) >= contrast((255, 255, 255), bg) else (255, 255, 255)
    for step in range(1, 21):
        t = step / 20
        mixed = tuple(int(round(c + (o - c) * t)) for c, o in zip(fg, toward))
        if contrast(mixed, bg) >= target:
            return hex_of(mixed)
    return hex_of(toward)


# ---------------------------------------------------------------- the audit

def _rel_tokens(value):
    return set(value.lower().split())


def _split_url(url):
    """('external', url) | ('scheme', name) | ('local', path, fragment) | ('empty',)."""
    url = url.strip()
    if not url:
        return ('empty',)
    low = url.lower()
    if low.startswith(('http://', 'https://', '//')):
        return ('external', url)
    m = re.match(r'([a-z][a-z0-9+.-]*):', low)
    if m:
        return ('scheme', m.group(1))
    path, _, fragment = url.partition('#')
    path = unquote(path.split('?', 1)[0]).replace('\\', '/')
    return ('local', path, unquote(fragment))


class _Audit:
    def __init__(self, name):
        self.name = name
        self.root = projects.project_dir(name)
        self.root_resolved = self.root.resolve()
        self.files = {}
        for rel, path in projects.iter_files(name, max_files=MAX_FILES):
            self.files[rel] = path
        self.lower = {}
        for rel in self.files:
            self.lower.setdefault(rel.lower(), rel)
        self.vite = 'package.json' in self.files
        self.issues = {}
        self.parsed = {}
        self.css_cache = {}
        self.size_cache = {}
        self.checked_images = set()
        self.external_links = set()
        self.external_assets = set()
        self.contact_links = set()
        self.page_weights = {}
        self.links_checked = 0
        self.assets_checked = 0

    # -- helpers
    def add(self, severity, check, file, line, message, fix):
        key = (check, file, line, message)
        if key not in self.issues and len(self.issues) < MAX_ISSUES:
            self.issues[key] = {'severity': severity, 'check': check, 'file': file, 'line': line,
                                'message': message, 'fix': fix}

    def exists(self, rel):
        """'ok' | ('case', actual) | None — read-only lookup inside the project."""
        if rel in self.files:
            return 'ok'
        actual = self.lower.get(rel.lower())
        if actual:
            return ('case', actual)
        if not rel or rel.startswith('..'):
            return None
        try:
            path = self.root / rel
            resolved = path.resolve()
            if (self.root_resolved in resolved.parents and resolved.is_file()
                    and not path.is_symlink() and not resolved.is_symlink()):
                return 'ok'
        except (OSError, ValueError):
            pass
        return None

    def size(self, rel):
        if rel not in self.size_cache:
            path = self.files.get(rel) or (self.root / rel)
            try:
                self.size_cache[rel] = path.stat().st_size
            except OSError:
                self.size_cache[rel] = 0
        return self.size_cache[rel]

    def read(self, rel, limit):
        try:
            return projects.read_text(self.name, rel, limit=limit)
        except (projects.ProjectError, OSError):
            return None

    def site_root(self, page):
        first = page.split('/', 1)[0]
        return first if '/' in page and first in BUILD_ROOTS else ''

    def resolve(self, base_file, path, site_root):
        """(found rel or None, wanted rel or None if it escapes the project)."""
        if path.startswith('/'):
            base, rest = site_root, path.lstrip('/')
        else:
            base, rest = posixpath.dirname(base_file), path
        dir_intent = rest == '' or rest.endswith('/') or rest in ('.', '..') or rest.endswith(('/.', '/..'))
        joined = posixpath.normpath(posixpath.join(base, rest)) if (base or rest) else '.'
        if joined == '..' or joined.startswith('../') or joined.startswith('/'):
            return None, None
        joined = '' if joined == '.' else joined
        if dir_intent or not joined:
            candidates = [posixpath.join(joined, 'index.html') if joined else 'index.html']
        else:
            candidates = [joined]
            if '.' not in posixpath.basename(joined):
                candidates += [joined + '.html', joined + '/index.html']
        if path.startswith('/') and not site_root and self.vite:
            candidates += ['public/' + c for c in candidates]
        for cand in candidates:
            found = self.exists(cand)
            if found == 'ok':
                return cand, candidates[0]
            if found:
                return found, candidates[0]
        return None, candidates[0]

    def check_asset(self, page, line, url, kind, site_root, weight=None, origin=None):
        """Verify one referenced asset. Returns the project-relative path when it exists."""
        parts = _split_url(url)
        if parts[0] == 'external':
            if kind in ('script', 'stylesheet'):
                self.external_assets.add(parts[1])
                what = 'script' if kind == 'script' else 'stylesheet'
                self.add('info', 'external-asset', page, line,
                         f'External {what} {parts[1][:120]} works online only; DreadOS preview blocks external requests.',
                         'Download it into the project (e.g. vendor/) and reference the local copy if it must work offline.')
            return None
        if parts[0] != 'local' or not parts[1]:
            return None
        self.assets_checked += 1
        found, wanted = self.resolve(origin or page, parts[1], site_root)
        if wanted is None:
            self.add('error', 'missing-asset', page, line, f'{kind.capitalize()} "{url[:120]}" points outside the project.',
                     'Copy the file into the project and use a path inside it.')
            return None
        if found is None:
            self.add('error', 'missing-asset', page, line, f'Missing {kind}: "{url[:120]}" (looked for {wanted}).',
                     f'Create {wanted} or fix the path.')
            return None
        if isinstance(found, tuple):
            actual = found[1]
            self.add('warning', 'path-case', page, line,
                     f'"{url[:120]}" only matches {actual} with different letter case.',
                     f'Use the exact name {actual}; Linux web hosts are case-sensitive.')
            found = actual
        if weight is not None:
            weight.add(found)
        if found.lower().endswith(IMAGE_EXT):
            self.check_image_size(found, page, line)
        return found

    def check_image_size(self, rel, page, line):
        if rel in self.checked_images:
            return
        self.checked_images.add(rel)
        size = self.size(rel)
        where = f' (used by {page}:{line})'
        if size > IMAGE_ERROR:
            self.add('error', 'image-size', rel, None, f'Image is {size / 1048576:.1f} MB{where}.',
                     'Resize to the displayed size and compress (WebP/AVIF or quality ~80 JPEG); aim under 300 KB.')
        elif size > IMAGE_WARN:
            self.add('warning', 'image-size', rel, None, f'Image is {size // 1024} KB{where}.',
                     'Resize/compress it (WebP/AVIF) to under 300 KB.')

    def css(self, rel):
        if rel not in self.css_cache:
            text = self.read(rel, MAX_CSS_BYTES)
            self.css_cache[rel] = _parse_css(text) if text is not None else None
        return self.css_cache[rel]

    def page_ids(self, rel):
        if rel not in self.parsed:
            if len(self.parsed) > MAX_PAGES * 2:
                return None
            text = self.read(rel, MAX_HTML_BYTES)
            self.parsed[rel] = _parse_html(text) if text is not None else None
        parsed = self.parsed[rel]
        return None if parsed is None else (set(parsed.ids) | parsed.names)

    # -- stylesheet handling (assets + contrast)
    def load_sheets(self, page, doc, site_root, weight):
        """Ordered [(file label, parsed css)] for a page, checking url()/@import references."""
        items = []
        for attrs, line in doc.links:
            if 'stylesheet' in _rel_tokens(attrs.get('rel', '')) and attrs.get('href', '').strip():
                items.append((line, 'link', attrs['href']))
        for css_text, line in doc.styles:
            items.append((line or 1, 'style', css_text))
        items.sort(key=lambda x: x[0])
        sheets = []
        for line, kind, value in items:
            if kind == 'style':
                parsed = _parse_css(value, line)
                sheets.append((page, parsed))
                self.css_refs(page, page, parsed, site_root, weight, sheets, set())
            else:
                rel = self.check_asset(page, line, value, 'stylesheet', site_root, weight)
                if rel:
                    self.add_sheet(rel, page, site_root, weight, sheets, set())
        return sheets

    def add_sheet(self, rel, page, site_root, weight, sheets, seen):
        if rel in seen or len(seen) > 20:
            return
        seen.add(rel)
        parsed = self.css(rel)
        if parsed is None:
            return
        self.css_refs(rel, rel, parsed, site_root, weight, sheets, seen)
        sheets.append((rel, parsed))

    def css_refs(self, label, origin, parsed, site_root, weight, sheets, seen):
        imported = set()
        for url, line in parsed['imports']:
            imported.add(url)
            rel = self.check_asset(label, line, url, 'stylesheet', site_root, weight, origin=origin)
            if rel:
                self.add_sheet(rel, label, site_root, weight, sheets, seen)
        for url, line in parsed['urls']:
            if url in imported or url.startswith('#'):
                continue
            lower = url.split('?')[0].lower()
            kind = 'font' if lower.endswith(('.woff', '.woff2', '.ttf', '.otf', '.eot')) else (
                'stylesheet' if lower.endswith('.css') else 'image')
            rel = self.check_asset(label, line, url, kind, site_root, weight, origin=origin)
            if rel and kind == 'stylesheet':
                self.add_sheet(rel, label, site_root, weight, sheets, seen)

    def contrast_checks(self, sheets, has_text=True):
        root_vars, media_vars = {}, {}
        for _, parsed in sheets:
            for selector, decls, _, context in parsed['rules']:
                parts = [p.strip() for p in selector.split(',')]
                if all(p in (':root', 'html', 'body') for p in parts):
                    target = root_vars if not context else media_vars.setdefault(context, {})
                    for prop, (value, _) in decls.items():
                        if prop.startswith('--'):
                            target[prop] = value.strip()
        body = {'color': None, 'bg': None}  # (value, file, line, rule_id)
        styled = {'color': False, 'bg': False}  # other rules set text colour / backgrounds
        for file, parsed in sheets:
            for index, (selector, decls, line, context) in enumerate(parsed['rules']):
                if 'keyframes' in context or ':disabled' in selector or '[disabled]' in selector:
                    continue
                variables = dict(root_vars, **media_vars.get(context, {})) if context else root_vars
                rule_id = (file, index)
                parts = [p.strip() for p in selector.split(',')]
                if not any(p in ('html', 'body', ':root') for p in parts):
                    styled['color'] |= 'color' in decls
                    styled['bg'] |= 'background' in decls or 'background-color' in decls
                if not context:
                    for p in ('html', 'body'):
                        if p in parts:
                            if 'color' in decls:
                                body['color'] = (decls['color'], file, rule_id, variables)
                            bg = decls.get('background-color') or decls.get('background')
                            if bg:
                                body['bg'] = (bg, file, rule_id, variables)
                if 'color' not in decls or 'opacity' in decls:
                    continue
                bg_decl = decls.get('background-color') or decls.get('background')
                if not bg_decl:
                    continue
                fg = _fg(decls['color'][0], variables)
                kind, bg = _bg(bg_decl[0], variables)
                if fg and kind == 'color':
                    self.report_contrast(file, decls['color'][1], selector, fg, bg, _is_large(selector, decls))
        color, bg = body['color'], body['bg']
        if not (color or bg) or (color and bg and color[2] == bg[2]) or (not (color and bg) and not has_text) \
                or (bg and not color and styled['color']) or (color and not bg and styled['bg']):
            return  # a text-less page (e.g. a canvas game) cannot have unreadable default text
        fg = _fg(color[0][0], color[3]) if color else (0, 0, 0)
        kind, bgc = _bg(bg[0][0], bg[3]) if bg else ('color', (255, 255, 255))
        if kind == 'none':
            kind, bgc = 'color', (255, 255, 255)
        if fg and kind == 'color':
            src = color or bg
            self.report_contrast(src[1], src[0][1], 'body text', fg, bgc, False,
                                 defaulted='' if (color and bg) else (' (browser default background white)' if color else
                                                                     ' (browser default text black)'))

    def report_contrast(self, file, line, selector, fg, bg, large, defaulted=''):
        ratio = contrast(fg, bg)
        need = 3.0 if large else 4.5
        if ratio >= need:
            return
        severity = 'error' if ratio < 3 and not large else 'warning'
        target = need + 0.05
        self.add(severity, 'contrast', file, line,
                 f'Low contrast {ratio:.2f}:1 for "{selector[:80]}": {hex_of(fg)} text on {hex_of(bg)}{defaulted}'
                 f' (needs {need:g}:1).',
                 f'Use text colour {_suggest(fg, bg, target)} (or change the background) to reach {need:g}:1.')

    # -- per page
    def audit_page(self, page):
        text = self.read(page, MAX_HTML_BYTES)
        if text is None:
            self.add('error', 'read', page, None, 'Could not read this page.', 'Check the file is valid UTF-8 text.')
            return
        doc = self.parsed.get(page) or _parse_html(text)
        self.parsed[page] = doc
        site_root = self.site_root(page)
        weight = set()
        head_line = doc.tag_lines.get('head', 1)
        body_line = doc.tag_lines.get('body', head_line)
        add = self.add

        # document basics
        if not doc.lang:
            add('error', 'html-lang', page, doc.tag_lines.get('html', 1), '<html> has no lang attribute.',
                'Add the page language, e.g. <html lang="en">.')
        if doc.title is None or not doc.title[0]:
            add('error', 'title', page, doc.title[1] if doc.title else head_line, 'Page has no <title>.',
                'Add <title>Clear page name - Site name</title> (10-60 characters) inside <head>.')
        elif not 10 <= len(doc.title[0]) <= 60:
            add('warning', 'title', page, doc.title[1],
                f'Title is {len(doc.title[0])} characters ("{doc.title[0][:70]}"); aim for 10-60.',
                'Write a descriptive title of 10-60 characters.' if len(doc.title[0]) < 10 else
                'Shorten the title to 60 characters or fewer so search results do not cut it off.')
        metas = {}
        for attrs, line in doc.metas:
            key = (attrs.get('name') or attrs.get('property') or '').strip().lower()
            if key and key not in metas:
                metas[key] = (attrs.get('content', '').strip(), line)
        desc = metas.get('description')
        if not desc or not desc[0]:
            add('warning', 'meta-description', page, desc[1] if desc else head_line, 'No meta description.',
                'Add <meta name="description" content="..."> with a 50-160 character summary of the page.')
        elif not 50 <= len(desc[0]) <= 160:
            add('info', 'meta-description', page, desc[1],
                f'Meta description is {len(desc[0])} characters; aim for 50-160.',
                'Expand it into a one-sentence summary.' if len(desc[0]) < 50 else 'Trim it to 160 characters.')
        viewport = metas.get('viewport')
        if not viewport:
            add('error', 'viewport', page, head_line, 'No meta viewport; the page will render zoomed-out on phones.',
                'Add <meta name="viewport" content="width=device-width, initial-scale=1">.')
        else:
            content = viewport[0].lower().replace(' ', '')
            max_scale = re.search(r'maximum-scale=([\d.]+)', content)
            if re.search(r'user-scalable=(no|0)\b', content) or (max_scale and _float(max_scale.group(1)) < 2):
                add('warning', 'viewport-zoom', page, viewport[1], 'Meta viewport blocks pinch-zoom.',
                    'Remove user-scalable=no and maximum-scale so low-vision users can zoom.')
        if 'og:title' not in metas:
            add('info', 'open-graph', page, head_line, 'No og:title meta (link previews in chats/social apps).',
                'Add <meta property="og:title" content="...">.')
        if 'og:description' not in metas:
            add('info', 'open-graph', page, head_line, 'No og:description meta.',
                'Add <meta property="og:description" content="...">.')

        # favicon + link-tag assets
        has_icon = False
        for attrs, line in doc.links:
            rel_tokens = _rel_tokens(attrs.get('rel', ''))
            href = attrs.get('href', '').strip()
            if 'icon' in rel_tokens or 'apple-touch-icon' in rel_tokens:
                has_icon = True
                if href:
                    self.check_asset(page, line, href, 'icon', site_root)
            elif rel_tokens & {'preload', 'manifest', 'modulepreload'} and href:
                self.check_asset(page, line, href, 'file', site_root)
        if not has_icon and not self.exists(posixpath.join(site_root, 'favicon.ico') if site_root else 'favicon.ico'):
            add('warning', 'favicon', page, head_line, 'No favicon link.',
                'Add <link rel="icon" href="favicon.svg"> (or favicon.ico at the site root).')

        # headings
        h1s = [h for h in doc.headings if h[0] == 1]
        if not h1s:
            add('warning', 'h1', page, body_line, 'Page has no <h1>.', 'Add one <h1> naming the page topic.')
        for h in h1s[1:]:
            add('warning', 'h1', page, h[1], f'Extra <h1> (first one is on line {h1s[0][1]}).',
                'Keep a single <h1>; use <h2> for sections.')
        previous = None
        for level, line, text_ in doc.headings:
            if not text_:
                add('warning', 'heading-empty', page, line, f'<h{level}> has no text.', 'Add text or remove the heading.')
            if previous and level > previous + 1:
                add('warning', 'heading-order', page, line, f'Heading jumps from <h{previous}> to <h{level}>.',
                    f'Use <h{previous + 1}> here (or restyle with CSS instead of skipping levels).')
            previous = level

        # images
        for attrs, line in doc.imgs:
            src = attrs.get('src', '').strip()
            if 'alt' not in attrs:
                add('error', 'img-alt', page, line, f'<img src="{src[:80]}"> has no alt attribute.',
                    'Add alt="what the image shows" (or alt="" if purely decorative).')
            if not (attrs.get('width', '').strip() and attrs.get('height', '').strip()) and \
                    not src.split('?')[0].lower().endswith('.svg'):
                add('info', 'img-size-attrs', page, line, f'<img src="{src[:80]}"> has no width/height.',
                    'Add width and height attributes (intrinsic size) to prevent layout shift.')
            if src:
                self.check_asset(page, line, src, 'image', site_root, weight)
            self.check_srcset(page, line, attrs.get('srcset', ''), site_root, weight)
        for tag, attrs, line in doc.media:
            if tag == 'input':
                if not attrs.get('alt', '').strip():
                    add('error', 'img-alt', page, line, '<input type="image"> has no alt text.',
                        'Add alt describing the action, e.g. alt="Search".')
                if attrs.get('src', '').strip():
                    self.check_asset(page, line, attrs['src'], 'image', site_root, weight)
                continue
            if attrs.get('src', '').strip():
                self.check_asset(page, line, attrs['src'], 'media file', site_root)
            if attrs.get('poster', '').strip():
                self.check_asset(page, line, attrs['poster'], 'image', site_root, weight)
            self.check_srcset(page, line, attrs.get('srcset', ''), site_root, weight)

        # scripts
        for attrs, line in doc.scripts:
            src = attrs.get('src', '').strip()
            if not src:
                continue
            found = self.check_asset(page, line, src, 'script', site_root, weight)
            if found and found.lower().endswith(SOURCE_EXT):
                add('info', 'build-needed', page, line,
                    f'Script {src[:80]} is framework source that needs a build step.',
                    'Run the build and audit dist/index.html (page="dist/index.html") for the real output.')

        # links
        for attrs, line, text_ in doc.anchors:
            if 'href' not in attrs:
                continue
            href = attrs['href'].strip()
            label = text_ or attrs.get('aria-label', '').strip() or attrs.get('aria-labelledby', '').strip() \
                or attrs.get('title', '').strip()
            if not label:
                add('error', 'link-text', page, line, f'Link to "{href[:80]}" has no text.',
                    'Add visible text, or aria-label="..." for icon-only links.')
            if attrs.get('target', '').strip().lower() == '_blank' and \
                    not _rel_tokens(attrs.get('rel', '')) & {'noopener', 'noreferrer'}:
                add('warning', 'target-blank', page, line, f'target="_blank" link to "{href[:80]}" has no rel="noopener".',
                    'Add rel="noopener noreferrer".')
            self.check_link(page, line, href, site_root, doc)

        # buttons + forms
        for attrs, line, text_ in doc.buttons:
            if not (text_ or attrs.get('aria-label', '').strip() or attrs.get('aria-labelledby', '').strip()
                    or attrs.get('title', '').strip()):
                add('error', 'button-text', page, line, '<button> has no accessible text.',
                    'Add text inside it, or aria-label="..." for icon buttons.')
        for tag, attrs, line, inside in doc.inputs:
            kind = attrs.get('type', 'text').strip().lower() if tag == 'input' else tag
            if kind in NO_LABEL_INPUTS:
                continue
            if inside or attrs.get('id', '').strip() in doc.label_for or attrs.get('aria-label', '').strip() \
                    or attrs.get('aria-labelledby', '').strip() or attrs.get('title', '').strip():
                continue
            ident = attrs.get('id', '').strip()
            described = f' type="{kind}"' if tag == 'input' else ''
            if attrs.get('placeholder', '').strip():
                add('warning', 'form-label', page, line, f'<{tag}> relies on a placeholder instead of a label.',
                    f'Add <label for="{ident or "field-id"}">...</label>; placeholders vanish while typing.')
            else:
                add('error', 'form-label', page, line, f'<{tag}{described}> has no label.',
                    f'Wrap it in <label> or add <label for="{ident or "field-id"}">, or aria-label="...".')

        # misc markup
        for ident, line, first in doc.dup_ids:
            add('error', 'duplicate-id', page, line, f'Duplicate id="{ident[:60]}" (first used on line {first}).',
                'Make every id unique on the page.')
        if len(doc.inline_styles) > INLINE_STYLE_LIMIT:
            add('info', 'inline-style', page, doc.inline_styles[0],
                f'{len(doc.inline_styles)} elements use inline style= attributes.',
                'Move repeated styles into CSS classes.')
        for tag, line in doc.deprecated:
            add('warning', 'deprecated-tag', page, line, f'Deprecated <{tag}> tag.',
                'Replace it with semantic HTML styled by CSS.')

        # CSS: referenced assets + contrast, then page weight
        sheets = self.load_sheets(page, doc, site_root, weight)
        self.contrast_checks(sheets, doc.text_chars > 0)
        total = len(text.encode('utf-8')) + sum(self.size(rel) for rel in weight if rel != page)
        self.page_weights[page] = total
        if total > PAGE_WEIGHT_WARN:
            add('warning', 'page-weight', page, None,
                f'Page weight is {total / 1048576:.1f} MB (HTML + CSS + JS + images + fonts).',
                'Compress images, lazy-load below-the-fold images (loading="lazy"), and drop unused scripts.')

    def check_srcset(self, page, line, srcset, site_root, weight):
        if not srcset.strip() or 'data:' in srcset:
            return
        for candidate in srcset.split(','):
            url = candidate.strip().split()[0] if candidate.strip() else ''
            if url:
                self.check_asset(page, line, url, 'image', site_root, weight)

    def check_link(self, page, line, href, site_root, doc):
        if href == '#':
            self.add('warning', 'link-hash', page, line, 'Link uses href="#" (goes nowhere).',
                     'Point it at a real page or #section id, or use a <button> for actions.')
            return
        parts = _split_url(href)
        if parts[0] == 'external':
            self.external_links.add(parts[1])
            return
        if parts[0] == 'scheme':
            if parts[1] == 'javascript':
                self.add('warning', 'link-hash', page, line, 'Link uses a javascript: URL.',
                         'Use a <button> with an event listener instead.')
            elif parts[1] in ('mailto', 'tel'):
                self.contact_links.add(href[:200])
            return
        if parts[0] != 'local':
            return
        path, fragment = parts[1], parts[2]
        self.links_checked += 1
        if not path:
            if fragment and fragment != 'top' and fragment not in doc.ids and fragment not in doc.names:
                self.add('error', 'broken-anchor', page, line, f'Anchor "#{fragment[:80]}" has no matching id on this page.',
                         f'Add id="{fragment[:80]}" to the target element or fix the link.')
            return
        found, wanted = self.resolve(page, path, site_root)
        if wanted is None:
            self.add('error', 'broken-link', page, line, f'Link "{href[:120]}" points outside the project.',
                     'Link to a page inside the project.')
            return
        if found is None:
            self.add('error', 'broken-link', page, line, f'Broken link "{href[:120]}" (no file {wanted}).',
                     f'Create {wanted} or fix the href.')
            return
        if isinstance(found, tuple):
            self.add('warning', 'path-case', page, line, f'Link "{href[:120]}" only matches {found[1]} with different letter case.',
                     f'Use the exact name {found[1]}; Linux web hosts are case-sensitive.')
            found = found[1]
        if fragment and fragment != 'top' and found.lower().endswith(('.html', '.htm')):
            ids = self.page_ids(found)
            if ids is not None and fragment not in ids:
                self.add('error', 'broken-anchor', page, line, f'Anchor "#{fragment[:80]}" not found in {found}.',
                         f'Add id="{fragment[:80]}" in {found} or fix the link.')


def _float(text):
    try:
        return float(text)
    except ValueError:
        return 99.0


def _check_page_arg(page):
    if not isinstance(page, str) or not page.strip():
        raise AuditError('page must be a project-relative .html path, e.g. "index.html".')
    rel = page.strip().replace('\\', '/')
    while rel.startswith('./'):
        rel = rel[2:]
    parts = rel.split('/')
    if rel.startswith('/') or ':' in rel or any(p in ('', '.', '..') for p in parts) or len(rel) > 240:
        raise AuditError(f'Unsafe page path "{page[:80]}": use a path inside the project such as "index.html" or "blog/post.html".')
    if not rel.lower().endswith(('.html', '.htm')):
        raise AuditError(f'"{page[:80]}" is not an .html page.')
    return rel


def audit(name, page=None):
    """Audit a Build project (read-only). Raises AuditError with a friendly message on bad input."""
    try:
        ctx = _Audit(name)
    except projects.ProjectError as error:
        raise AuditError(str(error)) from None
    notes = []
    if page is not None and page != '':
        rel = _check_page_arg(page)
        found = ctx.exists(rel)
        if isinstance(found, tuple):
            rel = found[1]
        elif found != 'ok':
            html = sorted(r for r in ctx.files if r.lower().endswith(('.html', '.htm')))[:15]
            raise AuditError(f'No page "{rel}" in project "{name}". HTML pages: {", ".join(html) or "none"}.')
        pages = [rel]
    else:
        pages = sorted((r for r in ctx.files if r.lower().endswith(('.html', '.htm'))),
                       key=lambda r: (r.count('/'), posixpath.basename(r).lower() != 'index.html', r))
        if not pages:
            hint = ''
            for built in ('dist/index.html', 'build/index.html'):
                if ctx.exists(built) == 'ok':
                    hint = f' A built page exists: audit it with page="{built}".'
                    break
            raise AuditError(
                f'Project "{name}" has no HTML pages yet. Build the site first (an index.html), then audit it. '
                f'Framework apps (Vite/React) should be built and audited on dist/index.html.{hint}')
        if len(pages) > MAX_PAGES:
            notes.append(f'Only the first {MAX_PAGES} of {len(pages)} HTML pages were audited.')
            pages = pages[:MAX_PAGES]
    for rel in pages:
        ctx.audit_page(rel)

    order = {s: i for i, s in enumerate(SEVERITIES)}
    issues = sorted(ctx.issues.values(), key=lambda i: (order[i['severity']], i['file'], i['line'] or 0, i['check'],
                                                         i['message']))
    counts = {s: sum(1 for i in issues if i['severity'] == s) for s in SEVERITIES}
    score = max(0, 100 - sum(WEIGHTS[s] * n for s, n in counts.items()))
    kinds = {'html': ('.html', '.htm'), 'css': ('.css',), 'js': ('.js', '.mjs', '.jsx', '.ts', '.tsx'),
             'images': IMAGE_EXT}
    stats = {
        'pages_audited': len(pages),
        'files_scanned': len(ctx.files),
        'file_counts': {k: sum(1 for r in ctx.files if r.lower().endswith(ext)) for k, ext in kinds.items()},
        'page_weight_bytes': dict(sorted(ctx.page_weights.items())),
        'internal_links_checked': ctx.links_checked,
        'assets_checked': ctx.assets_checked,
        'images_checked': len(ctx.checked_images),
        'external_links': sorted(ctx.external_links)[:50],
        'external_assets': sorted(ctx.external_assets)[:50],
        'contact_links': sorted(ctx.contact_links)[:20],
        'issues_truncated': len(ctx.issues) >= MAX_ISSUES,
        'notes': notes + (['File scan stopped at 2000 files.'] if len(ctx.files) >= MAX_FILES else []),
    }
    return {'project': name, 'pages': pages, 'score': score, 'counts': counts, 'issues': issues, 'stats': stats}


# ---------------------------------------------------------------- MCP tool

def _kb(n):
    return f'{n / 1048576:.1f} MB' if n >= 1048576 else f'{max(1, round(n / 1024))} KB'


def report(result, limit=MAX_REPORT_ISSUES):
    c = result['counts']
    pages = result['pages']
    lines = [f'Site audit: {result["project"]} - score {result["score"]}/100',
             f'{c["error"]} errors, {c["warning"]} warnings, {c["info"]} info - {len(pages)} page(s): '
             + ', '.join(pages[:10]) + (f' (+{len(pages) - 10} more)' if len(pages) > 10 else '')]
    if not result['issues']:
        lines.append('\nNo issues found.')
    shown = 0
    for severity in SEVERITIES:
        group = [i for i in result['issues'] if i['severity'] == severity]
        if not group or shown >= limit:
            continue
        lines.append(f'\n{severity.upper()}S ({len(group)})')
        for issue in group:
            if shown >= limit:
                break
            where = issue['file'] + (f':{issue["line"]}' if issue['line'] else '')
            lines.append(f'- {where} - [{issue["check"]}] {issue["message"]} -> {issue["fix"]}')
            shown += 1
    if len(result['issues']) > shown:
        lines.append(f'\n+{len(result["issues"]) - shown} more issues not shown.')
    s = result['stats']
    weights = ', '.join(f'{p} {_kb(b)}' for p, b in list(s['page_weight_bytes'].items())[:10])
    lines.append('\nStats')
    lines.append(f'- Files scanned: {s["files_scanned"]} (html {s["file_counts"]["html"]}, css {s["file_counts"]["css"]}, '
                 f'js {s["file_counts"]["js"]}, images {s["file_counts"]["images"]})')
    lines.append(f'- Internal links checked: {s["internal_links_checked"]}; assets checked: {s["assets_checked"]}')
    if weights:
        lines.append(f'- Page weight: {weights}')
    if s['external_links']:
        lines.append(f'- External links (not fetched): {len(s["external_links"])}: ' + ', '.join(s['external_links'][:8])
                     + (' ...' if len(s['external_links']) > 8 else ''))
    if s['external_assets']:
        lines.append('- External assets: ' + ', '.join(s['external_assets'][:8]))
    for note in s['notes']:
        lines.append(f'- {note}')
    return '\n'.join(lines)


def call(tool, arguments):
    if tool != 'audit_site':
        return _error(f'Unknown tool {tool}.')
    if not isinstance(arguments, dict):
        return _error('Pass {"project": "<build project name>"} and optionally "page".')
    project = arguments.get('project')
    if not isinstance(project, str) or not project.strip():
        known = ', '.join(projects.list_projects()[:20]) or 'none yet'
        return _error(f'Pass project: the Build project name. Existing projects: {known}.')
    page = arguments.get('page')
    if page is not None and not isinstance(page, str):
        return _error('page must be a project-relative .html path, e.g. "index.html".')
    try:
        result = audit(project.strip(), page.strip() if page else None)
    except AuditError as error:
        return _error(error)
    return {'content': [{'type': 'text', 'text': report(result)}]}
