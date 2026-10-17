"""The document-PDF layout: rows of columns holding blocks, one independent
layout per document kind (apps/core/pdf_layout.py)."""
import copy
import json

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from tests.base import FixtureTestCase
from apps.core.models import Configuration
from apps.core.pdf_layout import (
    BLOCK_TYPES, COLUMN_PRESETS, block_catalog, default_layout, get_layout,
    layout_key, resolve_layout, save_layout, validate_layout,
)


def _row(columns, *cells):
    return {'columns': columns, 'cells': [list(cell) for cell in cells]}


def _lines_row():
    return _row('full', [{'type': 'line_items'}])


def _layout(*rows):
    return {'version': 1, 'rows': list(rows)}


class ValidateLayoutTests(SimpleTestCase):
    def assertInvalid(self, layout, fragment, kind='estimate'):
        with self.assertRaises(ValidationError) as ctx:
            validate_layout(kind, layout)
        messages = ctx.exception.message_dict['layout']
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_default_layouts_are_valid(self):
        for kind in ('estimate', 'change_order', 'po'):
            layout = default_layout(kind)
            self.assertEqual(validate_layout(kind, layout), layout)

    def test_normalizes_block_defaults_and_keeps_order(self):
        layout = _layout(
            _row('1/2-1/2', [{'type': 'logo'}], [{'type': 'company_name', 'align': 'right'},
                                                 {'type': 'company_phone'}]),
            _row('full', [{'type': 'spacer'}]),
            _lines_row(),
        )
        out = validate_layout('po', layout)
        self.assertEqual(out['rows'][0]['cells'][0], [{'type': 'logo', 'align': 'left'}])
        self.assertEqual(out['rows'][0]['cells'][1], [
            {'type': 'company_name', 'align': 'right'},
            {'type': 'company_phone', 'align': 'left'},
        ])
        self.assertEqual(out['rows'][1]['cells'][0], [
            {'type': 'spacer', 'orientation': 'vertical', 'size': 'medium', 'side': 'left'},
        ])

    def test_does_not_mutate_its_input(self):
        layout = _layout(_row('full', [{'type': 'logo'}]), _lines_row())
        before = copy.deepcopy(layout)
        validate_layout('estimate', layout)
        self.assertEqual(layout, before)

    def test_text_is_sanitized(self):
        layout = _layout(
            _row('full', [{'type': 'text', 'html': '<p onclick="x">Hi<img src="file:///x"></p>'
                                                   '<script>bad</script>'}]),
            _lines_row())
        out = validate_layout('estimate', layout)
        self.assertEqual(out['rows'][0]['cells'][0][0],
                         {'type': 'text', 'align': 'left', 'html': '<p>Hi</p>'})

    def test_must_be_an_object_with_version_one(self):
        self.assertInvalid([], 'must be an object')
        self.assertInvalid({'rows': [_lines_row()]}, 'version')
        self.assertInvalid({'version': 2, 'rows': [_lines_row()]}, 'version')

    def test_rows_must_be_a_non_empty_list(self):
        self.assertInvalid({'version': 1, 'rows': []}, 'at least one row')
        self.assertInvalid({'version': 1, 'rows': 'x'}, 'at least one row')

    def test_row_count_is_capped(self):
        rows = [_row('full', [{'type': 'spacer'}]) for _ in range(40)] + [_lines_row()]
        self.assertInvalid(_layout(*rows), 'at most 40 rows')

    def test_unknown_column_preset(self):
        self.assertInvalid(_layout(_row('1/4-3/4', [], []), _lines_row()), 'Row 1')

    def test_cell_count_must_match_the_preset(self):
        self.assertInvalid(_layout(_row('1/2-1/2', [{'type': 'logo'}]), _lines_row()),
                           'Row 1 needs 2 columns')

    def test_blocks_per_cell_are_capped(self):
        cell = [{'type': 'spacer'}] * 21
        self.assertInvalid(_layout(_row('full', cell), _lines_row()), 'at most 20 blocks')

    def test_unknown_block_type(self):
        self.assertInvalid(_layout(_row('full', [{'type': 'video'}]), _lines_row()),
                           'unknown block')

    def test_unknown_block_setting(self):
        self.assertInvalid(
            _layout(_row('full', [{'type': 'logo', 'style': 'x'}]), _lines_row()),
            'style')

    def test_bad_alignment_and_spacer_size(self):
        self.assertInvalid(
            _layout(_row('full', [{'type': 'logo', 'align': 'justify'}]), _lines_row()), 'align')
        self.assertInvalid(
            _layout(_row('full', [{'type': 'spacer', 'size': 'huge'}]), _lines_row()), 'size')

    def test_text_html_must_be_text_and_is_capped(self):
        self.assertInvalid(
            _layout(_row('full', [{'type': 'text', 'html': 5}]), _lines_row()), 'text')
        self.assertInvalid(
            _layout(_row('full', [{'type': 'text', 'html': 'x' * 20001}]), _lines_row()),
            'too long')

    def test_line_items_exactly_once(self):
        self.assertInvalid(_layout(_row('full', [{'type': 'title'}])), 'line items')
        self.assertInvalid(_layout(_lines_row(), _lines_row()), 'line items')

    def test_line_items_alone_in_a_full_row(self):
        self.assertInvalid(
            _layout(_row('1/2-1/2', [{'type': 'line_items'}], [])), 'full-width row')
        self.assertInvalid(
            _layout(_row('full', [{'type': 'line_items'}, {'type': 'spacer'}])), 'by itself')

    def test_title_and_details_at_most_once(self):
        self.assertInvalid(
            _layout(_row('1/2-1/2', [{'type': 'title'}], [{'type': 'title'}]), _lines_row()),
            'Title')
        self.assertInvalid(
            _layout(_row('full', [{'type': 'details'}, {'type': 'details'}]), _lines_row()),
            'Details')

    def test_logos_and_text_may_repeat(self):
        layout = _layout(
            _row('1/3-1/3-1/3', [{'type': 'logo'}], [{'type': 'text', 'html': 'a'}],
                 [{'type': 'logo'}, {'type': 'text', 'html': 'b'}]),
            _lines_row())
        validate_layout('estimate', layout)


