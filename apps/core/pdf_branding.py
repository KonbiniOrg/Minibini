"""User-customizable branding for the locally rendered document PDFs
(estimate, change order, purchase order — invoices attach QBO's PDF and are
not covered).

Three parts, all stored as optional Configuration rows:

- Shared company data: an uploaded logo (`pdf_logo`, a base64 data URI so it
  lives in the DB and survives redeploys), the company name / address /
  phone / email, and an image library (`pdf_image_<id>`: JSON of the file's
  name and data URI) that image blocks place. One set for every document.
- Per-document layout: where each document prints what, as rows of columns
  holding blocks (`apps.core.pdf_layout`). The company blocks print the
  shared values; text blocks hold the document's own text.
- Per-document page footer (`<kind>_pdf_text_page_footer`), repeated in the
  bottom page margin — outside the layout, which is the page body.

The company fields, footers and text blocks are rich text: the small HTML
subset of `apps.core.rich_text`, sanitized on save and again on render, with
`{placeholder}` substitution in the document text.

The settings page previews unsaved edits: `drafts` stand in for the stored
values of the keys `preview_draft_keys` allows, a draft `layout` for the
stored layout, and `pdf_page_images` turns the rendered PDF into page images
for the preview window.

The templates own the look of each block; this module only supplies the
`branding` context they render. See docs/designs/architecture-and-conventions.md.
"""
import base64
import io
import json
import re
import threading
import uuid

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from .pdf_layout import (
    BLOCK_TYPES, DOCUMENT_TEMPLATES, get_layout, resolve_layout, validate_layout,
)
from .rich_text import is_blank, render_rich_text, sanitize_rich_text

DOCUMENT_KINDS = ('estimate', 'change_order', 'po')

LOGO_KEY = 'pdf_logo'
COMPANY_KEYS = (
    'pdf_company_name', 'pdf_company_address',
    'pdf_company_phone', 'pdf_company_email',
)

IMAGE_PREFIX = 'pdf_image_'
MAX_IMAGES = 50

MAX_LOGO_BYTES = 1024 * 1024
# Pillow format name -> MIME type. Raster only: SVG can carry script/external
# references and WeasyPrint would fetch them.
LOGO_FORMATS = {'PNG': 'image/png', 'JPEG': 'image/jpeg'}

# Render scale for preview page images: 1.0 is 72 dpi (612 px across a
# Letter page). 1.5 stays sharp in a small window on a high-density screen.
PREVIEW_SCALE = 1.8

# PDFium is not thread-safe — no two threads may call into it at once, even
# on different documents — and the settings page fires a preview per document
# together into a threaded server. Every PDFium call goes through this lock,
# and every PDFium object is closed inside it so the garbage collector never
# finalizes one later on another thread.
_PDFIUM_LOCK = threading.Lock()

# The footer's {page} / {page_count}: spans the stylesheet fills from the CSS
# page counters.
_PAGE_TOKENS = {
    'page': '<span class="page-number"></span>',
    'page_count': '<span class="page-count"></span>',
}


def image_key(image_id):
    """Configuration key for one library image."""
    return f'{IMAGE_PREFIX}{image_id}'


def _image_record(value):
    """A stored library image: {'name', 'src', 'added'}; a row that doesn't
    parse has no picture."""
    try:
        record = json.loads(value)
        return {'name': str(record.get('name', '')), 'src': str(record.get('src', '')),
                'added': str(record.get('added', ''))}
    except (ValueError, AttributeError):
        return {'name': '', 'src': '', 'added': ''}


def footer_key(kind):
    """Configuration key for one document kind's page footer."""
    return f'{kind}_pdf_text_page_footer'


# Keys holding rich text — sanitized by the settings PATCH before storing.
RICH_TEXT_KEYS = frozenset((*COMPANY_KEYS, *(footer_key(kind) for kind in DOCUMENT_KINDS)))


def preview_draft_keys(kind):
    """Keys a settings preview may override with unsaved values: the shared
    company text and the document's own footer (not the logo, which is
    uploaded deliberately)."""
    return (*COMPANY_KEYS, footer_key(kind))


