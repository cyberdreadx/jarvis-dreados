"""Website starter templates: a polished, editable, dependency-free site in a NEW Build project.

Small local models are much better at editing a good site than writing one from scratch, so
`new_site` writes a complete starting point (HTML/CSS/JS, favicon and a PROJECT_BRIEF.md for
Build's coding agent). Files are written only through projects.write_files (new project, never
overwrites). Theme colours are derived from one brand colour and adjusted until every text/background
pair used by the templates meets WCAG AA (4.5:1).
"""
import datetime
import html
import re

from . import palette, projects

TEMPLATES = ('landing', 'portfolio', 'blog', 'link_in_bio', 'docs')
THEMES = ('dark', 'light')
DEFAULT_COLOR = '#2ff3d0'
ALLOWED = {'template', 'site_title', 'tagline', 'project_name', 'color', 'theme', 'sections'}
MAX_SECTIONS, MAX_SECTION_LEN = 8, 60
AA = 4.5

TOOLS = [{
    'name': 'new_site',
    'description': ('Create a polished website starter as a new DreadOS Build project (HTML/CSS/JS, mobile-first, '
                    'accessible), themed from one brand colour. Use for any new website, then edit it in Build. '
                    'Templates: landing (product page: features, pricing, FAQ), portfolio (works grid, about, '
                    'contact), blog (posts), link_in_bio (link buttons), docs (pages + sidebar). "sections" are '
                    'ITEMS to fill in, not page names (templates already have about/contact): landing = features, '
                    'portfolio = work/project titles (e.g. albums, shows), blog = post titles, link_in_bio = link '
                    'labels, docs = page names.'),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'template': {'type': 'string', 'enum': list(TEMPLATES), 'description': 'Kind of site.'},
            'site_title': {'type': 'string', 'minLength': 1, 'maxLength': 60,
                           'description': 'Site or brand name, e.g. "Nova Analytics" or "Jane Doe".'},
            'tagline': {'type': 'string', 'maxLength': 140, 'description': 'One-sentence description.'},
            'project_name': {'type': 'string', 'maxLength': 50,
                             'description': 'Optional Build project name (lowercase-hyphens). Default: from site_title.'},
            'color': {'type': 'string', 'maxLength': 60, 'default': DEFAULT_COLOR,
                      'description': 'Brand colour: hex (#2ff3d0), rgb(...), hsl(...) or a CSS name like coral.'},
            'theme': {'type': 'string', 'enum': list(THEMES), 'default': 'dark'},
            'sections': {'type': 'array', 'maxItems': MAX_SECTIONS,
                         'items': {'type': 'string', 'minLength': 1, 'maxLength': MAX_SECTION_LEN},
                         'description': ('Optional items to fill in, NOT page names: feature names (landing), '
                                         'work/project titles (portfolio), post titles (blog), link labels '
                                         '(link_in_bio) or doc page names (docs).')},
        },
        'required': ['template', 'site_title'],
        'additionalProperties': False,
    },
}]


class SiteError(ValueError):
    pass


def _error(message):
    return {'isError': True, 'content': [{'type': 'text', 'text': str(message)[:2000]}]}


def esc(text):
    return html.escape(str(text), quote=True)


# ---------------------------------------------------------------- theme

WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def _hsl(h, s, l):
    return palette._hsl_to_rgb(h, s, l)


def _mix(a, b, t):
    """t of colour a over colour b."""
    return tuple(int(round(x * t + y * (1 - t))) for x, y in zip(a, b))


def _fit(h, s, l, against, direction, ratio=AA + 0.1):
    """Move lightness in `direction` until the colour reaches `ratio` against every colour in `against`."""
    for _ in range(101):
        rgb = _hsl(h, s, l)
        if all(palette.contrast(rgb, other) >= ratio for other in against):
            return rgb
        l = min(1.0, max(0.0, l + direction * 0.01))
    return WHITE if direction > 0 else BLACK


# Text/background pairs the templates actually use; every one must pass AA.
CONTRAST_PAIRS = [
    ('text', 'bg'), ('text', 'surface'), ('text', 'surface-2'), ('text', 'accent-soft'),
    ('muted', 'bg'), ('muted', 'surface'), ('muted', 'surface-2'),
    ('accent', 'bg'), ('accent', 'surface'), ('accent', 'surface-2'), ('accent', 'accent-soft'),
    ('accent-contrast', 'accent'),
]


def build_theme(color, theme='dark'):
    """Design tokens {name: (r, g, b)} derived from the brand colour, all CONTRAST_PAIRS passing AA."""
    rgb = palette.parse_color(color)
    h, s, l = palette.rgb_to_hsl(rgb)
    ns = min(s, 0.6) * 0.32                       # subtle brand tint for the neutrals
    if theme == 'dark':
        bg, surface, surface2 = _hsl(h, ns, 0.06), _hsl(h, ns, 0.095), _hsl(h, ns, 0.14)
        border = _hsl(h, ns, 0.22)
        text = _fit(h, min(ns, 0.2), 0.95, [bg, surface, surface2], +1, 7)
        muted = _fit(h, min(ns, 0.18), 0.68, [bg, surface, surface2], +1)
        ink, direction = _hsl(h, min(s, 0.7), 0.07), +1
    else:
        bg, surface, surface2 = _hsl(h, ns, 0.98), WHITE, _hsl(h, min(ns + 0.08, 0.5), 0.945)
        border = _hsl(h, ns, 0.87)
        text = _fit(h, min(ns + 0.1, 0.35), 0.13, [bg, surface, surface2], -1, 7)
        muted = _fit(h, min(ns, 0.18), 0.45, [bg, surface, surface2], -1)
        ink, direction = _hsl(h, min(s, 0.7), 0.1), -1
    backgrounds = [bg, surface, surface2]
    al = l
    for _ in range(140):
        accent = _hsl(h, s, al)
        soft = _mix(accent, surface, 0.14)
        fg = max((ink, WHITE), key=lambda c: palette.contrast(c, accent))
        if (all(palette.contrast(accent, b) >= AA + 0.05 for b in backgrounds + [soft])
                and palette.contrast(fg, accent) >= AA + 0.05 and palette.contrast(text, soft) >= AA + 0.05):
            break
        al = min(1.0, max(0.0, al + direction * 0.01))
    return {
        'bg': bg, 'surface': surface, 'surface-2': surface2, 'border': border,
        'text': text, 'muted': muted, 'accent': accent, 'accent-contrast': fg, 'accent-soft': soft,
        'brand': rgb, 'brand-2': _hsl(h + 42, max(s, 0.45), min(max(l, 0.45), 0.65)),
    }


def theme_report(tokens):
    """[(fg, bg, ratio)] for every text pair the templates use."""
    return [(fg, bg, palette.contrast(tokens[fg], tokens[bg])) for fg, bg in CONTRAST_PAIRS]


def _thumb_colors(tokens, count):
    h, s, l = palette.rgb_to_hsl(tokens['brand'])
    s = max(s, 0.45)
    out = []
    for i in range(count):
        hue = h + (i * 47) % 360 - (i % 2) * 20
        out.append((palette.hex_of(_hsl(hue, s, 0.55)), palette.hex_of(_hsl(hue + 38, s * 0.9, 0.32))))
    return out


# ---------------------------------------------------------------- shared pieces

ICONS = {
    'bolt': '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    'shield': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    'layers': '<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    'sparkle': '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    'chart': '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
    'globe': '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
    'heart': '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>',
    'code': '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    'users': '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'arrow': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'arrow-left': '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
    'mail': '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    'play': '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4V8z"/>',
    'camera': '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    'music': '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    'mic': '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8"/>',
    'bag': '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/>',
    'link': '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    'book': '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    'info': '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    'alert': '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    'copy': '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    'search': '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    'calendar': '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    'pen': '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    'star': '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    'file': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    'map': '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
}

KEYWORD_ICONS = [
    (('video', 'youtube', 'watch', 'stream', 'twitch', 'tiktok'), 'play'),
    (('instagram', 'photo', 'gallery', 'picture', 'camera'), 'camera'),
    (('music', 'spotify', 'song', 'album', 'soundcloud', 'band'), 'music'),
    (('podcast', 'audio', 'listen', 'radio'), 'mic'),
    (('shop', 'store', 'merch', 'buy', 'cart', 'product'), 'bag'),
    (('mail', 'email', 'newsletter', 'contact', 'subscribe'), 'mail'),
    (('github', 'code', 'api', 'developer', 'dev', 'integration'), 'code'),
    (('blog', 'read', 'article', 'write', 'post', 'docs', 'guide'), 'book'),
    (('fast', 'speed', 'quick', 'instant', 'performance', 'setup'), 'bolt'),
    (('secure', 'security', 'privacy', 'safe', 'protect'), 'shield'),
    (('analytic', 'dashboard', 'chart', 'stat', 'insight', 'report', 'metric', 'data'), 'chart'),
    (('team', 'collab', 'share', 'community', 'people', 'friend'), 'users'),
    (('global', 'world', 'everywhere', 'web', 'site', 'website', 'portfolio'), 'globe'),
    (('support', 'help', 'love', 'care', 'donate', 'tip'), 'heart'),
    (('time', 'schedule', 'book', 'calendar', 'event', 'tour'), 'calendar'),
    (('location', 'map', 'visit', 'address'), 'map'),
]


def icon(name, size=20, cls='icon'):
    return (f'<svg class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true" focusable="false">{ICONS[name]}</svg>')


def icon_for(label, fallback):
    words = re.findall(r'[a-z]+', label.lower())
    for keys, name in KEYWORD_ICONS:
        if any(w.startswith(k) for w in words for k in keys):
            return name
    return fallback


def monogram(title):
    words = re.findall(r'[A-Za-z0-9]+', title)
    if not words:
        return 'S'
    if len(words) == 1:
        return words[0][:1].upper()
    return (words[0][:1] + words[1][:1]).upper()


def favicon_svg(tokens, title):
    accent, fg = palette.hex_of(tokens['accent']), palette.hex_of(tokens['accent-contrast'])
    letters = esc(monogram(title))
    size = 34 if len(monogram(title)) == 1 else 26
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64" rx="16" fill="{accent}"/>'
            f'<text x="32" y="{32 + size * 0.36:.1f}" text-anchor="middle" font-family="system-ui,-apple-system,'
            f'Segoe UI,Roboto,Arial,sans-serif" font-size="{size}" font-weight="800" fill="{fg}">{letters}</text></svg>\n')


def _page(ctx, *, title, description, body, depth=0, body_class=''):
    p = '../' * depth
    page_title = esc(title)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <meta name="description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{page_title}">
  <meta property="og:description" content="{esc(description)}">
  <meta name="theme-color" content="{ctx['hex']['bg']}">
  <link rel="icon" href="{p}favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{p}styles.css">
  <script src="{p}script.js" defer></script>