class CatalogTests(SimpleTestCase):
    def test_catalog_names_each_kinds_default_heading(self):
        self.assertEqual(block_catalog('po')['default_heading'], 'Purchase Order')
        self.assertEqual(block_catalog('change_order')['default_heading'], 'Change Order')

    def test_catalog_lists_every_block_with_labels_and_rules(self):
        catalog = block_catalog('po')
        types = [b['type'] for b in catalog['blocks']]
        self.assertEqual(set(types), set(BLOCK_TYPES))
        lines = next(b for b in catalog['blocks'] if b['type'] == 'line_items')
        self.assertTrue(lines['single'])
        self.assertTrue(lines['required'])
        logo = next(b for b in catalog['blocks'] if b['type'] == 'logo')
        self.assertFalse(logo['single'])
        self.assertEqual(catalog['presets'], [
            {'key': key, 'widths': widths} for key, widths in COLUMN_PRESETS.items()])

    def test_layout_keys_are_per_kind(self):
        self.assertEqual(layout_key('estimate'), 'estimate_pdf_layout')
        self.assertEqual(layout_key('po'), 'po_pdf_layout')


class StoredLayoutTests(FixtureTestCase):
    def test_get_falls_back_to_the_default(self):
        self.assertEqual(get_layout('estimate'), default_layout('estimate'))

    def test_save_validates_and_stores_canonical_json_per_kind(self):
        layout = _layout(_lines_row(), _row('full', [{'type': 'text', 'html': '<p>PO</p>'}]))
        saved = save_layout('po', layout)
        self.assertEqual(get_layout('po'), saved)
        self.assertEqual(json.loads(Configuration.objects.get(key='po_pdf_layout').value), saved)
        # Independent per document.
        self.assertEqual(get_layout('estimate'), default_layout('estimate'))

    def test_save_rejects_an_invalid_layout_and_stores_nothing(self):
        with self.assertRaises(ValidationError):
            save_layout('po', _layout(_row('full', [{'type': 'title'}])))
        self.assertFalse(Configuration.objects.filter(key='po_pdf_layout').exists())

    def test_unreadable_stored_layout_falls_back_to_the_default(self):
        Configuration.objects.create(key='po_pdf_layout', value='{not json')
        self.assertEqual(get_layout('po'), default_layout('po'))
        Configuration.objects.filter(key='po_pdf_layout').update(
            value=json.dumps(_layout(_row('full', [{'type': 'video'}]))))
        self.assertEqual(get_layout('po'), default_layout('po'))


