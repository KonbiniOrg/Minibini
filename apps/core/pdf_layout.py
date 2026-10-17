"""User-arranged layouts for the locally rendered document PDFs (estimate,
change order, purchase order).

A layout is rows of columns holding blocks:

    {"version": 1, "rows": [
        {"columns": "1/2-1/2", "cells": [[block, ...], [block, ...]]}, ...]}

Each document kind has its own, fully independent layout, stored as canonical
JSON in Configuration `<kind>_pdf_layout`; with no (readable) row stored the
kind's `default_layout` applies. The company data the shared blocks print
(logo, name, address, phone, email) is not part of a layout — it stays the
single shared set of `pdf_branding` keys, so every layout places the same
values.

Users arrange blocks; they never write markup. Text blocks hold the rich-text
subset of `apps.core.rich_text`, sanitized when a layout is validated and
again when it is rendered.

Divider lines are not blocks — they sit on borders and take no space of
their own: `line_below: true` on a block (a line under it, across its
column), `line_below: true` on a row (a line under the row, across the
page), and `column_lines` on a column row (one boolean per boundary
between neighbouring columns: a vertical line down the middle of that
gap, the row's full height). Each is stored only when set.

The line-item block must appear exactly once, alone in a full-width row: it is
the one part that grows across pages, and WeasyPrint only splits a table
across pages reliably in the normal flow — not inside a multi-column row.
"""
import json
import re

from django.core.exceptions import ValidationError

from .rich_text import is_blank, render_rich_text, sanitize_rich_text

LAYOUT_VERSION = 1
MAX_ROWS = 40
MAX_BLOCKS_PER_CELL = 20
MAX_TEXT_LENGTH = 20000

# Preset key -> column widths in percent.
COLUMN_PRESETS = {
    'full': [100],
    '1/2-1/2': [50, 50],
    '1/3-2/3': [33.333, 66.667],
    '2/3-1/3': [66.667, 33.333],
    '1/3-1/3-1/3': [33.333, 33.333, 33.334],
}

ALIGNMENTS = ('left', 'center', 'right')
SIDES = ('left', 'right')
SPACER_SIZES = ('small', 'medium', 'large')
# A spacer is a vertical gap (a block) or a horizontal indent of its whole
# column. (Divider lines are not blocks: they sit on borders — see
# LINES below.)
ORIENTATIONS = {'spacer': ('vertical', 'horizontal')}
# Column rows: the space between columns (px). Rows without a `gap` key are
# medium, so only small / large are stored.
COLUMN_GAPS = {'small': 8, 'medium': 16, 'large': 32}
INDENTS = {'small': 12, 'medium': 24, 'large': 48}
# The title block's heading when none is typed.
TITLE_DEFAULTS = {'estimate': 'Estimate', 'change_order': 'Change Order', 'po': 'Purchase Order'}
MAX_HEADING_LENGTH = 80
# An image block's picture: an id in the shared image library
# (apps/core/pdf_branding.py), or '' before one is chosen.
_IMAGE_ID = re.compile(r'[0-9a-f]{32}')
RULE = '1px solid #333'

# type -> label, settings it takes (each with its default), whether it may
# appear at most once, whether it must appear, and where it renders from:
# 'shared' blocks from pdf/_blocks.html, 'document' blocks from the kind's own
# partial (DOCUMENT_TEMPLATES).
BLOCK_TYPES = {
    'logo': {'label': 'Logo', 'settings': {'align': 'left'}},
    'company_name': {'label': 'Company name', 'settings': {'align': 'left'}},
    'company_address': {'label': 'Company address', 'settings': {'align': 'left'}},
    'company_phone': {'label': 'Company phone', 'settings': {'align': 'left'}},
    'company_email': {'label': 'Company email', 'settings': {'align': 'left'}},
    'text': {'label': 'Text', 'settings': {'align': 'left', 'html': ''}},
    'image': {'label': 'Image',
              'settings': {'image': '', 'align': 'left', 'size': 'medium'}},
    'spacer': {'label': 'Spacer',
               'settings': {'orientation': 'vertical', 'size': 'medium', 'side': 'left'}},
    'title': {'label': 'Title', 'settings': {'align': 'left', 'heading': ''},
              'single': True, 'source': 'document'},
    'details': {'label': 'Details', 'settings': {'align': 'left'},
                'single': True, 'source': 'document'},
    'line_items': {'label': 'Line items', 'settings': {},
                   'single': True, 'required': True, 'source': 'document'},
}
COMPANY_BLOCKS = ('company_name', 'company_address', 'company_phone', 'company_email')

