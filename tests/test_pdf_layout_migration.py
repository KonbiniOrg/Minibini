"""The data migration that turns the fixed document-PDF arrangement (logo
position + three body text slots per document) into one stored layout per
document, so every PDF prints as it did."""
import importlib

from django.test import SimpleTestCase

from apps.core.pdf_layout import validate_layout

migration = importlib.import_module('apps.core.migrations.0005_pdf_layouts')

LOGO = 'data:image/png;base64,AAAA'


def _types(row):
    return [[block['type'] for block in cell] for cell in row['cells']]


class BuildLayoutTests(SimpleTestCase):
    def test_every_built_layout_validates_unchanged(self):
        for stored in ({}, {'pdf_logo': LOGO, 'pdf_logo_position': 'right',
                            'po_pdf_text_below_header': '<p>a</p>',
                            'po_pdf_text_above_lines': '<p>b</p>',
                            'po_pdf_text_below_totals': '<p>c</p>'}):
            for kind in ('estimate', 'change_order', 'po'):
                layout = migration.build_layout(kind, stored)
                self.assertEqual(validate_layout(kind, layout), layout)

    def test_order_matches_the_old_template(self):
        layout = migration.build_layout('estimate', {
            'estimate_pdf_text_below_header': '<p>under title</p>',
            'estimate_pdf_text_above_lines': '<p>before lines</p>',
            'estimate_pdf_text_below_totals': '<p>terms</p>',
            'po_pdf_text_below_totals': '<p>not mine</p>',
        })
        rows = layout['rows']
        self.assertEqual([_types(r) for r in rows], [
            [['logo', 'company_name', 'company_address', 'company_phone', 'company_email']],
            [['title']], [['text']], [['details']], [['text']], [['line_items']], [['text']],
        ])
        self.assertEqual(
            [r['cells'][0][0].get('html') for r in rows if _types(r) == [['text']]],
            ['<p>under title</p>', '<p>before lines</p>', '<p>terms</p>'])
        self.assertTrue(all(r['columns'] == 'full' for r in rows))

    def test_blank_slots_get_no_text_row(self):
        layout = migration.build_layout('po', {'po_pdf_text_below_totals': '<p> </p>'})
        self.assertEqual([_types(r) for r in layout['rows']][1:],
                         [[['title']], [['details']], [['line_items']]])

    def test_no_logo_keeps_the_company_block_left(self):
        row = migration.build_layout('po', {'pdf_logo_position': 'right'})['rows'][0]
        self.assertEqual(row['columns'], 'full')
        self.assertTrue(all(b['align'] == 'left' for b in row['cells'][0]))

    def test_logo_left_puts_the_company_on_the_right(self):
        row = migration.build_layout('po', {'pdf_logo': LOGO})['rows'][0]
        self.assertEqual(row['columns'], '1/2-1/2')
        self.assertEqual(row['cells'][0], [{'type': 'logo', 'align': 'left'}])
        self.assertEqual({b['align'] for b in row['cells'][1]}, {'right'})

    def test_logo_right_puts_the_company_on_the_left(self):
        row = migration.build_layout(
            'po', {'pdf_logo': LOGO, 'pdf_logo_position': 'right'})['rows'][0]
        self.assertEqual(row['columns'], '1/2-1/2')
        self.assertEqual({b['align'] for b in row['cells'][0]}, {'left'})
        self.assertEqual(row['cells'][1], [{'type': 'logo', 'align': 'right'}])

    def test_logo_center_stacks_everything_centered(self):
        row = migration.build_layout(
            'po', {'pdf_logo': LOGO, 'pdf_logo_position': 'center'})['rows'][0]
        self.assertEqual(row['columns'], 'full')
        self.assertEqual(row['cells'][0][0]['type'], 'logo')
        self.assertEqual({b['align'] for b in row['cells'][0]}, {'center'})


class IsBrandedTests(SimpleTestCase):
    def test_nothing_set_stores_no_layout(self):
        self.assertFalse(migration.is_branded({}))
        self.assertFalse(migration.is_branded({
            'pdf_logo_position': 'right', 'pdf_company_name': '<p></p>',
            'po_pdf_text_below_totals': ''}))

    def test_any_logo_company_text_or_slot_stores_layouts(self):
        for stored in ({'pdf_logo': LOGO}, {'pdf_company_phone': '<p>555</p>'},
                       {'estimate_pdf_text_above_lines': '<p>x</p>'}):
            self.assertTrue(migration.is_branded(stored), stored)


class ReverseTests(SimpleTestCase):
    def test_slots_and_logo_position_come_back(self):
        stored = {
            'pdf_logo': LOGO, 'pdf_logo_position': 'right',
            'estimate_pdf_text_below_header': '<p>a</p>',
            'estimate_pdf_text_above_lines': '<p>b</p>',
            'estimate_pdf_text_below_totals': '<p>c</p>',
        }
        layout = migration.build_layout('estimate', stored)
        self.assertEqual(migration.slots_from_layout('estimate', layout), {
            'estimate_pdf_text_below_header': '<p>a</p>',
            'estimate_pdf_text_above_lines': '<p>b</p>',
            'estimate_pdf_text_below_totals': '<p>c</p>',
        })
        self.assertEqual(migration.logo_position_from_layout(layout), 'right')

    def test_logo_positions_round_trip(self):
        for position in ('left', 'center', 'right'):
            layout = migration.build_layout(
                'po', {'pdf_logo': LOGO, 'pdf_logo_position': position})
            self.assertEqual(migration.logo_position_from_layout(layout), position)

    def test_texts_sharing_a_slot_are_joined(self):
        layout = migration.build_layout('po', {})
        layout['rows'].append({'columns': '1/2-1/2', 'cells': [
            [{'type': 'text', 'align': 'left', 'html': '<p>x</p>'}],
            [{'type': 'text', 'align': 'left', 'html': '<p>y</p>'}]]})
        self.assertEqual(migration.slots_from_layout('po', layout),
                         {'po_pdf_text_below_totals': '<p>x</p><p>y</p>'})