class ResolveLayoutTests(SimpleTestCase):
    shared = {
        'logo': 'data:image/png;base64,AAAA',
        'company_name': '<p>Neal CNC</p>',
        'company_address': '',
        'company_phone': '<p>555</p>',
        'company_email': '',
    }

    def _resolve(self, layout, values=None, shared=None):
        return resolve_layout('estimate', validate_layout('estimate', layout),
                              values or {}, shared or self.shared)

    def test_blocks_carry_their_template_and_rendered_content(self):
        rows = self._resolve(_layout(
            _row('1/3-2/3', [{'type': 'logo', 'align': 'center'}],
                 [{'type': 'company_name', 'align': 'right'},
                  {'type': 'text', 'html': '<p>For {contact_fname}</p>'}]),
            _lines_row()), values={'contact_fname': '<Pat>'})
        top = rows[0]
        self.assertFalse(top['flow'])
        self.assertEqual(top['widths'], COLUMN_PRESETS['1/3-2/3'])
        logo, = top['cells'][0]['blocks']
        self.assertEqual(logo['template'], 'pdf/_blocks.html')
        self.assertEqual(logo['src'], self.shared['logo'])
        self.assertEqual(logo['align'], 'center')
        name, text = top['cells'][1]['blocks']
        self.assertEqual(name['html'], '<p>Neal CNC</p>')
        self.assertEqual(text['html'], '<p>For &lt;Pat&gt;</p>')

    def test_document_blocks_use_the_kinds_template(self):
        rows = resolve_layout('po', default_layout('po'), {}, self.shared)
        templates = {b['type']: b['template'] for r in rows for c in r['cells'] for b in c['blocks']}
        self.assertEqual(templates['line_items'], 'purchasing/_po_blocks.html')
        self.assertEqual(templates['title'], 'purchasing/_po_blocks.html')
        rows = resolve_layout('change_order', default_layout('change_order'), {}, self.shared)
        templates = {b['type']: b['template'] for r in rows for c in r['cells'] for b in c['blocks']}
        self.assertEqual(templates['details'], 'estimates/_change_order_blocks.html')

    def test_full_width_rows_flow(self):
        rows = self._resolve(_layout(_row('full', [{'type': 'title'}]), _lines_row()))
        self.assertEqual([r['flow'] for r in rows], [True, True])

    def test_empty_blocks_and_rows_are_dropped(self):
        rows = self._resolve(_layout(
            _row('1/2-1/2', [{'type': 'company_address'}], [{'type': 'text', 'html': '<p> </p>'}]),
            _row('1/2-1/2', [{'type': 'company_email'}], [{'type': 'company_phone'}]),
            _lines_row()))
        self.assertEqual(len(rows), 2)
        # A kept row keeps its empty cell so the columns hold their place.
        self.assertEqual(rows[0]['cells'][0]['blocks'], [])
        self.assertEqual([b['type'] for b in rows[0]['cells'][1]['blocks']], ['company_phone'])

    def test_no_logo_means_no_logo_block(self):
        rows = self._resolve(_layout(_row('full', [{'type': 'logo'}]), _lines_row()),
                             shared={**self.shared, 'logo': ''})
        self.assertEqual(len(rows), 1)