SHARED_TEMPLATE = 'pdf/_blocks.html'
DOCUMENT_TEMPLATES = {
    'estimate': 'estimates/_estimate_blocks.html',
    'change_order': 'estimates/_change_order_blocks.html',
    'po': 'purchasing/_po_blocks.html',
}


def layout_key(kind):
    """Configuration key for one document kind's layout."""
    return f'{kind}_pdf_layout'


def default_layout(kind):
    """The layout a document kind prints with until one is saved: the
    letterhead (logo left, company details right), title, details, lines."""
    return {
        'version': LAYOUT_VERSION,
        'rows': [
            {'columns': '1/2-1/2', 'cells': [
                [{'type': 'logo', 'align': 'left'}],
                [{'type': block, 'align': 'right'} for block in COMPANY_BLOCKS],
            ]},
            {'columns': 'full', 'cells': [[{'type': 'title', 'align': 'left'}]]},
            {'columns': 'full', 'cells': [[{'type': 'details', 'align': 'left'}]]},
            {'columns': 'full', 'cells': [[{'type': 'line_items'}]]},
        ],
    }


def block_catalog(kind):
    """What the layout editor may place for `kind`, and the column presets."""
    return {
        'blocks': [
            {'type': block_type, 'label': spec['label'],
             'settings': dict(spec['settings']),
             'single': spec.get('single', False),
             'required': spec.get('required', False)}
            for block_type, spec in BLOCK_TYPES.items()
        ],
        'presets': [{'key': key, 'widths': widths}
                    for key, widths in COLUMN_PRESETS.items()],
        'default_heading': TITLE_DEFAULTS[kind],
    }


def _validate_block(block, where):
    """One block normalized to its type plus every setting it takes, or a
    list of error messages."""
    if not isinstance(block, dict):
        return None, [f'{where}: each block must be an object.']
    block_type = block.get('type')
    spec = BLOCK_TYPES.get(block_type)
    if spec is None:
        return None, [f'{where}: unknown block type "{block_type}".']
    label = spec['label']
    errors = []
    out = {'type': block_type}
    for key in block:
        if key not in ('type', 'line_below') and key not in spec['settings']:
            errors.append(f'{where}: {label} has no setting "{key}".')
    line_below = block.get('line_below', False)
    if not isinstance(line_below, bool):
        errors.append(f'{where}: line_below must be true or false.')
    for key, default in spec['settings'].items():
        value = block.get(key, default)
        if key == 'align' and value not in ALIGNMENTS:
            errors.append(f'{where}: align must be one of {", ".join(ALIGNMENTS)}.')
        elif key == 'size' and value not in SPACER_SIZES:
            errors.append(f'{where}: size must be one of {", ".join(SPACER_SIZES)}.')
        elif key == 'heading':
            if not isinstance(value, str):
                errors.append(f'{where}: the heading must be text.')
                continue
            value = value.strip()
            if len(value) > MAX_HEADING_LENGTH:
                errors.append(
                    f'{where}: the heading can be at most {MAX_HEADING_LENGTH} characters.')
                continue
            if not value:
                continue   # blank: the document's own name prints; not stored
        elif key == 'image' and not (value == '' or (
                isinstance(value, str) and _IMAGE_ID.fullmatch(value))):
            errors.append(f'{where}: unknown image.')
        elif key == 'side' and value not in SIDES:
            errors.append(f'{where}: side must be one of {", ".join(SIDES)}.')
        elif key == 'orientation' and value not in ORIENTATIONS[block_type]:
            errors.append(
                f'{where}: orientation must be one of {", ".join(ORIENTATIONS[block_type])}.')
        elif key == 'html':
            if not isinstance(value, str):
                errors.append(f'{where}: the text must be text.')
                continue
            if len(value) > MAX_TEXT_LENGTH:
                errors.append(f'{where}: the text is too long.')
                continue
            value = sanitize_rich_text(value)
        out[key] = value
    if line_below is True:
        out['line_below'] = True
    return out, errors