def pdf_branding_context(kind, values, drafts=None, layout=None):
    """The `branding` template context for one document kind. `values` are
    the placeholder substitutions for that document's text. `drafts` and
    `layout` (settings preview only) are unsaved values / an unsaved layout
    that replace the stored ones — `drafts` only for the keys
    `preview_draft_keys` allows; they are never written. A draft layout is
    validated like a saved one (ValidationError when it is not)."""
    from .models import Configuration

    layout = get_layout(kind) if layout is None else validate_layout(kind, layout)
    image_ids = {block['image'] for row in layout['rows'] for cell in row['cells']
                 for block in cell if block['type'] == 'image' and block['image']}
    keys = [LOGO_KEY, *COMPANY_KEYS, footer_key(kind), *(image_key(i) for i in image_ids)]
    stored = dict(
        Configuration.objects.filter(key__in=keys).values_list('key', 'value'))
    if drafts:
        allowed = preview_draft_keys(kind)
        stored.update({k: v for k, v in drafts.items() if k in allowed})

    shared = {'logo': stored.get(LOGO_KEY, ''), 'images': {}}
    for image_id in image_ids:
        if image_key(image_id) in stored:
            shared['images'][image_id] = _image_record(stored[image_key(image_id)])['src']
    for key in COMPANY_KEYS:
        html = sanitize_rich_text(stored.get(key, ''))
        # pdf_company_name -> the company_name block
        shared[key.removeprefix('pdf_')] = '' if is_blank(html) else html

    rows = resolve_layout(kind, layout, values, shared)
    for row in rows:
        for cell in row['cells']:
            for block in cell['blocks']:
                if 'html' in block:
                    block['html'] = mark_safe(block['html'])
    return {'branding': {
        'rows': rows,
        'page_footer': mark_safe(render_rich_text(
            stored.get(footer_key(kind), ''), values, safe_values=_PAGE_TOKENS)),
    }}


def render_document_html(template_name, kind, context, values, drafts=None, layout=None):
    """Render a document PDF template with the branding context merged in."""
    return render_to_string(
        template_name, {**context, **pdf_branding_context(kind, values, drafts, layout)})


_STYLE = re.compile(r'<style>(.*?)</style>', re.S)
# The canvas page element the scoped stylesheet applies under.
CANVAS_SCOPE = '.pdf-page'


def scope_css(css, scope):
    """Our own PDF stylesheet, re-aimed at one element of a web page: each
    rule's selectors are prefixed with `scope` (`body` becomes `scope`
    itself), and at-rules (`@page` and its margin boxes — print-only) are
    dropped. Handles the flat rule lists our templates write, not CSS at
    large."""
    out = []
    i = 0
    while i < len(css):
        brace = css.find('{', i)
        if brace < 0:
            break
        selector = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < len(css) and depth:
            depth += {'{': 1, '}': -1}.get(css[j], 0)
            j += 1
        body = css[brace:j]
        i = j
        if not selector or selector.startswith('@'):
            continue
        selectors = [part.strip() for part in selector.split(',')]
        scoped = ', '.join(scope if part == 'body' else f'{scope} {part}' for part in selectors)
        out.append(f'{scoped} {body}')
    return '\n'.join(out)


def canvas_parts(kind, template_name, context):
    """What the settings page's layout canvas needs to draw `kind` like its
    PDF: each document-owned block (title, details, line items) rendered
    from its partial with `context` (the sample document), and the
    document's stylesheet (its own head rules plus the shared layout and
    block rules) scoped under CANVAS_SCOPE. The canvas draws the shared
    blocks itself from the layout and company values."""
    document_types = [t for t, spec in BLOCK_TYPES.items() if spec.get('source') == 'document']
    blocks = {
        block_type: render_to_string(
            DOCUMENT_TEMPLATES[kind], {**context, 'block': {'type': block_type}})
        # title_number: the title without its heading, which the canvas
        # draws (and edits) itself.
        for block_type in (*document_types, 'title_number')
    }
    page = render_to_string(template_name, {'branding': {'rows': [], 'page_footer': ''}})
    return {'blocks': blocks,
            'stylesheet': scope_css('\n'.join(_STYLE.findall(page)), CANVAS_SCOPE)}