class SpacerAndGapTests(SimpleTestCase):
    """Spacers make a vertical gap or indent a column; a column row's gap is
    small / medium / large."""

    def assertInvalid(self, layout, fragment):
        with self.assertRaises(ValidationError) as ctx:
            validate_layout('estimate', layout)
        messages = ctx.exception.message_dict['layout']
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_orientation_and_side_are_validated(self):
        for block, fragment in (({'type': 'spacer', 'orientation': 'sideways'}, 'orientation'),
                                ({'type': 'spacer', 'side': 'top'}, 'side')):
            self.assertInvalid(_layout(_row('full', [block]), _lines_row()), fragment)

    def test_there_is_no_divider_block(self):
        self.assertInvalid(_layout(_row('full', [{'type': 'divider'}]), _lines_row()), 'unknown block')

    def test_gap_is_kept_only_when_not_medium_and_only_on_column_rows(self):
        out = validate_layout('estimate', _layout(
            dict(_row('1/2-1/2', [{'type': 'logo'}], [{'type': 'title'}]), gap='large'),
            dict(_row('1/2-1/2', [{'type': 'logo'}], [{'type': 'logo'}]), gap='medium'),
            dict(_row('full', [{'type': 'logo'}]), gap='small'),
            _lines_row()))
        self.assertEqual(out['rows'][0]['gap'], 'large')
        self.assertNotIn('gap', out['rows'][1])
        self.assertNotIn('gap', out['rows'][2])
        self.assertInvalid(_layout(dict(_row('1/2-1/2', [], []), gap='huge'), _lines_row()), 'gap')

    shared = {'logo': '', 'company_name': '<p>Neal CNC</p>', 'company_address': '<p>1 Mill Rd</p>',
              'company_phone': '', 'company_email': ''}

    def _resolve(self, *rows):
        return resolve_layout('estimate', validate_layout('estimate', _layout(*rows, _lines_row())),
                              {}, self.shared)

    def test_indents_add_up_with_the_gap(self):
        rows = self._resolve(dict(_row(
            '1/2-1/2', [{'type': 'company_name'},
                        {'type': 'spacer', 'orientation': 'horizontal', 'side': 'right', 'size': 'large'}],
            [{'type': 'spacer', 'orientation': 'horizontal', 'side': 'left', 'size': 'small'},
             {'type': 'company_address'}]), gap='large'))
        left, right = rows[0]['cells']
        self.assertEqual(left['style'], 'padding-right: 48px')
        self.assertEqual(right['style'], 'padding-left: 44px')   # 32 gap + 12 indent
        self.assertEqual([b['type'] for b in left['blocks']], ['company_name'])

    def test_vertical_spacers_still_print_as_blocks(self):
        rows = self._resolve(_row('full', [{'type': 'spacer'}, {'type': 'company_name'}]))
        self.assertEqual([b['type'] for b in rows[0]['cells'][0]['blocks']], ['spacer', 'company_name'])

    def test_a_row_of_only_indents_prints_nothing(self):
        rows = self._resolve(_row(
            '1/2-1/2', [{'type': 'spacer', 'orientation': 'horizontal'}],
            [{'type': 'spacer', 'orientation': 'horizontal'}]))
        self.assertEqual(len(rows), 1)   # just the line items


class LineTests(SimpleTestCase):
    """Divider lines sit on borders, not in blocks: under a block
    (`line_below` on the block), under a row (`line_below` on the row), or
    between two columns (`column_lines` on the row)."""

    def assertInvalid(self, layout, fragment):
        with self.assertRaises(ValidationError) as ctx:
            validate_layout('estimate', layout)
        messages = ctx.exception.message_dict['layout']
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_lines_are_kept_only_where_set(self):
        out = validate_layout('estimate', _layout(
            dict(_row('1/3-1/3-1/3', [{'type': 'logo', 'line_below': True}],
                      [{'type': 'company_name', 'line_below': False}], [{'type': 'title'}]),
                 line_below=True, column_lines=[True, False]),
            dict(_row('1/2-1/2', [{'type': 'logo'}], [{'type': 'logo'}]),
                 line_below=False, column_lines=[False]),
            _lines_row()))
        first, second = out['rows'][:2]
        self.assertEqual(first['cells'][0], [{'type': 'logo', 'align': 'left', 'line_below': True}])
        self.assertEqual(first['cells'][1], [{'type': 'company_name', 'align': 'left'}])
        self.assertTrue(first['line_below'])
        self.assertEqual(first['column_lines'], [True, False])
        self.assertNotIn('line_below', second)
        self.assertNotIn('column_lines', second)

    def test_column_lines_are_dropped_on_full_rows(self):
        out = validate_layout('estimate', _layout(
            dict(_row('full', [{'type': 'logo'}]), column_lines=[]), _lines_row()))
        self.assertNotIn('column_lines', out['rows'][0])

    def test_bad_lines_are_rejected(self):
        self.assertInvalid(_layout(_row('full', [{'type': 'logo', 'line_below': 'yes'}]), _lines_row()),
                           'line_below')
        self.assertInvalid(_layout(dict(_row('full', [{'type': 'logo'}]), line_below=1), _lines_row()),
                           'line_below')
        self.assertInvalid(_layout(dict(_row('1/2-1/2', [], []), column_lines=[True, True]),
                                   _lines_row()), 'column_lines')
        self.assertInvalid(_layout(dict(_row('1/2-1/2', [], []), column_lines=['x']),
                                   _lines_row()), 'column_lines')

    shared = SpacerAndGapTests.shared

    def _resolve(self, *rows):
        return resolve_layout('estimate', validate_layout('estimate', _layout(*rows, _lines_row())),
                              {}, self.shared)

    def test_a_column_line_sits_in_the_middle_of_the_gap(self):
        rows = self._resolve(dict(
            _row('1/2-1/2', [{'type': 'company_name'}], [{'type': 'company_address'}]),
            column_lines=[True]))
        left, right = rows[0]['cells']
        self.assertEqual(left['style'], 'border-right: 1px solid #333; padding-right: 8px')
        self.assertEqual(right['style'], 'padding-left: 8px')

    def test_block_and_row_lines_come_through(self):
        rows = self._resolve(dict(
            _row('full', [{'type': 'company_name', 'line_below': True}]), line_below=True))
        self.assertTrue(rows[0]['line_below'])
        self.assertTrue(rows[0]['cells'][0]['blocks'][0]['line_below'])
        self.assertFalse(self._resolve(_row('full', [{'type': 'company_name'}]))[0]['line_below'])