</head>
<body class="{body_class}">
  <a class="skip-link" href="#main">Skip to content</a>
{body}
</body>
</html>
'''


def _header(ctx, links, cta='', depth=0, current=None, nav_id='site-nav', extra=''):
    p = '../' * depth
    items = []
    for label, href in links:
        here = ' aria-current="page"' if current and href == current else ''
        items.append(f'<li><a href="{href}"{here}>{esc(label)}</a></li>')
    return f'''  <header class="site-header">
    <div class="container header-inner">
      <a class="brand" href="{p}index.html"><img src="{p}favicon.svg" alt="" width="30" height="30"><span>{ctx['title']}</span></a>
      {extra}
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="{nav_id}" data-nav-toggle>
        <span class="visually-hidden">Menu</span>{icon('menu', 22)}
      </button>
      <nav class="site-nav" id="{nav_id}" aria-label="Main">
        <ul>{''.join(items)}</ul>{cta}
      </nav>
    </div>
  </header>'''


def _footer(ctx, note='', links=()):
    items = ''.join(f'<li><a href="{href}">{esc(label)}</a></li>' for label, href in links)
    nav = f'<nav aria-label="Footer"><ul class="footer-links">{items}</ul></nav>' if items else ''
    return f'''  <footer class="site-footer">
    <div class="container footer-inner">
      <p>&copy; <span data-year>{ctx['year']}</span> {ctx['title']}.{(' ' + note) if note else ''}</p>
      {nav}
    </div>
  </footer>'''


# ---------------------------------------------------------------- CSS

def tokens_css(tokens, theme):
    hexes = {k: palette.hex_of(v) for k, v in tokens.items()}
    shadow = ('0 1px 0 rgb(255 255 255 / 0.04) inset, 0 18px 40px -20px rgb(0 0 0 / 0.7)' if theme == 'dark'
              else '0 1px 2px rgb(15 23 42 / 0.06), 0 18px 40px -22px rgb(15 23 42 / 0.28)')
    lines = '\n'.join(f'  --{k}: {v};' for k, v in hexes.items())
    return f''':root {{
  /* Theme tokens generated from the brand colour {hexes['brand']} ({theme}).
     Every text colour here meets WCAG AA (4.5:1) on bg, surface, surface-2 and accent-soft.
     If you change a colour, re-check contrast. */
{lines}
  --shadow: {shadow};
  --radius: 14px;
  --radius-lg: 22px;
  --max: 1120px;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "Cascadia Code", "SF Mono", Menlo, Consolas, monospace;
  color-scheme: {theme};
}}
'''


BASE_CSS = r'''
/* ---------- Base (mobile-first) ---------- */
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--font); font-size: 1.0625rem; line-height: 1.65;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
img, svg { max-width: 100%; }
img { display: block; height: auto; }
.icon { display: inline-block; flex: none; vertical-align: middle; }
a { color: var(--accent); text-underline-offset: 0.2em; text-decoration-thickness: 1px; }
a:hover { text-decoration-thickness: 2px; }
h1, h2, h3, h4 { line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 0.5em; text-wrap: balance; }
h1 { font-size: clamp(2.4rem, 7vw, 4.4rem); letter-spacing: -0.035em; }
h2 { font-size: clamp(1.75rem, 4vw, 2.6rem); }
h3 { font-size: 1.2rem; }
p { margin: 0 0 1em; }
ul, ol { padding-left: 1.25em; }
[id] { scroll-margin-top: 5.5rem; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; border-radius: 6px; }
::selection { background: var(--accent); color: var(--accent-contrast); }
.visually-hidden {
  position: absolute !important; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.skip-link {
  position: absolute; left: 1rem; top: -100px; z-index: 100;
  background: var(--accent); color: var(--accent-contrast);
  padding: 0.65rem 1rem; border-radius: 10px; font-weight: 700; text-decoration: none;
}
.skip-link:focus { top: 1rem; }
main:focus { outline: none; }
.container { width: min(100% - 2.5rem, var(--max)); margin-inline: auto; }
.section { padding: clamp(4rem, 10vw, 7rem) 0; }
.section-head { max-width: 40rem; margin-bottom: clamp(2rem, 5vw, 3.25rem); }
.section-head p { color: var(--muted); font-size: 1.125rem; }
.eyebrow {
  display: inline-flex; align-items: center; gap: 0.5rem; margin: 0 0 1rem;
  font-size: 0.8125rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent);
}
.lead { font-size: clamp(1.125rem, 2.4vw, 1.3rem); color: var(--muted); max-width: 38rem; }
.muted { color: var(--muted); }
.chip {
  display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.2rem 0.65rem;
  border-radius: 999px; background: var(--accent-soft); color: var(--accent);
  font-size: 0.8125rem; font-weight: 600; line-height: 1.6;
}
.chips { display: flex; flex-wrap: wrap; gap: 0.5rem; list-style: none; padding: 0; margin: 0; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}

/* ---------- Buttons ---------- */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem;
  min-height: 2.9rem; padding: 0.7rem 1.3rem; border-radius: 999px; border: 1px solid transparent;
  font: inherit; font-weight: 650; font-size: 1rem; line-height: 1.2; text-decoration: none; cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, background-color 0.15s ease;
}
.btn:hover { transform: translateY(-1px); text-decoration: none; }
.btn-primary { background: var(--accent); color: var(--accent-contrast); box-shadow: 0 10px 30px -12px var(--accent); }
.btn-ghost { background: var(--surface-2); color: var(--text); border-color: var(--border); }
.btn-row { display: flex; flex-wrap: wrap; gap: 0.75rem; }

/* ---------- Header & navigation ---------- */
.site-header {
  position: sticky; top: 0; z-index: 50;
  background: color-mix(in srgb, var(--bg) 85%, transparent);
  backdrop-filter: saturate(1.4) blur(14px); -webkit-backdrop-filter: saturate(1.4) blur(14px);
  border-bottom: 1px solid var(--border);
}
.header-inner { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; min-height: 4rem; padding: 0.6rem 0; }
.brand {
  display: inline-flex; align-items: center; gap: 0.6rem; margin-right: auto;
  color: var(--text); font-weight: 750; font-size: 1.075rem; letter-spacing: -0.01em; text-decoration: none;
}
.brand img { border-radius: 9px; }
.nav-toggle {
  display: none; align-items: center; justify-content: center; width: 2.75rem; height: 2.75rem;
  border-radius: 12px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer;
}
.site-nav { flex-basis: 100%; }
.site-nav ul { display: flex; flex-wrap: wrap; gap: 0.25rem 1.25rem; list-style: none; margin: 0; padding: 0; }
.site-nav a:not(.btn) { color: var(--muted); text-decoration: none; font-weight: 550; padding: 0.35rem 0; display: inline-block; }
.site-nav a:not(.btn):hover, .site-nav a[aria-current="page"] { color: var(--text); }
.js .nav-toggle { display: inline-flex; }
.js .site-nav { display: none; padding: 0.5rem 0 1rem; }
.js .site-nav.is-open { display: block; }
.js .site-nav ul { flex-direction: column; gap: 0; }
.js .site-nav ul a:not(.btn) { padding: 0.7rem 0; display: block; border-bottom: 1px solid var(--border); }
.site-nav .btn { margin-top: 1rem; }
@media (min-width: 820px) {
  .header-inner { flex-wrap: nowrap; }
  .site-nav, .js .site-nav { display: flex; align-items: center; gap: 1.75rem; flex-basis: auto; padding: 0; }
  .js .nav-toggle { display: none; }
  .js .site-nav ul { flex-direction: row; gap: 1.6rem; }
  .js .site-nav ul a:not(.btn) { padding: 0.35rem 0; border: 0; }
  .site-nav .btn { margin-top: 0; min-height: 2.5rem; padding: 0.5rem 1.05rem; }
}

/* ---------- Footer ---------- */
.site-footer { border-top: 1px solid var(--border); padding: 2.25rem 0; color: var(--muted); font-size: 0.9375rem; }
.footer-inner { display: flex; flex-wrap: wrap; gap: 1rem 2rem; align-items: center; justify-content: space-between; }
.footer-inner p { margin: 0; }
.footer-links { display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem; list-style: none; margin: 0; padding: 0; }
.footer-links a { color: var(--muted); }
.footer-links a:hover { color: var(--text); }

