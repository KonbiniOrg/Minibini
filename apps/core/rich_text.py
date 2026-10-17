"""The rich-text format of the document-PDF branding fields.

The settings editor (Tiptap) produces a small HTML subset — paragraphs (with
an optional text alignment), line breaks, bulleted / numbered lists, bold /
italic / underline / strikethrough, sub- / superscript, four text-size steps
carried as span classes, and text colour / highlight / font family carried
as span styles. No links, no images, no markup of the user's own. Stored values are rendered into WeasyPrint documents, and WeasyPrint
fetches whatever an element references (`<img src="file:///…">`, stylesheet
URLs), so arbitrary markup would be a file-read / SSRF surface. Every value
therefore passes through `sanitize_rich_text`, an allowlist, both when saved
and again when rendered: the browser's HTML is never trusted.
"""
import re
from html import escape, unescape
from html.parser import HTMLParser

# Size steps, as span classes the PDF stylesheet maps to sizes. Normal is no
# span at all.
SIZE_CLASSES = ('size-small', 'size-large', 'size-xlarge')

_INLINE = {'strong': 'strong', 'b': 'strong', 'em': 'em', 'i': 'em', 'u': 'u',
           's': 's', 'strike': 's', 'del': 's', 'sub': 'sub', 'sup': 'sup'}
# Styles are rebuilt from an allowlist — never passed through: a span may
# carry colour, highlight and one of a few generic font families; a
# paragraph, its alignment. Values are matched whole, so nothing like url()
# or expression() survives.
FONT_FAMILIES = ('sans-serif', 'serif', 'monospace')
ALIGNMENTS = ('left', 'center', 'right', 'justify')
_HEX = re.compile(r'#(?:[0-9a-f]{3}|[0-9a-f]{6})')
_RGB = re.compile(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)')
# A named colour (as pasted text often carries): letters only, so it can't
# carry a function or a URL; a name WeasyPrint doesn't know is ignored.
_NAMED = re.compile(r'[a-z]{3,20}')
_LISTS = {'ul', 'ol'}
# Block-level tags (from pasted documents) become paragraph boundaries. An
# <li> outside any list is one too.
_BLOCK = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote',
          'pre', 'tr', 'section', 'article', 'header', 'footer'}
# A paragraph never closes past the list item / list it sits in, and an item
# never past its own list.
_PARAGRAPH_SCOPE = {'li', *_LISTS}
_ITEM_SCOPE = _LISTS
_START = re.compile(r'[0-9]{1,4}')
# Dropped together with everything inside them.
_DROP = {'script', 'style', 'head', 'title', 'iframe', 'object', 'embed',
         'svg', 'math', 'template', 'noscript', 'textarea', 'select', 'xml'}

_PLACEHOLDER = re.compile(r'\{(\w+)\}')
_TAG = re.compile(r'<[^>]*>')


def _declarations(style):
    """(property, value) pairs from a style attribute, lowercased; the last
    of a repeated property wins."""
    out = {}
    for part in (style or '').split(';'):
        prop, sep, value = part.partition(':')
        if sep:
            out[prop.strip().lower()] = value.strip().lower()
    return out


def _colour(value):
    if _HEX.fullmatch(value) or _NAMED.fullmatch(value):
        return value
    match = _RGB.fullmatch(value)
    if match and all(int(part) <= 255 for part in match.groups()):
        return 'rgb({}, {}, {})'.format(*(int(part) for part in match.groups()))
    return None


def _span_style(style):
    parts = []
    for prop, value in _declarations(style).items():
        if prop in ('color', 'background-color'):
            colour = _colour(value)
            if colour:
                parts.append(f'{prop}: {colour}')
        elif prop == 'font-family':
            family = value.strip('\'"')
            if family in FONT_FAMILIES:
                parts.append(f'font-family: {family}')
    return '; '.join(parts)