class TitleAndImageBlockTests(SimpleTestCase):
    """The title's heading is editable text; image blocks place a picture
    from the shared image library."""

    IMAGE = 'a' * 32

    def assertInvalid(self, layout, fragment):
        with self.assertRaises(ValidationError) as ctx:
            validate_layout('estimate', layout)
        messages = ctx.exception.message_dict['layout']
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_heading_is_plain_text_trimmed_and_capped(self):
        out = validate_layout('estimate', _layout(
            _row('full', [{'type': 'title', 'heading': '  Quote  '}]), _lines_row()))
        self.assertEqual(out['rows'][0]['cells'][0][0],
                         {'type': 'title', 'align': 'left', 'heading': 'Quote'})
        self.assertInvalid(_layout(_row('full', [{'type': 'title', 'heading': 'x' * 81}]),
                                   _lines_row()), 'heading')
        self.assertInvalid(_layout(_row('full', [{'type': 'title', 'heading': 5}]),
                                   _lines_row()), 'heading')

    def test_a_blank_heading_prints_the_documents_own_name(self):
        for kind, name in (('estimate', 'Estimate'), ('change_order', 'Change Order'),
                           ('po', 'Purchase Order')):
            rows = resolve_layout(kind, default_layout(kind), {}, {'logo': ''})
            title = next(b for r in rows for c in r['cells'] for b in c['blocks']
                         if b['type'] == 'title')
            self.assertEqual(title['heading'], name)
        rows = resolve_layout('po', validate_layout('po', _layout(
            _row('full', [{'type': 'title', 'heading': 'Order'}]), _lines_row())), {}, {})
        self.assertEqual(rows[0]['cells'][0]['blocks'][0]['heading'], 'Order')

    def test_image_blocks_are_validated(self):
        out = validate_layout('estimate', _layout(
            _row('full', [{'type': 'image', 'image': self.IMAGE, 'size': 'large'}, {'type': 'image'}]),
            _lines_row()))
        self.assertEqual(out['rows'][0]['cells'][0], [
            {'type': 'image', 'image': self.IMAGE, 'align': 'left', 'size': 'large'},
            {'type': 'image', 'image': '', 'align': 'left', 'size': 'medium'},
        ])
        self.assertInvalid(_layout(_row('full', [{'type': 'image', 'image': '../etc'}]), _lines_row()),
                           'image')
        self.assertInvalid(_layout(_row('full', [{'type': 'image', 'size': 'huge'}]), _lines_row()),
                           'size')

    def test_an_image_prints_from_the_library_or_not_at_all(self):
        layout = validate_layout('estimate', _layout(
            _row('full', [{'type': 'image', 'image': self.IMAGE}, {'type': 'image'},
                          {'type': 'image', 'image': 'b' * 32}]), _lines_row()))
        rows = resolve_layout('estimate', layout, {},
                              {'logo': '', 'images': {self.IMAGE: 'data:image/png;base64,AAAA'}})
        image, = rows[0]['cells'][0]['blocks']
        self.assertEqual(image['src'], 'data:image/png;base64,AAAA')
        self.assertEqual(image['template'], 'pdf/_blocks.html')
