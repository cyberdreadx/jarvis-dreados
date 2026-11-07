"""Shared look for DreadOS Tools images: dark panel, cyan/violet accents, readable text.

Use these so every built-in tool's output looks like part of DreadOS.
"""
import base64
from html import escape as _escape

COLORS = {
    'bg': '#0b1020',        # page background
    'panel': '#111a33',     # card / plot area
    'grid': '#26304f',      # gridlines, faint borders
    'line': '#5d6a8f',      # axes, frets, connectors
    'text': '#ffffff',      # titles, primary labels
    'sub': '#8f9bc4',       # secondary labels, captions
    'accent': '#2ff3d0',    # primary highlight (teal)
    'accent_text': '#06121a',
    'warn': '#ff6b8a',
}
# Ordered series colours for charts and categories (high contrast on the dark background).
SERIES = ['#2ff3d0', '#8a7dff', '#ff9a3c', '#ff3bd4', '#5fe8ff', '#ffd23f', '#7cff6b', '#ff6b8a']
FONT = 'Segoe UI,Arial,sans-serif'
MONO = 'Consolas,monospace'


def esc(text):
    """Escape any user-supplied text placed in SVG."""
    return _escape(str(text), quote=True)


def svg_document(width, height, body, title=''):
    """Wrap SVG body elements in a full document with the DreadOS background and optional title."""
    top = []
    if title:
        top.append(f'<text x="18" y="32" font-size="20" font-weight="700" fill="{COLORS["text"]}">{esc(title)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" '
            f'viewBox="0 0 {int(width)} {int(height)}" font-family="{FONT}">'
            f'<rect width="{int(width)}" height="{int(height)}" fill="{COLORS["bg"]}"/>' + ''.join(top) + ''.join(body) + '</svg>')


def image_result(summary, svg):
    """Standard MCP result: a short text summary plus the SVG image."""
    return {'content': [{'type': 'text', 'text': summary},
                        {'type': 'image', 'mimeType': 'image/svg+xml', 'data': base64.b64encode(svg.encode()).decode('ascii')}]}


def text_result(text):
    return {'content': [{'type': 'text', 'text': text}]}