def validate_layout(kind, layout):
    """`layout` normalized (every block carries exactly its settings; text
    sanitized), or ValidationError({'layout': [messages]}). Never mutates
    its input."""
    def fail(messages):
        raise ValidationError({'layout': messages})

    if not isinstance(layout, dict):
        fail(['The layout must be an object.'])
    if layout.get('version') != LAYOUT_VERSION:
        fail([f'The layout version must be {LAYOUT_VERSION}.'])
    rows = layout.get('rows')
    if not isinstance(rows, list) or not rows:
        fail(['The layout needs at least one row.'])
    if len(rows) > MAX_ROWS:
        fail([f'A layout can have at most {MAX_ROWS} rows.'])

    errors = []
    out_rows = []
    counts = {}
    for r, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f'Row {r} must be an object.')
            continue
        columns = row.get('columns')
        if columns not in COLUMN_PRESETS:
            errors.append(f'Row {r} has an unknown column layout "{columns}".')
            continue
        cells = row.get('cells')
        expected = len(COLUMN_PRESETS[columns])
        if not isinstance(cells, list) or len(cells) != expected:
            errors.append(f'Row {r} needs {expected} columns.')
            continue
        out_cells = []
        for c, cell in enumerate(cells, start=1):
            if not isinstance(cell, list):
                errors.append(f'Row {r}, column {c} must be a list of blocks.')
                continue
            if len(cell) > MAX_BLOCKS_PER_CELL:
                errors.append(
                    f'Row {r}, column {c} can hold at most {MAX_BLOCKS_PER_CELL} blocks.')
                continue
            out_cell = []
            for b, block in enumerate(cell, start=1):
                normalized, block_errors = _validate_block(
                    block, f'Row {r}, column {c}, block {b}')
                errors.extend(block_errors)
                if normalized and not block_errors:
                    out_cell.append(normalized)
                    counts[normalized['type']] = counts.get(normalized['type'], 0) + 1
            out_cells.append(out_cell)
        types = [block.get('type') for cell in cells if isinstance(cell, list)
                 for block in cell if isinstance(block, dict)]
        if 'line_items' in types:
            if columns != 'full':
                errors.append(f'Row {r}: line items need a full-width row.')
            elif len(types) > 1:
                errors.append(f'Row {r}: line items must be in a row by itself.')
        out_row = {'columns': columns, 'cells': out_cells}
        gap = row.get('gap', 'medium')
        if gap not in COLUMN_GAPS:
            errors.append(f'Row {r}: gap must be one of {", ".join(COLUMN_GAPS)}.')
        elif columns != 'full' and gap != 'medium':
            out_row['gap'] = gap
        line_below = row.get('line_below', False)
        if not isinstance(line_below, bool):
            errors.append(f'Row {r}: line_below must be true or false.')
        elif line_below:
            out_row['line_below'] = True
        column_lines = row.get('column_lines')
        if column_lines is not None and columns != 'full':
            if (not isinstance(column_lines, list) or len(column_lines) != expected - 1
                    or not all(isinstance(x, bool) for x in column_lines)):
                errors.append(f'Row {r}: column_lines must be {expected - 1} true/false values.')
            elif any(column_lines):
                out_row['column_lines'] = column_lines
        out_rows.append(out_row)

    for block_type, spec in BLOCK_TYPES.items():
        count = counts.get(block_type, 0)
        if spec.get('required') and count != 1:
            errors.append(f'The layout must contain the line items exactly once.'
                          if block_type == 'line_items'
                          else f'The layout must contain {spec["label"]} exactly once.')
        elif spec.get('single') and count > 1:
            errors.append(f'{spec["label"]} can appear only once.')
    if errors:
        fail(errors)
    return {'version': LAYOUT_VERSION, 'rows': out_rows}


def get_layout(kind):
    """The stored layout for `kind`, or its default when none is stored or
    the stored one no longer validates."""
    from .models import Configuration
    try:
        raw = Configuration.objects.get(key=layout_key(kind)).value
        return validate_layout(kind, json.loads(raw))
    except (Configuration.DoesNotExist, ValueError, ValidationError):
        return default_layout(kind)


