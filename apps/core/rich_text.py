"""The rich-text format of the document-PDF branding fields.

The settings editor (Tiptap) produces a tiny HTML subset — paragraphs, line
breaks, bulleted / numbered lists, bold / italic / underline, and four
text-size steps carried as span classes. Stored values are rendered into WeasyPrint documents, and WeasyPrint
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

_INLINE = {'strong': 'strong', 'b': 'strong', 'em': 'em', 'i': 'em', 'u': 'u'}
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
            self.out.append('<p>')
            self.stack.append(('p', True))
        elif tag in _INLINE:
            name = _INLINE[tag]
            self.out.append(f'<{name}>')
            self.stack.append((name, True))
        elif tag == 'span':
            cls = (dict(attrs).get('class') or '').strip()
            keep = cls in SIZE_CLASSES
            if keep:
                self.out.append(f'<span class="{cls}">')
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
    """Reduce any HTML to the allowlist: <p>, <br>, <ul>, <ol start="n">,
    <li>, <strong>, <em>, <u>, and <span class="size-…">. Other attributes
    are dropped, b/i become strong/em,
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
