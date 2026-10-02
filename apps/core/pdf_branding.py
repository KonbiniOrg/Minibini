"""User-customizable branding for the locally rendered document PDFs
(estimate, change order, purchase order — invoices attach QBO's PDF and are
not covered).

Two layers, all stored as optional Configuration rows:

- Shared letterhead: an uploaded logo (`pdf_logo`, a base64 data URI so it
  lives in the DB and survives redeploys), its position, and the company
  name / address / phone / email.
- Per-document text: four fixed slots per document kind
  (`<kind>_pdf_text_<slot>`), plain text with `{placeholder}` substitution.

The templates own the layout; this module only supplies the `branding`
context they render. See docs/designs/architecture-and-conventions.md.
"""
import base64
import io
import re

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import mark_safe

DOCUMENT_KINDS = ('estimate', 'change_order', 'po')
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

_PLACEHOLDER = re.compile(r'\{(\w+)\}')
# Private-use sentinels standing in for the footer's page counters while the
# rest of the text is HTML-escaped.
_PAGE_SENTINEL = ''
_PAGE_COUNT_SENTINEL = ''


def text_key(kind, slot):
    """Configuration key for one document kind's text slot."""
    return f'{kind}_pdf_text_{slot}'


def render_pdf_text(template, values):
    """Substitute `{name}` placeholders in user-authored boilerplate.

    Unknown placeholders render literally and ``None`` renders empty. Unlike
    `render_email_template` this never raises: boilerplate is free text, so a
    stray or unbalanced brace is left as typed rather than blocking a send.
    """
    if not template:
        return ''

    def substitute(match):
        name = match.group(1)
        if name not in values:
            return match.group(0)
        value = values[name]
        return '' if value is None else str(value)

    return _PLACEHOLDER.sub(substitute, template)


def _render_page_footer(template, values):
    """Footer text as safe HTML. `{page}` / `{page_count}` become spans the
    stylesheet fills from the CSS page counters."""
    text = render_pdf_text(template, {
        **values, 'page': _PAGE_SENTINEL, 'page_count': _PAGE_COUNT_SENTINEL,
    })
    html = escape(text)
    html = html.replace(_PAGE_SENTINEL, '<span class="page-number"></span>')
    html = html.replace(_PAGE_COUNT_SENTINEL, '<span class="page-count"></span>')
    return mark_safe(html)


def pdf_branding_context(kind, values):
    """The `branding` template context for one document kind. `values` are
    the placeholder substitutions for that document's text slots."""
    from .models import Configuration

    keys = [LOGO_KEY, LOGO_POSITION_KEY, *COMPANY_KEYS]
    keys += [text_key(kind, slot) for slot in TEXT_SLOTS]
    stored = dict(
        Configuration.objects.filter(key__in=keys).values_list('key', 'value'))

    position = stored.get(LOGO_POSITION_KEY, DEFAULT_LOGO_POSITION)
    if position not in LOGO_POSITIONS:
        position = DEFAULT_LOGO_POSITION

    branding = {
        'logo': stored.get(LOGO_KEY, ''),
        'logo_position': position,
        'company_name': stored.get('pdf_company_name', '').strip(),
        'company_address': stored.get('pdf_company_address', '').strip(),
        'company_phone': stored.get('pdf_company_phone', '').strip(),
        'company_email': stored.get('pdf_company_email', '').strip(),
        'text': {
            slot: render_pdf_text(stored.get(text_key(kind, slot), ''), values).strip()
            for slot in TEXT_SLOTS if slot != 'page_footer'
        },
        'page_footer': _render_page_footer(
            stored.get(text_key(kind, 'page_footer'), '').strip(), values),
    }
    branding['has_letterhead'] = bool(
        branding['logo'] or branding['company_name'] or branding['company_address']
        or branding['company_phone'] or branding['company_email'])
    return {'branding': branding}


def render_document_html(template_name, kind, context, values):
    """Render a document PDF template with the branding context merged in."""
    return render_to_string(
        template_name, {**context, **pdf_branding_context(kind, values)})


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