def _paragraph_open(attrs):
    align = _declarations(dict(attrs).get('style')).get('text-align')
    return f'<p style="text-align: {align}">' if align in ALIGNMENTS else '<p>'


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        # Open elements as (tag, emitted). Spans are tracked even when
        # unwrapped so their end tag can't close an outer, kept span.
        self.stack = []
        self.drop_depth = 0

    def _close_to(self, tag, scope=()):
        """Close open elements down to and including the innermost `tag`,
        unless a `scope` element is open inside it."""
        for t, _ in reversed(self.stack):
            if t == tag:
                break
            if t in scope:
                return
        else:
            return
        while self.stack:
            t, emitted = self.stack.pop()
            if emitted:
                self.out.append(f'</{t}>')
            if t == tag:
                return

    def handle_starttag(self, tag, attrs):
        if self.drop_depth:
            if tag in _DROP:
                self.drop_depth += 1
            return
        if tag in _DROP:
            self.drop_depth = 1
        elif tag == 'br':
            self.out.append('<br>')
        elif tag in _LISTS:
            self._close_to('p', _PARAGRAPH_SCOPE)
            start = (dict(attrs).get('start') or '').strip()
            if tag == 'ol' and _START.fullmatch(start) and int(start) > 1:
                self.out.append(f'<ol start="{int(start)}">')
            else:
                self.out.append(f'<{tag}>')
            self.stack.append((tag, True))
        elif tag == 'li' and any(t in _LISTS for t, _ in self.stack):
            self._close_to('li', _ITEM_SCOPE)    # an unclosed sibling item
            self.out.append('<li>')
            self.stack.append(('li', True))
        elif tag in _BLOCK or tag == 'li':
            self._close_to('p', _PARAGRAPH_SCOPE)
            self.out.append(_paragraph_open(attrs))
            self.stack.append(('p', True))
        elif tag in _INLINE:
            name = _INLINE[tag]
            self.out.append(f'<{name}>')
            self.stack.append((name, True))
        elif tag == 'span':
            cls = (dict(attrs).get('class') or '').strip()
            cls = cls if cls in SIZE_CLASSES else ''
            style = _span_style(dict(attrs).get('style'))
            keep = bool(cls or style)
            if keep:
                attributes = ''.join((f' class="{cls}"' if cls else '',
                                      f' style="{style}"' if style else ''))
                self.out.append(f'<span{attributes}>')
            self.stack.append(('span', keep))

    def handle_startendtag(self, tag, attrs):
        if tag == 'br' and not self.drop_depth:
            self.out.append('<br>')

    def handle_endtag(self, tag):
        if self.drop_depth:
            if tag in _DROP:
                self.drop_depth -= 1
            return
        if tag in _LISTS:
            self._close_to(tag)
        elif tag == 'li' and any(t == 'li' for t, _ in self.stack):
            self._close_to('li', _ITEM_SCOPE)
        elif tag in _BLOCK or tag == 'li':
            self._close_to('p', _PARAGRAPH_SCOPE)
        elif tag in _INLINE:
            self._close_to(_INLINE[tag])
        elif tag == 'span':
            self._close_to('span')

    def handle_data(self, data):
        if not self.drop_depth:
            self.out.append(escape(data, quote=False))

    def result(self):
        self.close()
        while self.stack:
            t, emitted = self.stack.pop()
            if emitted:
                self.out.append(f'</{t}>')
        return ''.join(self.out)


def sanitize_rich_text(value):
    """Reduce any HTML to the allowlist: <p> (style: text-align only),
    <br>, <ul>, <ol start="n">, <li>, <strong>, <em>, <u>, <s>, <sub>,
    <sup>, and <span> with a size class and / or a style of colour,
    background colour and a generic font family. Other attributes and
    style properties are dropped, b/i become strong/em, strike/del s,
    block tags become paragraphs, unknown tags keep only their text, and
    resource-bearing / script elements are dropped with their content."""
    if not value:
        return ''
    parser = _Sanitizer()
    parser.feed(value)
    return parser.result()


def is_blank(value):
    """True when a rich-text value has no visible text."""
    if not value:
        return True
    return not unescape(_TAG.sub('', value)).replace('\xa0', ' ').strip()


def render_rich_text(value, values, safe_values=None):
    """Sanitize a stored rich-text value and substitute `{name}`
    placeholders: `values` are escaped, `safe_values` (trusted markup, e.g.
    the footer's page-counter spans) are inserted as-is. Unknown placeholders
    — and ones split by formatting — print as typed; nothing raises. A blank
    value renders ''."""
    html = sanitize_rich_text(value)
    if is_blank(html):
        return ''
    safe_values = safe_values or {}

    def substitute(match):
        name = match.group(1)
        if name in safe_values:
            return safe_values[name]
        if name not in values:
            return match.group(0)
        value = values[name]
        return '' if value is None else escape(str(value), quote=False)

    return _PLACEHOLDER.sub(substitute, html)
