"""User-customizable branding for the locally rendered document PDFs
(estimate, change order, purchase order — invoices attach QBO's PDF and are
not covered).

Two layers, all stored as optional Configuration rows:

- Shared letterhead: an uploaded logo (`pdf_logo`, a base64 data URI so it
  lives in the DB and survives redeploys), its position, and the company
  name / address / phone / email.
- Per-document text: four fixed slots per document kind
  (`<kind>_pdf_text_<slot>`) with `{placeholder}` substitution.

The company fields and the text slots are rich text (`RICH_TEXT_KEYS`): the
small HTML subset of `apps.core.rich_text`, sanitized on save and again on
render.

The settings page previews unsaved edits: `drafts` stand in for the stored
values of the keys `preview_draft_keys` allows, and `pdf_page_images` turns
the rendered PDF into page images for the preview windows.

The templates own the layout; this module only supplies the `branding`
context they render. See docs/designs/architecture-and-conventions.md.
"""
import base64
import io
import threading

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from .rich_text import is_blank, render_rich_text, sanitize_rich_text

DOCUMENT_KINDS = ('estimate', 'change_order', 'po')
# The settings page also previews the shared letterhead on its own.
LETTERHEAD = 'letterhead'
TEXT_SLOTS = ('below_header', 'above_lines', 'below_totals', 'page_footer')

LOGO_KEY = 'pdf_logo'
LOGO_POSITION_KEY = 'pdf_logo_position'
LOGO_POSITIONS = ('left', 'center', 'right')
DEFAULT_LOGO_POSITION = 'left'
COMPANY_KEYS = (
    'pdf_company_name', 'pdf_company_address',
    'pdf_company_phone', 'pdf_company_email',
)

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


def text_key(kind, slot):
    """Configuration key for one document kind's text slot."""
    return f'{kind}_pdf_text_{slot}'


# Keys holding rich text — sanitized by the settings PATCH before storing.
RICH_TEXT_KEYS = frozenset(
    (*COMPANY_KEYS,
     *(text_key(kind, slot) for kind in DOCUMENT_KINDS for slot in TEXT_SLOTS)))


def preview_draft_keys(kind):
    """Keys a settings preview may override with unsaved values: the
    letterhead text (not the logo, which is uploaded deliberately) and, for
    a document, its own text slots."""
    if kind == LETTERHEAD:
        return (LOGO_POSITION_KEY, *COMPANY_KEYS)
    return (LOGO_POSITION_KEY, *COMPANY_KEYS,
            *(text_key(kind, slot) for slot in TEXT_SLOTS))


def pdf_branding_context(kind, values, drafts=None):
    """The `branding` template context for one document kind. `values` are
    the placeholder substitutions for that document's text slots. `drafts`
    (settings preview only) are unsaved values that replace the stored ones
    for the keys `preview_draft_keys` allows; they are never written."""
    from .models import Configuration

    keys = [LOGO_KEY, LOGO_POSITION_KEY, *COMPANY_KEYS]
    keys += [text_key(kind, slot) for slot in TEXT_SLOTS]
    stored = dict(
        Configuration.objects.filter(key__in=keys).values_list('key', 'value'))
    if drafts:
        allowed = preview_draft_keys(kind)
        stored.update({k: v for k, v in drafts.items() if k in allowed})

    position = stored.get(LOGO_POSITION_KEY, DEFAULT_LOGO_POSITION)
    if position not in LOGO_POSITIONS:
        position = DEFAULT_LOGO_POSITION

    def company(key):
        html = sanitize_rich_text(stored.get(key, ''))
        return '' if is_blank(html) else mark_safe(html)

    branding = {
        'logo': stored.get(LOGO_KEY, ''),
        'logo_position': position,
        'company_name': company('pdf_company_name'),
        'company_address': company('pdf_company_address'),
        'company_phone': company('pdf_company_phone'),
        'company_email': company('pdf_company_email'),
        'text': {
            slot: mark_safe(render_rich_text(stored.get(text_key(kind, slot), ''), values))
            for slot in TEXT_SLOTS if slot != 'page_footer'
        },
        'page_footer': mark_safe(render_rich_text(
            stored.get(text_key(kind, 'page_footer'), ''), values,
            safe_values=_PAGE_TOKENS)),
    }
    branding['has_letterhead'] = bool(
        branding['logo'] or branding['company_name'] or branding['company_address']
        or branding['company_phone'] or branding['company_email'])
    return {'branding': branding}


def render_document_html(template_name, kind, context, values, drafts=None):
    """Render a document PDF template with the branding context merged in."""
    return render_to_string(
        template_name, {**context, **pdf_branding_context(kind, values, drafts)})


def preview_letterhead_html(drafts=None):
    """The shared letterhead alone on a page, as an HTML string, branded with
    the saved settings overlaid by `drafts` — for the settings preview."""
    return render_document_html('pdf/letterhead_preview.html', LETTERHEAD, {}, {}, drafts)


def pdf_page_images(pdf_bytes, scale=PREVIEW_SCALE, crop=False):
    """Each page of a PDF as a PNG data URI, for the settings preview.

    `crop` (the letterhead preview): only the first page, cut just below its
    lowest printed content at full page width — so the logo position still
    reads — or no image at all when the page is blank."""
    import pypdfium2 as pdfium

    images = []
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            for index, page in enumerate(pdf):
                try:
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                if crop:
                    image = _crop_below_content(image, margin=int(24 * scale))
                    if image is None:
                        break
                buf = io.BytesIO()
                image.save(buf, format='PNG')
                images.append(f'data:image/png;base64,'
                              f'{base64.b64encode(buf.getvalue()).decode("ascii")}')
                if crop and index == 0:
                    break
        finally:
            pdf.close()
    return images


def _crop_below_content(image, margin):
    """The top of `image` down to just below its lowest non-white pixel, or
    None when the image is blank."""
    ink = image.convert('L').point(lambda p: 255 if p < 250 else 0).getbbox()
    if ink is None:
        return None
    return image.crop((0, 0, image.width, min(image.height, ink[3] + margin)))


class PdfBrandingService:
    """Logo storage for the document PDFs."""

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
        from PIL import Image
        from .services import ConfigurationService

        if upload is None:
            raise ValidationError({'logo': ['Choose an image file to upload.']})
        if upload.size > MAX_LOGO_BYTES:
            raise ValidationError(
                {'logo': ['The logo must be 1 MB or smaller.']})
        data = upload.read()
        try:
            image = Image.open(io.BytesIO(data))
            image_format = image.format
            image.verify()
        except Exception:  # noqa: BLE001 — Pillow raises many types for bad input
            raise ValidationError(
                {'logo': ['That file is not a readable image.']})
        mime = LOGO_FORMATS.get(image_format)
        if mime is None:
            raise ValidationError(
                {'logo': ['The logo must be a PNG or JPEG image.']})

        uri = f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
        ConfigurationService.set(LOGO_KEY, uri)
        return uri

    @staticmethod
    def clear_logo():
        from .models import Configuration
        for config in Configuration.objects.filter(key=LOGO_KEY):
            config.delete()
