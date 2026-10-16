"""The data migration that converts the document-PDF branding values from
plain text to the rich-text format, so saved text prints as before."""
import importlib

from django.test import SimpleTestCase

migration = importlib.import_module('apps.core.migrations.0004_pdf_branding_rich_text')


class PlainToRichTests(SimpleTestCase):
    def test_lines_become_paragraphs_and_text_is_escaped(self):
        self.assertEqual(
            migration.plain_to_rich('pdf_company_address', '1 Mill Rd\r\nA & B <Unit 2>'),
            '<p>1 Mill Rd</p><p>A &amp; B &lt;Unit 2&gt;</p>')

    def test_blank_lines_are_kept(self):
        self.assertEqual(
            migration.plain_to_rich('po_pdf_text_below_totals', 'a\n\nb'),
            '<p>a</p><p></p><p>b</p>')

    def test_surrounding_whitespace_is_trimmed_as_the_old_render_did(self):
        self.assertEqual(
            migration.plain_to_rich('estimate_pdf_text_page_footer', '  \nPage {page}\n '),
            '<p>Page {page}</p>')

    def test_company_name_keeps_its_bold_larger_look(self):
        self.assertEqual(
            migration.plain_to_rich('pdf_company_name', "Neal's CNC"),
            '<p><strong><span class="size-large">Neal\'s CNC</span></strong></p>')

    def test_blank_stays_blank(self):
        self.assertEqual(migration.plain_to_rich('pdf_company_phone', '  '), '')

    def test_rich_to_plain_reverses(self):
        for key, plain in (('pdf_company_address', '1 Mill Rd\nA & B <Unit 2>'),
                           ('pdf_company_name', "Neal's CNC"),
                           ('po_pdf_text_below_totals', 'a\n\nb')):
            self.assertEqual(migration.rich_to_plain(migration.plain_to_rich(key, plain)), plain)

    def test_converts_exactly_the_rich_text_keys(self):
        from apps.core.pdf_branding import RICH_TEXT_KEYS
        self.assertEqual(set(migration.RICH_KEYS), set(RICH_TEXT_KEYS))