/* ---------- Motion ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important; scroll-behavior: auto !important;
  }
}
'''

LANDING_CSS = r'''
/* ---------- Landing ---------- */
.hero { position: relative; overflow: hidden; padding: clamp(3.5rem, 9vw, 7rem) 0 clamp(3rem, 7vw, 5rem); }
.hero::before {
  content: ""; position: absolute; inset: -30% -10% auto 35%; height: 640px; pointer-events: none;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--brand) 26%, transparent), transparent 70%),
              radial-gradient(closest-side at 70% 60%, color-mix(in srgb, var(--brand-2) 20%, transparent), transparent 70%);
  filter: blur(10px);
}
.hero-grid { position: relative; display: grid; gap: clamp(2.5rem, 6vw, 4rem); align-items: center; }
.hero .badge {
  display: inline-flex; align-items: center; gap: 0.5rem; margin-bottom: 1.4rem;
  padding: 0.35rem 0.85rem 0.35rem 0.4rem; border-radius: 999px;
  background: var(--surface); border: 1px solid var(--border); color: var(--muted); font-size: 0.875rem;
}
.hero .badge .chip { font-size: 0.75rem; }
.hero h1 { max-width: 13ch; }
.hero .lead { margin-bottom: 2rem; }
.hero-note { margin-top: 1.1rem; font-size: 0.9rem; color: var(--muted); display: flex; align-items: center; gap: 0.45rem; }
.hero-note .icon { color: var(--accent); }
.mock { position: relative; padding: 0; overflow: hidden; }
.mock-bar { display: flex; gap: 6px; padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); background: var(--surface-2); }
.mock-bar span { width: 10px; height: 10px; border-radius: 50%; background: var(--border); }
.mock-body { display: grid; grid-template-columns: 1fr; gap: 0.9rem; padding: 1.1rem; }
.mock-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; }
.mock-stat { background: var(--surface-2); border-radius: 12px; padding: 0.75rem; }
.mock-stat b { display: block; font-size: 1.25rem; letter-spacing: -0.02em; }
.mock-stat small { color: var(--muted); font-size: 0.75rem; }
.mock-chart { display: flex; align-items: flex-end; gap: 8px; height: 150px; padding: 1rem; background: var(--surface-2); border-radius: 12px; }
.mock-chart i { flex: 1; border-radius: 6px 6px 3px 3px; background: linear-gradient(180deg, var(--brand), color-mix(in srgb, var(--brand) 25%, transparent)); }
.mock-chart i:nth-child(1) { height: 38%; } .mock-chart i:nth-child(2) { height: 55%; }
.mock-chart i:nth-child(3) { height: 46%; } .mock-chart i:nth-child(4) { height: 70%; }
.mock-chart i:nth-child(5) { height: 62%; } .mock-chart i:nth-child(6) { height: 84%; }
.mock-chart i:nth-child(7) { height: 76%; } .mock-chart i:nth-child(8) { height: 96%; }
.mock-rows { display: grid; gap: 0.5rem; }
.mock-row { display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 0.75rem; border-radius: 10px; background: var(--surface-2); }
.mock-row i { width: 26px; height: 26px; border-radius: 8px; background: var(--accent-soft); }
.mock-row span { height: 8px; border-radius: 4px; background: var(--border); flex: 1; }
.mock-row span + span { flex: 0 0 18%; background: var(--accent-soft); }
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 0; padding: 2rem 0 0; }
.stats div { border-left: 2px solid var(--accent); padding-left: clamp(0.6rem, 2vw, 1rem); }
.stats dt { color: var(--muted); font-size: 0.9rem; }
.stats dd { margin: 0; font-size: clamp(1.4rem, 5vw, 1.9rem); font-weight: 750; letter-spacing: -0.03em; order: -1; }
.stats div { display: flex; flex-direction: column; }
.features { display: grid; grid-template-columns: 1fr; gap: 1.1rem; list-style: none; padding: 0; margin: 0; }
.feature { padding: 1.6rem; transition: transform 0.2s ease, border-color 0.2s ease; }
.feature:hover { transform: translateY(-3px); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.feature-icon {
  display: inline-grid; place-items: center; width: 2.75rem; height: 2.75rem; margin-bottom: 1.1rem;
  border-radius: 12px; background: var(--accent-soft); color: var(--accent);
}
.feature p { color: var(--muted); margin: 0; }
.alt { background: var(--surface); border-block: 1px solid var(--border); }
.steps { display: grid; gap: 1.25rem; counter-reset: step; list-style: none; padding: 0; margin: 0; }
.steps li { position: relative; padding: 1.5rem 1.5rem 1.5rem 4.6rem; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.steps li::before {
  counter-increment: step; content: counter(step);
  position: absolute; left: 1.4rem; top: 1.45rem; display: grid; place-items: center;
  width: 2.2rem; height: 2.2rem; border-radius: 50%; background: var(--accent); color: var(--accent-contrast); font-weight: 800;
}
.steps p { color: var(--muted); margin: 0; }
.quote { margin: 0 auto; max-width: 48rem; text-align: center; }
.quote blockquote { margin: 0 0 1.5rem; font-size: clamp(1.35rem, 3vw, 1.9rem); line-height: 1.4; letter-spacing: -0.015em; font-weight: 600; }
.quote figcaption { display: inline-flex; align-items: center; gap: 0.8rem; color: var(--muted); text-align: left; }
.quote figcaption b { display: block; color: var(--text); }
.avatar {
  display: grid; place-items: center; width: 2.9rem; height: 2.9rem; border-radius: 50%;
  background: var(--accent); color: var(--accent-contrast); font-weight: 800;
}
.pricing { display: grid; gap: 1.1rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); align-items: stretch; }
.plan { display: flex; flex-direction: column; padding: 1.9rem; position: relative; }
.plan.featured { border: 2px solid var(--accent); }
.plan .tag { position: absolute; top: -0.85rem; right: 1.25rem; background: var(--accent); color: var(--accent-contrast); border-radius: 999px; padding: 0.15rem 0.75rem; font-size: 0.8rem; font-weight: 700; }
.plan h3 { margin-bottom: 0.25rem; }
.plan .price { font-size: 2.6rem; font-weight: 800; letter-spacing: -0.04em; margin: 0.75rem 0 0.25rem; }
.plan .price small { font-size: 1rem; font-weight: 500; color: var(--muted); letter-spacing: 0; }
.plan ul { list-style: none; padding: 0; margin: 1.25rem 0 1.75rem; display: grid; gap: 0.6rem; }
.plan li { display: flex; gap: 0.6rem; align-items: flex-start; }
.plan li .icon { color: var(--accent); margin-top: 0.2rem; }
.plan .btn { margin-top: auto; }
.faq { max-width: 48rem; display: grid; gap: 0.75rem; }
.faq details { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 0 1.25rem; }
.faq summary { cursor: pointer; list-style: none; padding: 1.1rem 0; font-weight: 650; display: flex; justify-content: space-between; gap: 1rem; }
.faq summary::-webkit-details-marker { display: none; }
.faq summary::after { content: "+"; color: var(--accent); font-size: 1.4rem; line-height: 1; transition: transform 0.2s ease; }
.faq details[open] summary::after { transform: rotate(45deg); }
.faq details p { color: var(--muted); margin: 0 0 1.2rem; }
.cta-band { position: relative; overflow: hidden; text-align: center; padding: clamp(2.5rem, 7vw, 4.5rem) 1.5rem; }
.cta-band::before {
  content: ""; position: absolute; inset: auto -20% -60% -20%; height: 120%; pointer-events: none;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--brand) 22%, transparent), transparent);
}
.cta-band > * { position: relative; }
.cta-band p { color: var(--muted); max-width: 34rem; margin: 0 auto 1.75rem; }
.cta-band .btn-row { justify-content: center; }
@media (min-width: 640px) {
  .features { grid-template-columns: repeat(2, 1fr); }
}
@media (min-width: 900px) {
  .hero-grid { grid-template-columns: 1.05fr 0.95fr; }
  .steps { grid-template-columns: repeat(3, 1fr); }
  .features { grid-template-columns: repeat(3, 1fr); }
  .features.two-col { grid-template-columns: repeat(2, 1fr); }
  .mock { transform: perspective(1400px) rotateY(-6deg) rotateX(2deg); }
}
'''

PORTFOLIO_CSS = r'''
/* ---------- Portfolio ---------- */
.intro { padding: clamp(4rem, 12vw, 8.5rem) 0 clamp(3rem, 8vw, 5rem); }
.intro h1 { font-size: clamp(2.8rem, 9vw, 6rem); max-width: 14ch; margin-bottom: 1.5rem; }
.intro h1 .dot { color: var(--accent); }
.status {
  display: inline-flex; align-items: center; gap: 0.6rem; margin-bottom: 2rem; padding: 0.4rem 0.9rem;
  border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); font-size: 0.9rem;
}
.pulse { position: relative; width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }
.pulse::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--accent); animation: pulse 2s ease-out infinite; }
@keyframes pulse { from { transform: scale(1); opacity: 0.7; } to { transform: scale(2.8); opacity: 0; } }
.intro .lead { margin-bottom: 2.25rem; }
.section.work { padding-top: 1rem; }
.work-head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 1rem; margin-bottom: 2.5rem; }
.work-head h2 { margin: 0; }
.work-head p { margin: 0; color: var(--muted); max-width: 26rem; }
.projects { display: grid; gap: clamp(1.25rem, 3vw, 2rem); list-style: none; padding: 0; margin: 0; }
.project { overflow: hidden; display: flex; flex-direction: column; transition: transform 0.25s ease, border-color 0.25s ease; }
.project:hover { transform: translateY(-4px); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.thumb { position: relative; aspect-ratio: 16 / 10; overflow: hidden; }
.thumb svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.project-body { padding: 1.4rem 1.5rem 1.6rem; display: flex; flex-direction: column; gap: 0.75rem; flex: 1; }
.project-body h3 { margin: 0; font-size: 1.3rem; }
.project-body p { margin: 0; color: var(--muted); }
.project-meta { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-top: auto; padding-top: 0.5rem; }
.project-meta span { color: var(--muted); font-size: 0.875rem; }
.about-grid { display: grid; gap: clamp(2rem, 6vw, 4.5rem); align-items: start; }
.portrait { margin: 0; padding: 1rem; max-width: 360px; }
.portrait svg { display: block; width: 100%; height: auto; border-radius: 16px; }
.portrait p { margin: 1rem 0 0; color: var(--muted); font-size: 0.9rem; text-align: center; }
.about-text .lead { color: var(--text); }
.about-text p { color: var(--muted); }
.timeline { list-style: none; padding: 0; margin: 2rem 0 0; border-top: 1px solid var(--border); }
.timeline li { display: grid; grid-template-columns: 7.5rem 1fr; gap: 1rem; padding: 1rem 0; border-bottom: 1px solid var(--border); }
.timeline span { color: var(--muted); font-variant-numeric: tabular-nums; }
.timeline b { display: block; }
.timeline small { color: var(--muted); font-size: 0.9rem; }
.skills { margin-top: 1.5rem; }
.contact { text-align: center; }
.contact h2 { font-size: clamp(2.2rem, 7vw, 4.5rem); margin-bottom: 1rem; }
.contact p { color: var(--muted); max-width: 32rem; margin: 0 auto 2rem; }
.big-link {
  display: inline-flex; align-items: center; gap: 0.75rem; font-size: clamp(1.25rem, 4vw, 2rem); font-weight: 700;
  letter-spacing: -0.02em; text-decoration: none; padding: 0.4rem 0; border-bottom: 2px solid var(--accent);
}
.socials { display: flex; justify-content: center; gap: 0.75rem; list-style: none; padding: 0; margin: 2.5rem 0 0; }
.socials a {
  display: grid; place-items: center; width: 3rem; height: 3rem; border-radius: 50%;
  background: var(--surface); border: 1px solid var(--border); color: var(--text);
}
.socials a:hover { color: var(--accent); border-color: var(--accent); }
@media (min-width: 760px) {
  .projects { grid-template-columns: repeat(2, 1fr); }
  .project:first-child:nth-last-child(odd) { grid-column: 1 / -1; }
  .project:first-child:nth-last-child(odd) .thumb { aspect-ratio: 21 / 8; }
  .about-grid { grid-template-columns: 340px 1fr; }
}
'''

BLOG_CSS = r'''
/* ---------- Blog ---------- */
.blog-hero { padding: clamp(3.5rem, 10vw, 6.5rem) 0 clamp(2rem, 5vw, 3rem); }
.blog-hero h1 { max-width: 16ch; }
.featured { display: grid; overflow: hidden; text-decoration: none; color: inherit; margin-bottom: clamp(2.5rem, 6vw, 4rem); }
.featured:hover h2 { color: var(--accent); }
.cover { position: relative; min-height: 220px; overflow: hidden; }
.cover svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.featured-body { padding: clamp(1.5rem, 4vw, 2.5rem); display: flex; flex-direction: column; justify-content: center; gap: 0.25rem; }
.featured-body h2 { font-size: clamp(1.6rem, 3.5vw, 2.3rem); transition: color 0.15s ease; }
.featured-body p { color: var(--muted); }
.post-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 1rem; color: var(--muted); font-size: 0.9rem; margin: 0 0 0.75rem; }
.post-meta span { display: inline-flex; align-items: center; gap: 0.35rem; }
.posts { list-style: none; padding: 0; margin: 0; display: grid; gap: 0; border-top: 1px solid var(--border); }
.post-item { border-bottom: 1px solid var(--border); }
.post-item a { display: grid; gap: 0.35rem; padding: 1.6rem 0; text-decoration: none; color: inherit; }
.post-item h3 { margin: 0; font-size: 1.35rem; transition: color 0.15s ease; }
.post-item a:hover h3 { color: var(--accent); }
.post-item p { margin: 0; color: var(--muted); }
.post-item .post-meta { margin: 0; }
.read-more { display: inline-flex; align-items: center; gap: 0.35rem; color: var(--accent); font-weight: 600; font-size: 0.95rem; }
.author { display: grid; gap: 1.25rem; align-items: center; padding: clamp(1.5rem, 4vw, 2.25rem); margin-top: clamp(3rem, 8vw, 5rem); }
.author img { width: 72px; height: 72px; border-radius: 50%; }
.author h2 { font-size: 1.35rem; margin-bottom: 0.25rem; }
.author p { color: var(--muted); margin: 0; }
.blog-layout { padding-bottom: clamp(4rem, 10vw, 6rem); }
/* Article */
.article { padding: clamp(2.5rem, 8vw, 5rem) 0 clamp(4rem, 10vw, 6rem); }
.article-head { max-width: 46rem; margin: 0 auto 2.5rem; }
.article-head h1 { font-size: clamp(2.2rem, 6vw, 3.6rem); }
.back { display: flex; width: fit-content; align-items: center; gap: 0.4rem; margin-bottom: 2rem; font-weight: 600; text-decoration: none; }
.article .cover { max-width: 60rem; margin: 0 auto 3rem; border-radius: var(--radius-lg); min-height: 0; aspect-ratio: 21 / 9; }
.prose { max-width: 42rem; margin: 0 auto; font-size: 1.125rem; line-height: 1.8; }
.prose h2 { font-size: 1.65rem; margin: 2.5rem 0 0.75rem; }
.prose p, .prose ul, .prose ol { margin: 0 0 1.4em; }
.prose li { margin-bottom: 0.4em; }
.prose blockquote { margin: 2rem 0; padding: 0.25rem 0 0.25rem 1.5rem; border-left: 3px solid var(--accent); font-size: 1.25rem; font-style: italic; }
.prose code { font-family: var(--mono); font-size: 0.9em; background: var(--surface-2); padding: 0.15em 0.4em; border-radius: 6px; }
.prose pre { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.1rem 1.25rem; overflow-x: auto; line-height: 1.6; }
.prose pre code { background: none; padding: 0; }
.post-nav { max-width: 42rem; margin: 3.5rem auto 0; padding-top: 2rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
@media (min-width: 820px) {
  .featured { grid-template-columns: 1.1fr 1fr; }
  .cover { min-height: 340px; }
  .post-item a { grid-template-columns: 11rem 1fr; column-gap: 2rem; }
  .post-item .post-meta { grid-row: span 3; align-self: start; padding-top: 0.3rem; flex-direction: column; align-items: flex-start; }
  .author { grid-template-columns: auto 1fr; }
}
'''

BIO_CSS = r'''
/* ---------- Link in bio ---------- */
body.bio { min-height: 100vh; display: flex; flex-direction: column; position: relative; overflow-x: hidden; }
body.bio::before {
  content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(40rem 28rem at 15% -5%, color-mix(in srgb, var(--brand) 24%, transparent), transparent 70%),
    radial-gradient(36rem 30rem at 100% 30%, color-mix(in srgb, var(--brand-2) 18%, transparent), transparent 70%),
    radial-gradient(30rem 26rem at 30% 110%, color-mix(in srgb, var(--brand) 14%, transparent), transparent 70%);
}
.bio-wrap { width: min(100% - 2.5rem, 34rem); margin-inline: auto; }
.bio-header { padding: clamp(3rem, 10vw, 5rem) 0 1.75rem; text-align: center; }
.bio-avatar { width: 112px; height: 112px; margin: 0 auto 1.25rem; border-radius: 50%; padding: 4px;
  background: conic-gradient(from 200deg, var(--brand), var(--brand-2), var(--brand)); box-shadow: var(--shadow); }
.bio-avatar svg { display: block; width: 100%; height: 100%; border-radius: 50%; }
.bio-header h1 { font-size: clamp(1.9rem, 7vw, 2.4rem); margin-bottom: 0.4rem; }
.bio-header .handle { color: var(--accent); font-weight: 600; margin-bottom: 0.75rem; }
.bio-header .tagline { color: var(--muted); margin: 0 auto; max-width: 26rem; }
.bio-socials { display: flex; justify-content: center; gap: 0.6rem; list-style: none; padding: 0; margin: 1.5rem 0 0; }
.bio-socials a {
  display: grid; place-items: center; width: 2.75rem; height: 2.75rem; border-radius: 50%;
  background: var(--surface); border: 1px solid var(--border); color: var(--text);
}
.bio-socials a:hover { color: var(--accent); border-color: var(--accent); }
.bio main { flex: 1; }
.links { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.85rem; }
.link-btn {
  display: flex; align-items: center; gap: 1rem; padding: 0.85rem 1rem 0.85rem 0.85rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 18px; box-shadow: var(--shadow);
  color: var(--text); text-decoration: none; font-weight: 650; font-size: 1.05rem;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.link-btn:hover { transform: translateY(-2px) scale(1.01); border-color: var(--accent); }
.link-btn .link-icon { display: grid; place-items: center; width: 2.75rem; height: 2.75rem; border-radius: 12px; background: var(--accent-soft); color: var(--accent); flex: none; }
.link-btn .link-text { flex: 1; display: flex; flex-direction: column; line-height: 1.3; }
.link-btn small { color: var(--muted); font-weight: 500; font-size: 0.875rem; }
.link-btn .arrow { color: var(--muted); }
.link-btn.primary { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.link-btn.primary small, .link-btn.primary .arrow { color: var(--accent-contrast); }
.link-btn.primary .link-icon { background: var(--accent-contrast); color: var(--accent); }
.spotlight { margin-top: 1.75rem; padding: 1.25rem; display: grid; gap: 1rem; }
.spotlight .cover { border-radius: 14px; overflow: hidden; aspect-ratio: 16 / 8; }
.spotlight .cover svg { display: block; width: 100%; height: 100%; }
.spotlight h2 { font-size: 1.2rem; margin: 0 0 0.25rem; }
.spotlight p { color: var(--muted); margin: 0; font-size: 0.95rem; }
.bio .site-footer { border: 0; text-align: center; padding: 2.5rem 0 2rem; }
.bio .footer-inner { justify-content: center; }
'''

DOCS_CSS = r'''
/* ---------- Docs ---------- */
.docs-badge { font-size: 0.75rem; }
.search { position: relative; flex: 1 1 100%; order: 3; }
.search .icon { position: absolute; left: 0.8rem; top: 50%; transform: translateY(-50%); color: var(--muted); pointer-events: none; }
.search input {
  width: 100%; padding: 0.6rem 0.9rem 0.6rem 2.4rem; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit; font-size: 0.95rem;
}
.search input::placeholder { color: var(--muted); opacity: 1; }
.docs-shell { display: grid; gap: 0; align-items: start; }
.sidebar { padding: 1.5rem 0; border-bottom: 1px solid var(--border); }
.js .sidebar { display: none; }
.js .sidebar.is-open { display: block; }
.sidebar h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted); margin: 0 0 0.6rem; }
.sidebar ul { list-style: none; margin: 0 0 1.5rem; padding: 0; display: grid; gap: 2px; }
.sidebar a { display: flex; align-items: center; gap: 0.55rem; padding: 0.5rem 0.75rem; border-radius: 9px; color: var(--muted); text-decoration: none; font-weight: 550; font-size: 0.95rem; }
.sidebar a:hover { color: var(--text); background: var(--surface); }
.sidebar a[aria-current="page"] { color: var(--accent); background: var(--accent-soft); }
.sidebar .empty { color: var(--muted); font-size: 0.9rem; padding: 0.5rem 0.75rem; }
.doc { min-width: 0; padding: 2rem 0 4rem; }
.crumbs { display: flex; flex-wrap: wrap; gap: 0.4rem; list-style: none; padding: 0; margin: 0 0 1.25rem; font-size: 0.875rem; color: var(--muted); }
.crumbs li + li::before { content: "/"; margin-right: 0.4rem; }
.crumbs a { color: var(--muted); }
.doc h1 { font-size: clamp(2.1rem, 5vw, 3rem); }
.doc .lead { margin-bottom: 2rem; }
.doc h2 { font-size: 1.55rem; margin: 2.75rem 0 0.75rem; padding-top: 0.5rem; }
.doc p, .doc li { color: var(--text); }
.doc ul, .doc ol { margin: 0 0 1.25em; }
.doc li { margin-bottom: 0.35em; }
.doc :not(pre) > code { font-family: var(--mono); font-size: 0.875em; background: var(--surface-2); padding: 0.15em 0.4em; border-radius: 6px; }
.code { position: relative; margin: 1.25rem 0 1.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
.code-head { display: flex; justify-content: space-between; align-items: center; padding: 0.45rem 0.6rem 0.45rem 1rem; border-bottom: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; font-family: var(--mono); }
.code pre { margin: 0; padding: 1rem; overflow-x: auto; font-family: var(--mono); font-size: 0.9rem; line-height: 1.65; }
.copy { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.3rem 0.6rem; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); font: inherit; font-size: 0.78rem; cursor: pointer; }
.callout { display: flex; gap: 0.85rem; padding: 1rem 1.15rem; margin: 1.5rem 0; border-radius: var(--radius); background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--accent); }
.callout .icon { color: var(--accent); margin-top: 0.2rem; }
.callout p { margin: 0; }
.callout.warn { border-left-color: var(--muted); }
.callout.warn .icon { color: var(--muted); }
.table-wrap { overflow-x: auto; margin: 1.25rem 0 1.5rem; border: 1px solid var(--border); border-radius: var(--radius); }
table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
th, td { text-align: left; padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--surface); font-weight: 650; }
tr:last-child td { border-bottom: 0; }
td:first-child { white-space: nowrap; }
.cards { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr)); margin: 1.5rem 0; }
.cards a { display: block; padding: 1.25rem; text-decoration: none; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); transition: border-color 0.15s ease; }
.cards a:hover { border-color: var(--accent); }
.cards .icon { color: var(--accent); margin-bottom: 0.6rem; }
.cards b { display: block; margin-bottom: 0.2rem; }
.cards span { color: var(--muted); font-size: 0.925rem; }
.pager { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); margin-top: 3.5rem; padding-top: 2rem; border-top: 1px solid var(--border); }
.pager a { display: block; padding: 1rem 1.25rem; border: 1px solid var(--border); border-radius: var(--radius); text-decoration: none; }
.pager a:hover { border-color: var(--accent); }
.pager small { display: block; color: var(--muted); }
.pager b { color: var(--accent); }
.pager .next { text-align: right; grid-column: -2; }
.toc { display: none; }
.toc h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted); margin: 0 0 0.75rem; }
.toc ul { list-style: none; margin: 0; padding: 0 0 0 0.9rem; border-left: 1px solid var(--border); display: grid; gap: 0.45rem; }
.toc a { color: var(--muted); text-decoration: none; font-size: 0.9rem; }
.toc a:hover { color: var(--accent); }
.docs .site-footer .footer-inner { width: min(100% - 2.5rem, 1320px); }
.docs .container { width: min(100% - 2.5rem, 1320px); }
@media (min-width: 900px) {
  .search { flex: 0 1 18rem; order: 0; margin-left: auto; }
  .docs-shell { grid-template-columns: 250px minmax(0, 1fr); gap: 3rem; }
  .sidebar, .js .sidebar { display: block; position: sticky; top: 4.5rem; max-height: calc(100vh - 4.5rem); overflow-y: auto; border: 0; padding: 2.25rem 0; }
  .doc { padding-top: 2.5rem; max-width: 48rem; }
  .js .docs .nav-toggle { display: none; }
}
@media (min-width: 1240px) {
  .docs-shell { grid-template-columns: 250px minmax(0, 1fr) 200px; }
  .toc { display: block; position: sticky; top: 4.5rem; padding: 2.75rem 0; }
}
'''

TEMPLATE_CSS = {'landing': LANDING_CSS, 'portfolio': PORTFOLIO_CSS, 'blog': BLOG_CSS,
                'link_in_bio': BIO_CSS, 'docs': DOCS_CSS}

SCRIPT_JS = r'''/* Small progressive enhancements. Every feature checks its elements exist first. */
(function () {
  'use strict';
  var root = document.documentElement;
  root.classList.add('js');

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  // Mobile navigation: <button data-nav-toggle aria-controls="ID"> opens/closes #ID.
  Array.prototype.forEach.call(document.querySelectorAll('[data-nav-toggle]'), function (button) {
    var target = document.getElementById(button.getAttribute('aria-controls') || '');
    if (!target) return;
    function setOpen(open) {
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      target.classList.toggle('is-open', open);
    }
    button.addEventListener('click', function () {
      setOpen(button.getAttribute('aria-expanded') !== 'true');
    });
    target.addEventListener('click', function (event) {
      if (event.target.closest && event.target.closest('a')) setOpen(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        button.focus();
      }
    });
  });

  // Smooth scrolling for same-page links (instant when the user prefers reduced motion).
  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href^="#"]');
    if (!link) return;
    var id = decodeURIComponent(link.getAttribute('href').slice(1));
    var target = id && document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
    try { history.replaceState(null, '', '#' + id); } catch (e) {}
  });

  // Current year in the footer.
  Array.prototype.forEach.call(document.querySelectorAll('[data-year]'), function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  // Docs: filter the sidebar links as you type.
  var filter = document.querySelector('[data-filter]');
  var sidebar = document.getElementById('docs-sidebar');
  if (filter && sidebar) {
    var empty = sidebar.querySelector('.empty');
    filter.addEventListener('input', function () {
      var query = filter.value.trim().toLowerCase();
      var shown = 0;
      Array.prototype.forEach.call(sidebar.querySelectorAll('li'), function (item) {
        var match = !query || item.textContent.toLowerCase().indexOf(query) !== -1;
        item.hidden = !match;
        if (match) shown += 1;
      });
      if (empty) empty.hidden = shown !== 0;
      if (query && !sidebar.classList.contains('is-open')) sidebar.classList.add('is-open');
    });
  }

  // Docs: copy buttons next to code blocks.
  Array.prototype.forEach.call(document.querySelectorAll('[data-copy]'), function (button) {
    button.addEventListener('click', function () {
      var block = button.closest('.code');
      var code = block && block.querySelector('pre');
      if (!code) return;
      var label = button.querySelector('span');
      function done(text) {
        if (!label) return;
        label.textContent = text;
        setTimeout(function () { label.textContent = 'Copy'; }, 1600);
      }
      try {
        navigator.clipboard.writeText(code.textContent).then(function () { done('Copied'); }, function () { done('Select & copy'); });
      } catch (e) { done('Select & copy'); }
    });
  });
})();
'''


# ---------------------------------------------------------------- decorative SVG art

def art_svg(colors, seed, label=''):
    """Abstract cover art (inline SVG, decorative): gradient + soft shapes, varied by seed."""
    a, b = colors
    gid = f'g{seed}'
    variants = [
        f'<circle cx="78%" cy="30%" r="32%" fill="#fff" fill-opacity=".16"/><circle cx="20%" cy="85%" r="26%" fill="#000" fill-opacity=".14"/>'
        f'<rect x="18%" y="28%" width="42%" height="44%" rx="18" fill="#fff" fill-opacity=".18"/>',
        f'<path d="M0 70 Q 25 40 50 62 T 100 48 V100 H0Z" fill="#fff" fill-opacity=".18"/>'
        f'<path d="M0 82 Q 30 62 55 78 T 100 70 V100 H0Z" fill="#000" fill-opacity=".14"/>'
        f'<circle cx="74" cy="26" r="11" fill="#fff" fill-opacity=".28"/>',
        f'<g fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.4"><circle cx="50" cy="50" r="14"/>'
        f'<circle cx="50" cy="50" r="24"/><circle cx="50" cy="50" r="34"/><circle cx="50" cy="50" r="44"/></g>'
        f'<circle cx="50" cy="50" r="7" fill="#fff" fill-opacity=".5"/>',
        f'<g fill="#fff" fill-opacity=".2"><rect x="10" y="14" width="34" height="34" rx="6"/><rect x="52" y="14" width="38" height="20" rx="6"/>'
        f'<rect x="52" y="40" width="38" height="46" rx="6"/><rect x="10" y="54" width="34" height="32" rx="6"/></g>',
        f'<g fill="#fff" fill-opacity=".22"><polygon points="0,100 38,30 70,100"/></g>'
        f'<g fill="#000" fill-opacity=".14"><polygon points="40,100 72,46 100,100"/></g><circle cx="78" cy="22" r="8" fill="#fff" fill-opacity=".35"/>',
        f'<g stroke="#fff" stroke-opacity=".24" stroke-width="3">' +
        ''.join(f'<line x1="{x}" y1="0" x2="{x - 40}" y2="100"/>' for x in range(10, 150, 14)) + '</g>',
    ]
    shapes = variants[seed % len(variants)]
    view = 'viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice"' if seed % len(variants) in (1, 2, 3, 4, 5) \
        else 'viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice"'
    title = f'<title>{esc(label)}</title>' if label else ''
    hidden = '' if label else ' aria-hidden="true" focusable="false"'
    role = ' role="img"' if label else ''
    return (f'<svg {view}{role}{hidden} xmlns="http://www.w3.org/2000/svg">{title}<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>'
            f'<rect width="100%" height="100%" fill="url(#{gid})"/>{shapes}</svg>')


def avatar_svg(ctx, gid='av', size=200):
    accent, fg = ctx['hex']['accent'], ctx['hex']['accent-contrast']
    b1, b2 = ctx['hex']['brand'], ctx['hex']['brand-2']
    letters = esc(monogram(ctx['raw_title']))
    font = 84 if len(letters) <= 1 else 72
    return (f'<svg viewBox="0 0 {size} {size}" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{b1}"/>'
            f'<stop offset="1" stop-color="{b2}"/></linearGradient></defs>'
            f'<rect width="{size}" height="{size}" fill="url(#{gid})"/>'
            f'<circle cx="{size * .5}" cy="{size * .5}" r="{size * .36}" fill="{accent}"/>'
            f'<text x="50%" y="{size * .5 + font * .35:.0f}" text-anchor="middle" font-family="system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif" '
            f'font-size="{font}" font-weight="800" fill="{fg}">{letters}</text></svg>')


# ---------------------------------------------------------------- templates

# Page-section names a model may pass by mistake; the templates already include these sections.
PAGE_NAMES = {'home', 'about', 'about me', 'about us', 'contact', 'contact me', 'contact us', 'work', 'projects',
              'portfolio', 'blog', 'posts', 'services', 'pricing', 'faq', 'features', 'testimonials', 'team',
              'gallery', 'hero', 'footer', 'header', 'bio', 'skills', 'resume', 'cv'}


def _items(sections, defaults, limit, drop_page_names=False):
    items = [s for s in (sections or []) if not (drop_page_names and s.strip().lower() in PAGE_NAMES)][:limit]
    return items or list(defaults[:limit])


def landing(ctx):
    t = ctx['title']
    defaults = ['Fast setup', 'Built-in analytics', 'Secure by default', 'Works everywhere', 'Made for teams', 'Friendly support']
    fallbacks = ['bolt', 'chart', 'shield', 'globe', 'users', 'heart']
    features = _items(ctx['sections'], defaults, 6, drop_page_names=True)
    cards = []
    for i, name in enumerate(features):
        ic = icon_for(name, fallbacks[i % len(fallbacks)])
        cards.append(f'''          <li class="card feature">
            <span class="feature-icon">{icon(ic, 22)}</span>
            <h3>{esc(name)}</h3>
            <p>Explain in one or two sentences what &ldquo;{esc(name)}&rdquo; does for your customers. Keep it concrete.</p>
          </li>''')
    nav = [('Features', '#features'), ('How it works', '#how'), ('Pricing', '#pricing'), ('FAQ', '#faq')]
    cta = '\n        <a class="btn btn-primary" href="#cta">Get started</a>'
    plans = [
        ('Starter', '$0', 'For trying things out.', ['Up to 3 projects', 'Core features', 'Community support'], False, 'Start free'),
        ('Pro', '$19', 'For growing teams.', ['Unlimited projects', 'Everything in Starter', 'Priority support', 'Advanced insights'], True, 'Start a free trial'),
        ('Business', '$49', 'For larger organisations.', ['Everything in Pro', 'Single sign-on', 'Dedicated manager'], False, 'Contact sales'),
    ]
    plan_html = []
    for name, price, blurb, perks, featured, button in plans:
        perks_html = ''.join(f'<li>{icon("check", 18)}<span>{esc(p)}</span></li>' for p in perks)
        plan_html.append(f'''          <article class="card plan{' featured' if featured else ''}">
            {'<span class="tag">Most popular</span>' if featured else ''}
            <h3>{name}</h3>
            <p class="muted">{blurb}</p>
            <p class="price">{price} <small>/ month</small></p>
            <ul>{perks_html}</ul>
            <a class="btn {'btn-primary' if featured else 'btn-ghost'}" href="#cta">{button}</a>
          </article>''')
    faqs = [
        ('What is ' + ctx['raw_title'] + '?', 'Answer the most common question in two or three short sentences. Replace this sample text in index.html.'),
        ('How much does it cost?', 'Summarise your pricing here and link to the pricing section above.'),
        ('Can I cancel at any time?', 'Explain your cancellation or refund policy in plain words.'),
        ('How do I get help?', 'Tell visitors how to reach you: email, chat or a help centre.'),
    ]
    faq_html = ''.join(f'''
          <details>
            <summary>{esc(q)}</summary>
            <p>{esc(a)}</p>
          </details>''' for q, a in faqs)
    body = f'''{_header(ctx, nav, cta)}
  <main id="main">
    <section class="hero" aria-labelledby="hero-title">
      <div class="container hero-grid">
        <div>
          <p class="badge"><span class="chip">New</span> Introducing {t}</p>
          <h1 id="hero-title">{t}</h1>
          <p class="lead">{ctx['tagline']}</p>
          <div class="btn-row">
            <a class="btn btn-primary" href="#cta">Get started {icon('arrow', 18)}</a>
            <a class="btn btn-ghost" href="#features">See features</a>
          </div>
          <p class="hero-note">{icon('check', 16)} Free plan available. No credit card needed.</p>
          <dl class="stats">
            <div><dt>Happy customers</dt><dd>10k+</dd></div>
            <div><dt>Average rating</dt><dd>4.9/5</dd></div>
            <div><dt>Uptime</dt><dd>99.9%</dd></div>
          </dl>
        </div>
        <div class="card mock" aria-hidden="true">
          <div class="mock-bar"><span></span><span></span><span></span></div>
          <div class="mock-body">
            <div class="mock-stats">
              <div class="mock-stat"><b>2,481</b><small>Visitors</small></div>
              <div class="mock-stat"><b>+18%</b><small>Growth</small></div>
              <div class="mock-stat"><b>312</b><small>Sign-ups</small></div>
            </div>
            <div class="mock-chart"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
            <div class="mock-rows">
              <div class="mock-row"><i></i><span></span><span></span></div>
              <div class="mock-row"><i></i><span></span><span></span></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section" id="features" aria-labelledby="features-title">
      <div class="container">
        <div class="section-head">
          <p class="eyebrow">Features</p>
          <h2 id="features-title">Everything you need, nothing you don't</h2>
          <p>Use this paragraph to sum up the main benefit of {t} in one sentence.</p>
        </div>
        <ul class="features{' two-col' if len(features) in (2, 4) else ''}">
{chr(10).join(cards)}
        </ul>
      </div>
    </section>

    <section class="section alt" id="how" aria-labelledby="how-title">
      <div class="container">
        <div class="section-head">
          <p class="eyebrow">How it works</p>
          <h2 id="how-title">Up and running in three steps</h2>
        </div>
        <ol class="steps">
          <li><h3>Create your account</h3><p>Describe the first thing a new customer does.</p></li>
          <li><h3>Set things up</h3><p>Describe the setup step and how long it takes.</p></li>
          <li><h3>See results</h3><p>Describe the outcome your customers care about.</p></li>
        </ol>
      </div>
    </section>

    <section class="section" aria-label="Customer story">
      <div class="container">
        <figure class="quote">
          <blockquote><p>&ldquo;Put a short, specific quote from a real customer here. Specific results beat general praise.&rdquo;</p></blockquote>
          <figcaption><span class="avatar" aria-hidden="true">AC</span><span><b>Alex Customer</b>Role, Company name</span></figcaption>
        </figure>
      </div>
    </section>

    <section class="section alt" id="pricing" aria-labelledby="pricing-title">
      <div class="container">
        <div class="section-head">
          <p class="eyebrow">Pricing</p>
          <h2 id="pricing-title">Simple, honest pricing</h2>
          <p>Sample plans: change the names, prices and perks to match your offer.</p>
        </div>
        <div class="pricing">
{chr(10).join(plan_html)}
        </div>
      </div>
    </section>

    <section class="section" id="faq" aria-labelledby="faq-title">
      <div class="container">
        <div class="section-head">
          <p class="eyebrow">FAQ</p>
          <h2 id="faq-title">Questions, answered</h2>
        </div>
        <div class="faq">{faq_html}
        </div>
      </div>
    </section>

    <section class="section" id="cta" aria-labelledby="cta-title">
      <div class="container">
        <div class="card cta-band">
          <h2 id="cta-title">Ready to try {t}?</h2>
          <p>End with one clear call to action. Point this button at your sign-up page or email address.</p>
          <div class="btn-row">
            <a class="btn btn-primary" href="mailto:hello@example.com">Get started {icon('arrow', 18)}</a>
            <a class="btn btn-ghost" href="#features">Learn more</a>
          </div>
        </div>
      </div>
    </section>
  </main>
{_footer(ctx, 'All rights reserved.', [('Features', '#features'), ('Pricing', '#pricing'), ('FAQ', '#faq'), ('Contact', 'mailto:hello@example.com')])}'''
    return {'index.html': _page(ctx, title=page_title(ctx['raw_title'], ''), description=ctx['description'], body=body)}


def portfolio(ctx):
    t = ctx['title']
    defaults = ['Brand identity refresh', 'Mobile banking app', 'Editorial website', 'Product launch campaign']
    work = _items(ctx['sections'], defaults, 6, drop_page_names=True)
    if len(work) % 2:
        pass  # odd counts are fine: the last card simply sits alone on a row
    colors = _thumb_colors(ctx['tokens'], len(work))
    tags = [('Branding', 'Strategy'), ('UX/UI', 'iOS'), ('Web design', 'Development'), ('Campaign', 'Art direction'),
            ('Research', 'Prototyping'), ('Motion', 'Illustration')]
    cards = []
    for i, name in enumerate(work):
        chip_html = ''.join(f'<li class="chip">{c}</li>' for c in tags[i % len(tags)])
        cards.append(f'''          <li class="card project">
            <div class="thumb">{art_svg(colors[i], i)}</div>
            <div class="project-body">
              <ul class="chips" aria-label="Tags">{chip_html}</ul>
              <h3>{esc(name)}</h3>
              <p>Describe this project here: the problem, your role and the result in two sentences.</p>
              <div class="project-meta"><span>{ctx['year'] - (i // 2)}</span><a href="#contact">Ask about this project {icon('arrow', 16)}</a></div>
            </div>
          </li>''')
    nav = [('Work', '#work'), ('About', '#about'), ('Contact', '#contact')]
    cta = '\n        <a class="btn btn-primary" href="mailto:hello@example.com">Say hello</a>'
    skills = ''.join(f'<li class="chip">{s}</li>' for s in ('Product design', 'Design systems', 'Prototyping', 'Front-end', 'Art direction'))
    body = f'''{_header(ctx, nav, cta)}
  <main id="main">
    <section class="intro" aria-labelledby="intro-title">
      <div class="container">
        <p class="status"><span class="pulse" aria-hidden="true"></span> Available for new projects</p>
        <h1 id="intro-title">{t}<span class="dot">.</span></h1>
        <p class="lead">{ctx['tagline']}</p>
        <div class="btn-row">
          <a class="btn btn-primary" href="#work">View my work {icon('arrow', 18)}</a>
          <a class="btn btn-ghost" href="#contact">Get in touch</a>
        </div>
      </div>
    </section>

    <section class="section work" id="work" aria-labelledby="work-title">
      <div class="container">
        <div class="work-head">
          <h2 id="work-title">Selected work</h2>
          <p>A few projects I'm proud of. Replace these cards with your own case studies.</p>
        </div>
        <ul class="projects">
{chr(10).join(cards)}
        </ul>
      </div>
    </section>

    <section class="section" id="about" aria-labelledby="about-title">
      <div class="container about-grid">
        <figure class="card portrait">
          {avatar_svg(ctx, 'portrait')}
          <!-- Replace the SVG above with a photo: <img src="me.jpg" alt="Portrait of {t}" width="320" height="320"> -->
          <figcaption>Your photo goes here</figcaption>
        </figure>
        <div class="about-text">
          <p class="eyebrow">About</p>
          <h2 id="about-title">A little about me</h2>
          <p class="lead">Write one sentence that says who you are and what you love working on.</p>
          <p>Add a short paragraph about your background, the kind of clients or teams you work with, and what makes your approach different. Keep it friendly and specific.</p>
          <ul class="chips skills" aria-label="Skills">{skills}</ul>
          <ol class="timeline" reversed>
            <li><span>{ctx['year'] - 2} &ndash; now</span><div><b>Your current role</b><small>Company or freelance</small></div></li>
            <li><span>{ctx['year'] - 5} &ndash; {ctx['year'] - 2}</span><div><b>Previous role</b><small>Company name</small></div></li>
            <li><span>{ctx['year'] - 7} &ndash; {ctx['year'] - 5}</span><div><b>Where you started</b><small>School or first job</small></div></li>
          </ol>
        </div>
      </div>
    </section>

    <section class="section contact" id="contact" aria-labelledby="contact-title">
      <div class="container">
        <p class="eyebrow">Contact</p>
        <h2 id="contact-title">Let's work together</h2>
        <p>Tell visitors how you like to be contacted and how quickly you usually reply.</p>
        <a class="big-link" href="mailto:hello@example.com">{icon('mail', 28)} hello@example.com</a>
        <ul class="socials">
          <li><a href="https://example.com/" aria-label="Website (replace link)">{icon('globe', 20)}</a></li>
          <li><a href="https://example.com/" aria-label="Code profile (replace link)">{icon('code', 20)}</a></li>
          <li><a href="https://example.com/" aria-label="Photos (replace link)">{icon('camera', 20)}</a></li>
        </ul>
      </div>
    </section>
  </main>
{_footer(ctx, 'Designed and built with care.', [('Work', '#work'), ('About', '#about'), ('Email', 'mailto:hello@example.com')])}'''
    return {'index.html': _page(ctx, title=f"{ctx['raw_title']} — Portfolio", description=ctx['description'], body=body)}


def _post_files(titles):
    out, used = [], {'index'}
    for i, title in enumerate(titles):
        name = 'first-post' if i == 0 else projects.slug(title)
        base, n = name, 2
        while name in used:
            name = f'{base}-{n}'
            n += 1
        used.add(name)
        out.append((title, f'posts/{name}.html'))
    return out


def blog(ctx):
    t = ctx['title']
    defaults = ['Welcome to my blog', 'What I am working on right now', 'Five lessons from my first year']
    titles = _items(ctx['sections'], defaults, 4, drop_page_names=True)
    posts = _post_files(titles)
    colors = _thumb_colors(ctx['tokens'], len(posts))
    today = ctx['today']
    dates = [today - datetime.timedelta(days=9 * i) for i in range(len(posts))]
    tags = ['Updates', 'Notes', 'Ideas', 'Guides']
    excerpts = [
        'This is your first post. Open posts/first-post.html to replace it with your own words.',
        'A short summary of this post goes here. One or two sentences that make people want to read on.',
        'Write a teaser for this post. Mention the main idea and why it matters to your readers.',
        'Another post summary. Keep excerpts short so the list stays easy to scan.',
    ]

    def meta(i):
        d = dates[i]
        return (f'<p class="post-meta"><span>{icon("calendar", 15)}<time datetime="{d.isoformat()}">'
                f'{d.strftime("%b")} {d.day}, {d.year}</time></span><span>{icon("clock", 15)}{4 + i} min read</span></p>')

    nav = [('Posts', '#posts'), ('About', '#about'), ('Email', 'mailto:hello@example.com')]
    items = []
    for i, (title, href) in enumerate(posts[1:], 1):
        items.append(f'''          <li class="post-item"><a href="{href}">
            {meta(i)}
            <h3>{esc(title)}</h3>
            <p>{excerpts[i % len(excerpts)]}</p>
            <span class="read-more">Read post {icon('arrow', 16)}</span>
          </a></li>''')
    more = (f'''
        <h2 class="visually-hidden">More posts</h2>
        <ul class="posts">
{chr(10).join(items)}
        </ul>''' if items else '')
    body = f'''{_header(ctx, nav)}
  <main id="main">
    <section class="blog-hero" aria-labelledby="blog-title">
      <div class="container">
        <p class="eyebrow">{icon('pen', 16)} The blog</p>
        <h1 id="blog-title">{t}</h1>
        <p class="lead">{ctx['tagline']}</p>
      </div>
    </section>
    <section class="blog-layout" id="posts" aria-label="Posts">
      <div class="container">
        <a class="card featured" href="{posts[0][1]}">
          <div class="cover">{art_svg(colors[0], 1)}</div>
          <div class="featured-body">
            <p class="eyebrow">Latest post &middot; {tags[0]}</p>
            <h2>{esc(posts[0][0])}</h2>
            <p>{excerpts[0]}</p>
            {meta(0)}
            <span class="read-more">Read post {icon('arrow', 16)}</span>
          </div>
        </a>{more}
        <aside class="card author" id="about" aria-labelledby="about-title">
          <img src="favicon.svg" alt="{t} logo" width="72" height="72">
          <div>
            <h2 id="about-title">About {t}</h2>
            <p>Introduce yourself in two sentences: who writes here, what you write about and how often.</p>
          </div>
        </aside>
      </div>
    </section>
  </main>
{_footer(ctx, 'Thanks for reading.', nav)}'''
    files = {'index.html': _page(ctx, title=f"{ctx['raw_title']} — Blog", description=ctx['description'], body=body)}
    for i, (title, href) in enumerate(posts):
        prev_link = f'<a href="../{posts[i - 1][1]}">{icon("arrow-left", 16)} Newer post</a>' if i > 0 else '<span></span>'
        next_link = f'<a href="../{posts[i + 1][1]}">Older post {icon("arrow", 16)}</a>' if i + 1 < len(posts) else ''
        intro = ('This is your first post. Everything on this page is sample text: replace it with your own story. '
                 'Start with a sentence that tells readers what they will get from reading on.' if i == 0 else
                 'This is a sample post. Replace this introduction with the opening of your article and keep paragraphs short.')
        sub_nav = [('Posts', '../index.html#posts'), ('About', '../index.html#about'), ('Email', 'mailto:hello@example.com')]
        article = f'''{_header(ctx, sub_nav, depth=1)}
  <main id="main">
    <article class="article">
      <div class="container">
        <header class="article-head">
          <a class="back" href="../index.html">{icon('arrow-left', 16)} All posts</a>
          <p class="eyebrow">{tags[i % len(tags)]}</p>
          <h1>{esc(title)}</h1>
          {meta(i)}
        </header>
        <div class="cover">{art_svg(colors[i], i + 1)}</div>
        <div class="prose">
          <p>{intro}</p>
          <h2>A section heading</h2>
          <p>Break longer posts into sections with clear headings. Readers skim first, so make each heading say something useful.</p>
          <ul>
            <li>Use lists for steps or key points.</li>
            <li>Link to related posts or sources, like the <a href="../index.html#posts">full post list</a>.</li>
            <li>Keep one main idea per paragraph.</li>
          </ul>
          <blockquote><p>Pull out one memorable line as a quote to give the page rhythm.</p></blockquote>
          <h2>Wrapping up</h2>
          <p>End with a short summary or a question for your readers. You can show code too, for example <code>npm run build</code>.</p>
        </div>
        <nav class="post-nav" aria-label="More posts">{prev_link}{next_link}</nav>
      </div>
    </article>
  </main>
{_footer(ctx, 'Thanks for reading.')}'''
        excerpt = excerpts[i % len(excerpts)]
        files[href] = _page(ctx, title=f"{title} — {ctx['raw_title']}", description=excerpt, body=article, depth=1)
    return files


def link_in_bio(ctx):
    t = ctx['title']
    defaults = ['My website', 'Latest video', 'Newsletter', 'Shop', 'Podcast']
    links = _items(ctx['sections'], defaults, 8)
    fallbacks = ['globe', 'link', 'star', 'link']
    subtitles = {'play': 'Watch now', 'mail': 'Get updates by email', 'bag': 'Browse the collection',
                 'mic': 'New episodes weekly', 'music': 'Listen now', 'camera': 'See the latest photos',
                 'code': 'See my projects', 'book': 'Read the latest', 'globe': 'Everything in one place',
                 'calendar': 'See what is coming up', 'heart': 'Support my work'}
    items = []
    for i, label in enumerate(links):
        ic = icon_for(label, fallbacks[i % len(fallbacks)])
        sub = subtitles.get(ic, 'Replace this link')
        items.append(f'''        <li><a class="link-btn{' primary' if i == 0 else ''}" href="https://example.com/">
          <span class="link-icon">{icon(ic, 22)}</span>
          <span class="link-text">{esc(label)}<small>{sub}</small></span>
          <span class="arrow">{icon('arrow', 18)}</span>
        </a></li>''')
    handle = '@' + (re.sub(r'[^a-z0-9]', '', ctx['raw_title'].lower())[:24] or 'yourname')
    colors = _thumb_colors(ctx['tokens'], 2)
    body = f'''  <div class="bio-wrap">
    <header class="bio-header">
      <div class="bio-avatar">{avatar_svg(ctx, 'bioav')}</div>
      <h1>{t}</h1>
      <p class="handle">{esc(handle)}</p>
      <p class="tagline">{ctx['tagline']}</p>
      <nav aria-label="Social profiles">
        <ul class="bio-socials">
          <li><a href="https://example.com/" aria-label="Photos (replace link)">{icon('camera', 20)}</a></li>
          <li><a href="https://example.com/" aria-label="Videos (replace link)">{icon('play', 20)}</a></li>
          <li><a href="https://example.com/" aria-label="Music (replace link)">{icon('music', 20)}</a></li>
          <li><a href="mailto:hello@example.com" aria-label="Email">{icon('mail', 20)}</a></li>
        </ul>
      </nav>
    </header>
    <main id="main">
      <h2 class="visually-hidden">Links</h2>
      <ul class="links">
{chr(10).join(items)}
      </ul>
      <section class="card spotlight" aria-labelledby="spotlight-title">
        <div class="cover">{art_svg(colors[1], 2)}</div>
        <div>
          <h2 id="spotlight-title">Spotlight</h2>
          <p>Feature your newest thing here: a release, an event or a project. Replace this text.</p>
        </div>
      </section>
    </main>
{_footer(ctx)}
  </div>'''
    return {'index.html': _page(ctx, title=page_title(ctx['raw_title'], 'Links'), description=ctx['description'], body=body, body_class='bio')}


def _doc_pages(sections):
    pages, used = [('index.html', 'Introduction')], {'index'}
    skip = {'introduction', 'intro', 'home', 'overview', 'index'}
    names = [s for s in sections if s.strip().lower() not in skip][:4] if sections else []
    for name in names or ['Getting started', 'Configuration']:
        base = projects.slug(name)
        file, n = base, 2
        while file in used:
            file = f'{base}-{n}'
            n += 1
        used.add(file)
        pages.append((f'{file}.html', name))
    return pages


def docs(ctx):
    t, raw = ctx['title'], ctx['raw_title']
    pages = _doc_pages(ctx['sections'])
    cmd = projects.slug(raw)
    files = {}
    for i, (href, name) in enumerate(pages):
        side = []
        for h2, n2 in pages:
            here = ' aria-current="page"' if h2 == href else ''
            ic = 'book' if h2 == 'index.html' else 'file'
            side.append(f'<li><a href="{h2}"{here}>{icon(ic, 16)}{esc(n2)}</a></li>')
        sidebar = f'''      <nav class="sidebar" id="docs-sidebar" aria-label="Documentation">
        <h2>Guide</h2>
        <ul>{''.join(side)}</ul>
        <p class="empty" hidden>No pages match your search.</p>
        <h2>Resources</h2>
        <ul><li><a href="index.html#help">{icon('info', 16)}Getting help</a></li></ul>
      </nav>'''
        if i == 0:
            heads = [('what', f'What is {raw}?'), ('features', 'Key features'), ('quick', 'Quick start'), ('help', 'Getting help')]
            cards = ''.join(f'<a href="{h2}">{icon("file", 20)}<b>{esc(n2)}</b><span>Short description of this page.</span></a>'
                            for h2, n2 in pages[1:])
            content = f'''          <p class="lead">{ctx['tagline']}</p>
          <div class="callout">{icon('info', 20)}<p><b>This is sample documentation.</b> Every page is plain HTML: edit the text, and add pages by copying one and linking it in the sidebar.</p></div>
          <h2 id="what">{esc(heads[0][1])}</h2>
          <p>Describe what {t} does, who it is for and what problem it solves. Two short paragraphs are usually enough.</p>
          <h2 id="features">Key features</h2>
          <ul>
            <li><b>First feature</b> &ndash; one line on why it matters.</li>
            <li><b>Second feature</b> &ndash; one line on why it matters.</li>
            <li><b>Third feature</b> &ndash; one line on why it matters.</li>
          </ul>
          <h2 id="quick">Quick start</h2>
          <p>Show the fastest way to try it. Replace this example command with your own.</p>
          <div class="code"><div class="code-head"><span>terminal</span><button class="copy" type="button" data-copy>{icon('copy', 14)}<span>Copy</span></button></div><pre><code>{esc(cmd)} init my-project
cd my-project
{esc(cmd)} start</code></pre></div>
          <div class="cards">{cards}</div>
          <h2 id="help">Getting help</h2>
          <p>Tell readers where to ask questions, for example by email at <a href="mailto:hello@example.com">hello@example.com</a>.</p>'''
        else:
            heads = [('overview', 'Overview'), ('steps', 'Step by step'), ('example', 'Example'), ('options', 'Options')]
            content = f'''          <p class="lead">One sentence on what this page covers and when someone needs it.</p>
          <h2 id="overview">Overview</h2>
          <p>Explain the idea behind <b>{esc(name)}</b> before the details. Link related pages, like the <a href="index.html">introduction</a>.</p>
          <h2 id="steps">Step by step</h2>
          <ol>
            <li>Describe the first step.</li>
            <li>Describe the second step. Mention any setting with <code>inline code</code>.</li>
            <li>Describe how to check that it worked.</li>
          </ol>
          <div class="callout warn">{icon('alert', 20)}<p><b>Heads up:</b> use a callout like this for common mistakes or important warnings.</p></div>
          <h2 id="example">Example</h2>
          <div class="code"><div class="code-head"><span>config.json</span><button class="copy" type="button" data-copy>{icon('copy', 14)}<span>Copy</span></button></div><pre><code>{{
  "name": "my-project",
  "option": true,
  "level": 2
}}</code></pre></div>
          <h2 id="options">Options</h2>
          <div class="table-wrap"><table>
            <thead><tr><th scope="col">Option</th><th scope="col">Default</th><th scope="col">Description</th></tr></thead>
            <tbody>
              <tr><td><code>name</code></td><td>&ndash;</td><td>Describe what this option does.</td></tr>
              <tr><td><code>option</code></td><td><code>false</code></td><td>Describe what this option does.</td></tr>
              <tr><td><code>level</code></td><td><code>1</code></td><td>Describe the allowed values.</td></tr>
            </tbody>
          </table></div>'''
        toc = ''.join(f'<li><a href="#{hid}">{esc(label)}</a></li>' for hid, label in heads)
        prev_link = (f'<a class="prev" href="{pages[i - 1][0]}"><small>Previous</small><b>{esc(pages[i - 1][1])}</b></a>'
                     if i > 0 else '')
        next_link = (f'<a class="next" href="{pages[i + 1][0]}"><small>Next</small><b>{esc(pages[i + 1][1])}</b></a>'
                     if i + 1 < len(pages) else '')
        search = (f'<div class="search" role="search"><label class="visually-hidden" for="filter">Filter pages</label>'
                  f'{icon("search", 16)}<input id="filter" type="search" placeholder="Filter pages&hellip;" '
                  f'autocomplete="off" data-filter></div>')
        header = f'''  <header class="site-header">
    <div class="container header-inner">
      <a class="brand" href="index.html"><img src="favicon.svg" alt="" width="30" height="30"><span>{t}</span> <span class="chip docs-badge">Docs</span></a>
      {search}
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="docs-sidebar" data-nav-toggle>
        <span class="visually-hidden">Pages</span>{icon('menu', 22)}
      </button>
    </div>
  </header>'''
        body = f'''{header}
  <div class="container docs-shell">
{sidebar}
    <main id="main" class="doc">
      <article>
        <nav aria-label="Breadcrumb"><ol class="crumbs"><li><a href="index.html">Docs</a></li><li aria-current="page">{esc(name)}</li></ol></nav>
        <h1>{esc(name) if i else t}</h1>
{content}
        <nav class="pager" aria-label="Previous and next page">{prev_link}{next_link}</nav>
      </article>
    </main>
    <aside class="toc" aria-labelledby="toc-title">
      <h2 id="toc-title">On this page</h2>
      <ul>{toc}</ul>
    </aside>
  </div>
{_footer(ctx, 'Documentation.')}'''
        title = f'{raw} Docs' if i == 0 else f'{name} — {raw} Docs'
        desc = ctx['description'] if i == 0 else f'{name} in the {raw} docs: overview, step-by-step guide, example and options.'
        files[href] = _page(ctx, title=title, description=desc, body=body, body_class='docs')
    return files


BUILDERS = {'landing': landing, 'portfolio': portfolio, 'blog': blog, 'link_in_bio': link_in_bio, 'docs': docs}

TAGLINES = {
    'landing': 'Say what you offer and who it is for in one clear sentence. Edit this line in index.html.',
    'portfolio': 'I design and build thoughtful digital products. Replace this line with your own one-sentence introduction.',
    'blog': 'Notes, ideas and stories. Replace this line with what your blog is about.',
    'link_in_bio': 'Creator, maker, storyteller. Replace this line with a short bio.',
    'docs': 'Everything you need to get started. Replace this line with a one-sentence summary of the project.',
}

PURPOSE = {
    'landing': 'A one-page marketing site for a product or service: hero, features, steps, testimonial, pricing, FAQ and a final call to action.',
    'portfolio': 'A personal portfolio: introduction, selected work grid, about section with timeline, and contact.',
    'blog': 'A simple blog: index page with a featured post and post list, plus one HTML page per post in posts/.',
    'link_in_bio': 'A single "link in bio" page: avatar, short bio, social icons, big link buttons and a spotlight card.',
    'docs': 'A documentation site: shared header with page filter, sidebar navigation, content pages, on-this-page TOC and prev/next links.',
}


def project_brief(ctx, template, files):
    hexes = ctx['hex']
    roles = {
        'bg': 'page background', 'surface': 'cards, header menus', 'surface-2': 'inputs, ghost buttons, code',
        'border': 'hairlines and card borders (not text)', 'text': 'main text', 'muted': 'secondary text',
        'accent': 'links, highlights, primary button background', 'accent-contrast': 'text on accent backgrounds',
        'accent-soft': 'chips and icon backgrounds (accent text on top)', 'brand': 'raw brand colour, decoration only (never text)',
        'brand-2': 'second gradient colour, decoration only',
    }
    describe = {
        'index.html': 'home page', 'styles.css': 'all styles; theme tokens at the top in :root',
        'script.js': 'mobile menu toggle, smooth scrolling, footer year' + (', docs filter and copy buttons' if template == 'docs' else ''),
        'favicon.svg': 'monogram icon in the accent colour (also used as the header logo)',
        'PROJECT_BRIEF.md': 'this file',
    }
    file_lines = []
    for rel in sorted(files):
        if rel.startswith('posts/'):
            note = 'blog post page (links back with ../)'
        elif template == 'docs' and rel.endswith('.html') and rel != 'index.html':
            note = 'documentation page'
        else:
            note = describe.get(rel, '')
        file_lines.append(f'- `{rel}` — {note}')
    token_lines = '\n'.join(f'| `--{k}` | `{hexes[k]}` | {roles[k]} |' for k in roles)
    how = {
        'landing': ('Copy an existing `<section class="section">` block inside `<main>`, give it a new `id` and an `<h2>`, '
                    'and add a link to it in the header `<nav>`. Alternate `class="section alt"` for a tinted band.',
                    'This is a one-page site. For a new page, copy `index.html`, keep the header/footer, replace `<main>` and link it from the nav.'),
        'portfolio': ('Add a project by copying one `<li class="card project">` in `#work`. Add a section by copying a '
                      '`<section class="section">` block and linking its `id` in the nav.',
                      'For a case-study page, copy `index.html` to e.g. `work-name.html`, keep header/footer, replace `<main>`, and link the project card to it.'),
        'blog': ('On the index, add posts to `<ul class="posts">` (copy a `<li class="post-item">`). The newest post goes in the featured card.',
                 'New post: copy `posts/first-post.html` to `posts/my-new-post.html`, edit title/date/text, then link it from `index.html` '
                 'and update the Newer/Older links. Paths inside posts/ start with `../`.'),
        'link_in_bio': ('Add a link by copying one `<li>` in `<ul class="links">` and changing the `href`, label and icon. '
                        'Only the first link uses `primary`.',
                        'Keep this a single page. Replace every `https://example.com/` with your real links.'),
        'docs': ('Inside a page, add an `<h2 id="...">` section and add the same id to the "On this page" list in `<aside class="toc">`.',
                 'New page: copy a page such as `' + next((f for f in files if f.endswith('.html') and f != 'index.html'), 'index.html') +
                 '`, change the `<title>`, `<h1>` and breadcrumb, then add it to the sidebar `<ul>` on EVERY page and fix the prev/next pager links.'),
    }[template]
    return f'''# {ctx['raw_title']} — project brief

Template: **{template}** · Theme: **{ctx['theme']}** · Brand colour: `{ctx['color_in']}`
Created by DreadOS `new_site`. Plain HTML/CSS/JS: no build step, no frameworks, no external files.

## Purpose
{PURPOSE[template]}
Most text is editable sample copy (it says so). Replace it with real content first.

## File map
{chr(10).join(file_lines)}

## Design tokens (CSS custom properties in `styles.css` `:root`)
| Token | Value | Use |
|---|---|---|
{token_lines}

Also: `--radius`, `--radius-lg`, `--shadow`, `--max` (content width), `--font` (system font stack), `--mono`.
To retheme, change the colour tokens only; components use `var(--token)`, never raw colours.
All text pairs (text/muted/accent on bg/surface/surface-2/accent-soft, accent-contrast on accent) pass WCAG AA 4.5:1.

## How to add a section
{how[0]}

## How to add a page
{how[1]}

## Rules
- Keep it mobile-first: base styles are for phones, wider layouts go in `@media (min-width: ...)` blocks. Check 390px and 1280px widths.
- Keep contrast at WCAG AA (4.5:1 for text). Put text only on bg, surface, surface-2, accent-soft, or accent (with accent-contrast). `--brand`/`--brand-2` are decoration only.
- Keep it dependency-free: no CDNs, web fonts, external images or scripts. The preview blocks external network. Use inline SVG, CSS gradients or local image files.
- Keep accessibility: one `<h1>` per page, `<html lang="en">`, header/nav/main/footer landmarks, alt text on every `<img>`, visible focus styles, the skip link, and `prefers-reduced-motion`.
- Keep `script.js` small and defensive (check elements exist). The site must work without JavaScript.
- Escape user-facing text properly in HTML (`&amp;`, `&lt;`).
'''


# ---------------------------------------------------------------- inputs

def _clean_text(value, field, limit, required=False):
    if value is None:
        if required:
            raise SiteError(f'{field} is required.')
        return ''
    if not isinstance(value, str):
        raise SiteError(f'{field} must be text.')
    value = ' '.join(value.split())
    if required and not value:
        raise SiteError(f'{field} must not be empty.')
    if len(value) > limit:
        raise SiteError(f'{field} is too long (max {limit} characters).')
    return value


def _enum(value, field, options, default=None):
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise SiteError(f'{field} must be one of: {", ".join(options)}.')
    norm = value.strip().lower().replace('-', '_').replace(' ', '_')
    if norm == 'linkinbio':
        norm = 'link_in_bio'
    if norm not in options:
        raise SiteError(f'Unknown {field} "{value[:40]}". Use one of: {", ".join(options)}.')
    return norm


def _sections(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise SiteError('sections must be a list of short strings, e.g. ["Fast setup", "Analytics"].')
    if len(value) > MAX_SECTIONS:
        raise SiteError(f'sections can have at most {MAX_SECTIONS} items.')
    out = []
    for item in value:
        if not isinstance(item, str):
            raise SiteError('Every item in sections must be text.')
        item = ' '.join(item.split())
        if len(item) > MAX_SECTION_LEN:
            raise SiteError(f'Each section hint must be at most {MAX_SECTION_LEN} characters.')
        if item:
            out.append(item)
    return out


def _free_name(requested, title):
    if requested:
        if not isinstance(requested, str) or not projects.NAME_RE.fullmatch(requested):
            raise SiteError('project_name must use lowercase letters, numbers and hyphens (e.g. "jazz-portfolio").')
        base = requested
    else:
        base = projects.slug(title)
    existing = set(projects.list_projects())
    if base not in existing and not (projects.PROJECTS / base).exists():
        return base
    stem = base[:47].rstrip('-') or 'my-site'
    for n in range(2, 10):
        name = f'{stem}-{n}'
        if name not in existing and not (projects.PROJECTS / name).exists():
            return name
    raise SiteError(f'Projects "{base}" and "{stem}-2" … "{stem}-9" already exist. Pass a different project_name.')


def generate_files(template, site_title, tagline='', color=DEFAULT_COLOR, theme='dark', sections=(), today=None):
    """{relative path: text} for a complete site (no writing)."""
    tokens = build_theme(color, theme)
    today = today or datetime.date.today()
    ctx = {
        'raw_title': site_title, 'title': esc(site_title),
        'tagline': esc(tagline or TAGLINES[template]),
        'description': describe_site(template, site_title, tagline),
        'sections': list(sections), 'tokens': tokens, 'theme': theme, 'color_in': color,
        'hex': {k: palette.hex_of(v) for k, v in tokens.items()}, 'year': today.year, 'today': today,
    }
    files = BUILDERS[template](ctx)
    files['styles.css'] = tokens_css(tokens, theme) + BASE_CSS + TEMPLATE_CSS[template]
    files['script.js'] = SCRIPT_JS
    files['favicon.svg'] = favicon_svg(tokens, site_title)
    files['PROJECT_BRIEF.md'] = project_brief(ctx, template, list(files) + ['PROJECT_BRIEF.md'])
    return files


DESCRIPTION_SUFFIX = {
    'landing': 'Learn what {t} offers, see pricing and get started.',
    'portfolio': 'Selected work, background and contact details for {t}.',
    'blog': 'Read the latest posts and notes from {t}.',
    'link_in_bio': "All of {t}'s links, socials and latest news in one place.",
    'docs': 'Guides, examples and reference documentation for {t}.',
}


def describe_site(template, title, tagline):
    """Meta description of 50-160 characters where possible."""
    suffix = DESCRIPTION_SUFFIX[template].format(t=title)
    if not tagline:
        return suffix
    if len(tagline) >= 50:
        return tagline
    joined = tagline.rstrip()
    if joined[-1:] not in '.!?':
        joined += '.'
    return f'{joined} {suffix}'[:160]


def page_title(base, suffix):
    """Page titles of at least 10 characters (search engines and the audit prefer 10-60)."""
    return base if len(base) >= 10 and not suffix else f'{base} — {suffix}' if suffix else f'{base} — Home'


FIRST_EDIT = {
    'landing': 'the hero headline and lead in index.html, then the feature cards and pricing',
    'portfolio': 'the intro line, then the project cards in #work and the about text',
    'blog': 'posts/first-post.html (your first post), then the post list and About box in index.html',
    'link_in_bio': 'the bio line and every https://example.com/ link in index.html',
    'docs': 'the Introduction (index.html), then each page; keep the sidebar the same on every page',
}


def new_site(arguments):
    extra = set(arguments) - ALLOWED
    if extra:
        raise SiteError(f'Unexpected argument(s): {", ".join(sorted(map(str, extra)))}. Allowed: {", ".join(sorted(ALLOWED))}.')
    template = _enum(arguments.get('template'), 'template', TEMPLATES)
    title = _clean_text(arguments.get('site_title'), 'site_title', 60, required=True)
    tagline = _clean_text(arguments.get('tagline'), 'tagline', 140)
    theme = _enum(arguments.get('theme'), 'theme', THEMES, default='dark')
    color = arguments.get('color')
    if color is None or (isinstance(color, str) and not color.strip()):
        color = DEFAULT_COLOR
    if not isinstance(color, str) or len(color) > 60:
        raise SiteError('color must be a short colour string like "#2ff3d0", "rgb(47, 243, 208)" or "coral".')
    try:
        palette.parse_color(color)
    except palette.PaletteError as error:
        raise SiteError(str(error)) from None
    sections = _sections(arguments.get('sections'))
    name = _free_name(arguments.get('project_name'), title)
    files = generate_files(template, title, tagline, color.strip(), theme, sections)
    try:
        root = projects.write_files(name, files)
    except projects.ProjectError as error:
        raise SiteError(str(error)) from None

    content = []
    shot = None
    try:
        import preview_capture
        result = preview_capture.capture(root, 'index.html')
        shot = next((img for img in result.get('images', []) if 'desktop' in img.get('name', '')),
                    (result.get('images') or [None])[0])
    except Exception:  # browser missing, timeout, sandbox mismatch: the site is still created
        shot = None
    lines = [
        f'Created Build project "{name}" from the {template} template ({theme} theme, brand colour {color.strip()}).',
        'Files: ' + ', '.join(sorted(files)) + '.',
        f'Edit first: {FIRST_EDIT[template]}. PROJECT_BRIEF.md lists the design tokens and rules.',
        'Sample text is marked as placeholder copy; replace it with real content.',
        f'Open it in Build → {name} → Preview.',
    ]
    if shot is None:
        lines.append('(Screenshot unavailable; the site was still created.)')
    content.append({'type': 'text', 'text': '\n'.join(lines)})
    if shot and shot.get('data'):
        content.append({'type': 'image', 'mimeType': shot.get('mime') or shot.get('mimeType') or 'image/jpeg', 'data': shot['data']})
    return {'content': content}


def call(tool, arguments):
    if tool != 'new_site':
        return _error(f'Unknown tool "{tool}".')
    if not isinstance(arguments, dict):
        return _error('Pass an object like {"template": "landing", "site_title": "Nova"}.')
    try:
        return new_site(arguments)
    except SiteError as error:
        return _error(error)