def pdf_page_images(pdf_bytes, scale=PREVIEW_SCALE):
    """Each page of a PDF as a PNG data URI, for the settings preview."""
    import pypdfium2 as pdfium

    images = []
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            for page in pdf:
                try:
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                buf = io.BytesIO()
                image.save(buf, format='PNG')
                images.append(f'data:image/png;base64,'
                              f'{base64.b64encode(buf.getvalue()).decode("ascii")}')
        finally:
            pdf.close()
    return images


def _read_image(upload, field, label):
    """A validated uploaded PNG / JPEG as a data URI, or ValidationError
    keyed by `field`."""
    from PIL import Image

    if upload is None:
        raise ValidationError({field: ['Choose an image file to upload.']})
    if upload.size > MAX_LOGO_BYTES:
        raise ValidationError({field: [f'The {label} must be 1 MB or smaller.']})
    data = upload.read()
    try:
        image = Image.open(io.BytesIO(data))
        image_format = image.format
        image.verify()
    except Exception:  # noqa: BLE001 — Pillow raises many types for bad input
        raise ValidationError({field: ['That file is not a readable image.']})
    mime = LOGO_FORMATS.get(image_format)
    if mime is None:
        raise ValidationError({field: [f'The {label} must be a PNG or JPEG image.']})
    return f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'


class PdfBrandingService:
    """Logo and image-library storage for the document PDFs."""

    @staticmethod
    def get_logo():
        """The stored logo as a data URI, or '' when none is set."""
        from .models import Configuration
        try:
            return Configuration.objects.get(key=LOGO_KEY).value
        except Configuration.DoesNotExist:
            return ''

    @staticmethod
    def set_logo(upload):
        """Validate an uploaded image and store it as a data URI. Returns the
        data URI."""
        from .services import ConfigurationService
        uri = _read_image(upload, 'logo', 'logo')
        ConfigurationService.set(LOGO_KEY, uri)
        return uri

    @staticmethod
    def clear_logo():
        from .models import Configuration
        for config in Configuration.objects.filter(key=LOGO_KEY):
            config.delete()

    @staticmethod
    def list_images():
        """The image library, oldest first: [{'id', 'name', 'src'}]. (The
        Configuration key is the primary key, so upload order comes from
        each record's `added` time.)"""
        from .models import Configuration
        images = []
        for row in Configuration.objects.filter(key__startswith=IMAGE_PREFIX):
            record = _image_record(row.value)
            images.append((record.pop('added'), {'id': row.key.removeprefix(IMAGE_PREFIX), **record}))
        return [image for _added, image in sorted(images, key=lambda pair: pair[0])]

    @staticmethod
    def add_image(upload):
        """Validate an uploaded image and add it to the library. Returns
        {'id', 'name', 'src'}."""
        from .models import Configuration
        from .services import ConfigurationService
        if Configuration.objects.filter(key__startswith=IMAGE_PREFIX).count() >= MAX_IMAGES:
            raise ValidationError(
                {'image': [f'The library holds at most {MAX_IMAGES} images; remove one first.']})
        src = _read_image(upload, 'image', 'image')
        image_id = uuid.uuid4().hex
        name = (getattr(upload, 'name', '') or 'image')[:120]
        ConfigurationService.set(image_key(image_id), json.dumps(
            {'name': name, 'src': src, 'added': timezone.now().isoformat()}))
        return {'id': image_id, 'name': name, 'src': src}

    @staticmethod
    def remove_image(image_id):
        """Drop a library image. Image blocks that placed it print nothing.
        Returns whether it existed."""
        from .models import Configuration
        found = False
        for config in Configuration.objects.filter(key=image_key(image_id)):
            config.delete()
            found = True
        return found
