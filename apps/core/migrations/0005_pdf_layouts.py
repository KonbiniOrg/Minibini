"""Move the document PDFs from their fixed arrangement to stored layouts.

Before: a shared logo position (`pdf_logo_position`) and three body text
slots per document (`<kind>_pdf_text_below_header` / `_above_lines` /
`_below_totals`) in fixed places. After: one layout per document
(`<kind>_pdf_layout`, apps/core/pdf_layout.py) built to print as before — the
letterhead row as the logo position laid it out, then title, the old
below-header text, details, the above-lines text, line items, the
below-totals text. The position and slot keys are then deleted. With no
branding set at all nothing is stored and the app's default layout applies. Page footers
(`<kind>_pdf_text_page_footer`) are untouched.

Reversing restores the slots and the logo position from each layout as far
as they can say (text before the details → below header, between details
and lines → above lines, after the lines → below totals) and deletes the
layouts.

Self-contained on purpose: keys and layout shapes are spelled out here
rather than imported, so later changes to the app code can't change this
migration.
"""
import json
import re
from html import unescape

from django.db import migrations

KINDS = ('estimate', 'change_order', 'po')
SLOTS = ('below_header', 'above_lines', 'below_totals')
COMPANY = ('company_name', 'company_address', 'company_phone', 'company_email')
POSITION_KEY = 'pdf_logo_position'
LOGO_KEY = 'pdf_logo'
_TAG = re.compile(r'<[^>]*>')


def _slot_key(kind, slot):
    return f'{kind}_pdf_text_{slot}'


def _layout_key(kind):
    return f'{kind}_pdf_layout'


def _blank(html):
    return not unescape(_TAG.sub('', html or '')).replace('\xa0', ' ').strip()


def _full(*blocks):
    return {'columns': 'full', 'cells': [list(blocks)]}


def _company(align):
    return [{'type': block, 'align': align} for block in COMPANY]


def _letterhead(stored):
    position = stored.get(POSITION_KEY, 'left')
    if not stored.get(LOGO_KEY):
        # The old template left-aligned the company block when no logo
        # printed. A logo uploaded later prints above it.
        return _full({'type': 'logo', 'align': 'left'}, *_company('left'))
    if position == 'center':
        return _full({'type': 'logo', 'align': 'center'}, *_company('center'))
    if position == 'right':
        return {'columns': '1/2-1/2', 'cells': [
            _company('left'), [{'type': 'logo', 'align': 'right'}]]}
    return {'columns': '1/2-1/2', 'cells': [
        [{'type': 'logo', 'align': 'left'}], _company('right')]}


def build_layout(kind, stored):
    """The layout that prints `kind` as the old fixed template did, from the
    stored {key: value} settings."""
    def text_row(slot):
        html = stored.get(_slot_key(kind, slot), '')
        return [] if _blank(html) else [_full({'type': 'text', 'align': 'left', 'html': html})]

    rows = [
        _letterhead(stored),
        _full({'type': 'title', 'align': 'left'}),
        *text_row('below_header'),
        _full({'type': 'details', 'align': 'left'}),
        *text_row('above_lines'),
        _full({'type': 'line_items'}),
        *text_row('below_totals'),
    ]
    return {'version': 1, 'rows': rows}


def slots_from_layout(kind, layout):
    """Reverse: the old body slots, from where each layout's text blocks sit
    relative to the details and line items."""
    slot = 'below_header'
    texts = {}
    for row in layout.get('rows', []):
        for cell in row.get('cells', []):
            for block in cell:
                if block.get('type') == 'details':
                    slot = 'above_lines'
                elif block.get('type') == 'line_items':
                    slot = 'below_totals'
                elif block.get('type') == 'text' and not _blank(block.get('html')):
                    texts.setdefault(slot, []).append(block['html'])
    return {_slot_key(kind, s): ''.join(parts) for s, parts in texts.items()}


def logo_position_from_layout(layout):
    """Reverse: the old logo position, from the first row with a logo."""
    for row in layout.get('rows', []):
        cells = row.get('cells', [])
        for index, cell in enumerate(cells):
            for block in cell:
                if block.get('type') != 'logo':
                    continue
                if len(cells) == 1:
                    return 'center' if block.get('align') == 'center' else 'left'
                return 'right' if index == len(cells) - 1 else 'left'
    return 'left'


def is_branded(stored):
    """Whether anything the old letterhead or slots printed is set. With
    nothing set, no layout is stored and the app's default layout applies."""
    return bool(stored.get(LOGO_KEY)) or any(
        not _blank(value) for key, value in stored.items()
        if key not in (LOGO_KEY, POSITION_KEY))


def forwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    old_keys = [POSITION_KEY, *(_slot_key(k, s) for k in KINDS for s in SLOTS)]
    stored = dict(Configuration.objects.filter(
        key__in=[LOGO_KEY, *(f'pdf_{c}' for c in COMPANY), *old_keys],
    ).values_list('key', 'value'))
    if is_branded(stored):
        for kind in KINDS:
            Configuration.objects.update_or_create(
                key=_layout_key(kind),
                defaults={'value': json.dumps(build_layout(kind, stored))})
    for config in Configuration.objects.filter(key__in=old_keys):
        config.delete()


def backwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    position = None
    for kind in KINDS:
        try:
            config = Configuration.objects.get(key=_layout_key(kind))
        except Configuration.DoesNotExist:
            continue
        try:
            layout = json.loads(config.value)
        except ValueError:
            layout = {}
        for key, value in slots_from_layout(kind, layout).items():
            Configuration.objects.update_or_create(key=key, defaults={'value': value})
        if position is None:
            position = logo_position_from_layout(layout)
        config.delete()
    if position is not None:
        Configuration.objects.update_or_create(
            key=POSITION_KEY, defaults={'value': position})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_pdf_branding_rich_text'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