def save_layout(kind, layout):
    """Validate and store `kind`'s layout. Returns the normalized layout."""
    from .services import ConfigurationService
    normalized = validate_layout(kind, layout)
    ConfigurationService.set(layout_key(kind), json.dumps(normalized))
    return normalized


def resolve_layout(kind, layout, values, shared):
    """A validated layout as render-ready rows for pdf/_layout.html.

    `values` are the placeholder substitutions for text blocks; `shared` is
    the shared company data (`logo` data URI, the sanitized `company_*`
    HTML, and `images`: {library id: data URI} for the layout's image
    blocks). Each cell comes back as `{'blocks': [...], 'style': css}`:
    horizontal spacers (indents) are not blocks in print — with the row's
    gap and column lines they become the cell's padding / border
    (`_cell_style`). Blocks with nothing
    to print are dropped, then rows left with no blocks at all; a kept row
    keeps its empty cells so its columns hold their place. Full-width rows
    come back with `flow` set: they render as plain blocks that split
    across pages like any text (the line items always do); multi-column
    rows render as a table kept on one page."""
    rows = []
    for row in layout['rows']:
        gap = COLUMN_GAPS[row.get('gap', 'medium')]
        flow = row['columns'] == 'full'
        lines = row.get('column_lines') or []

        def has_line(boundary, lines=lines):
            return 0 <= boundary < len(lines) and lines[boundary]

        cells = []
        for c, cell in enumerate(row['cells']):
            out = []
            for block in cell:
                if _is_decoration(block):
                    continue
                resolved = _resolve_block(kind, block, values, shared)
                if resolved is not None:
                    out.append(resolved)
            cells.append({'blocks': out, 'style': _cell_style(
                cell, 0 if flow else c, gap,
                line_left=has_line(c - 1), line_right=has_line(c))})
        if not any(cell['blocks'] for cell in cells):
            continue
        rows.append({
            'columns': row['columns'],
            'widths': COLUMN_PRESETS[row['columns']],
            'flow': flow,
            'line_below': row.get('line_below', False),
            'cells': cells,
        })
    return rows


def _is_decoration(block):
    """A horizontal spacer (an indent): part of its cell's frame, not a
    block in the flow."""
    return block['type'] == 'spacer' and block['orientation'] == 'horizontal'


def _cell_style(cell, index, gap, line_left=False, line_right=False):
    """Inline CSS for one cell: its indents, the row's gap before it (a
    column after the first) and the column lines either side. A line sits
    in the middle of its gap: the left column carries it as its right
    border with half the gap after, the right column the other half.
    Mirrored by the canvas in frontend/src/lib/pdfLayout.js `cellStyle`."""
    indent = {'left': 0, 'right': 0}
    for block in cell:
        if _is_decoration(block):
            indent[block['side']] += INDENTS[block['size']]
    before = (gap // 2 if line_left else gap) if index else 0
    left = before + indent['left']
    right = (gap // 2 if line_right else 0) + indent['right']
    parts = []
    if line_right:
        parts.append(f'border-right: {RULE}')
    if left or index:
        parts.append(f'padding-left: {left}px')
    if right:
        parts.append(f'padding-right: {right}px')
    return '; '.join(parts)


def _resolve_block(kind, block, values, shared):
    block_type = block['type']
    spec = BLOCK_TYPES[block_type]
    out = dict(block)
    out['template'] = (DOCUMENT_TEMPLATES[kind] if spec.get('source') == 'document'
                       else SHARED_TEMPLATE)
    if block_type == 'logo':
        if not shared.get('logo'):
            return None
        out['src'] = shared['logo']
    elif block_type in COMPANY_BLOCKS:
        html = shared.get(block_type, '')
        if is_blank(html):
            return None
        out['html'] = html
    elif block_type == 'text':
        html = render_rich_text(block['html'], values)
        if not html:
            return None
        out['html'] = html
    elif block_type == 'title':
        out['heading'] = block.get('heading') or TITLE_DEFAULTS[kind]
    elif block_type == 'image':
        src = (shared.get('images') or {}).get(block['image'])
        if not src:
            return None
        out['src'] = src
    return out
