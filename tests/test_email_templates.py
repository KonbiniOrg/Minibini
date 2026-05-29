from django.test import TestCase

from apps.core.email_templates import render_email_template


class RenderEmailTemplateTest(TestCase):
    """SafeDict-style str.format_map: unknown placeholders pass through."""

    def test_known_placeholders_render(self):
        result = render_email_template(
            'Hi {contact_fname},\n\nQuote {document_number} is ready.',
            contact_fname='Jane',
            document_number='EST-2026-0001',
        )
        self.assertEqual(
            result, 'Hi Jane,\n\nQuote EST-2026-0001 is ready.'
        )

    def test_unknown_placeholders_pass_through_literal(self):
        result = render_email_template(
            'Hi {contact_fname}, your {nonexistent} is ready.',
            contact_fname='Bob',
        )
        self.assertEqual(result, 'Hi Bob, your {nonexistent} is ready.')

    def test_none_values_render_as_empty_string(self):
        result = render_email_template(
            'Job {job_number} for {contact_business}.',
            job_number='JOB-001',
            contact_business=None,
        )
        self.assertEqual(result, 'Job JOB-001 for .')

    def test_empty_template_returns_empty(self):
        self.assertEqual(render_email_template('', x=1), '')

    def test_no_placeholders_returns_unchanged(self):
        result = render_email_template('Plain text body.', x=1)
        self.assertEqual(result, 'Plain text body.')

    def test_repeated_placeholder(self):
        result = render_email_template(
            '{document_number} — see {document_number}.',
            document_number='PO-9',
        )
        self.assertEqual(result, 'PO-9 — see PO-9.')

    def test_braces_in_template_are_preserved_when_no_match(self):
        # Curly-brace content that isn't a known placeholder shouldn't error.
        result = render_email_template(
            'Use {variable_name} — also literal {{ and }}.',
            other='nope',
        )
        # {{ and }} are escape sequences for str.format, rendering as { and }
        self.assertIn('{variable_name}', result)
        self.assertIn('{', result)
        self.assertIn('}', result)
