"""I2 review finding: PDF templates hand-rolled `${{ x|floatformat:2 }}`,
which renders a negative amount as the nonsensical "$-500.00" (the literal
`$` lands before floatformat's own minus sign). The `money` templatetag
filter (apps/core/templatetags/money.py) owns the `$` placement instead,
producing "-$500.00" — mirroring the SPA's formatMoney
(frontend/src/lib/format.js). Covers the filter directly and its use in
both estimate_pdf.html and change_order_pdf.html.
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from apps.core.templatetags.money import money


class MoneyFilterTest(SimpleTestCase):
    def test_negative_amount_sign_before_dollar(self):
        self.assertEqual(money(Decimal('-500.00')), '-$500.00')

    def test_positive_amount_no_sign(self):
        self.assertEqual(money(Decimal('500.00')), '$500.00')

    def test_zero_amount_no_sign(self):
        self.assertEqual(money(Decimal('0.00')), '$0.00')

    def test_thousands_grouping(self):
        self.assertEqual(money(Decimal('-1234.5')), '-$1,234.50')

    def test_accepts_string_and_float_input(self):
        self.assertEqual(money('-80'), '-$80.00')
        self.assertEqual(money(80), '$80.00')

    def test_unparseable_value_returned_unchanged(self):
        self.assertEqual(money('not-a-number'), 'not-a-number')


class EstimatePdfNegativeLineRenderTest(TestCase):
    """Renders estimate_pdf.html directly (same pattern as
    test_change_order_pdf.py's test_pdf_shows_date_after_send) with a
    negative-price line, asserting the sign lands before the '$'."""

    def test_negative_line_renders_sign_before_dollar(self):
        html = render_to_string('estimates/estimate_pdf.html', {
            'estimate': {
                'estimate_number': 'EST-MONEY-1',
                'sent_date': None, 'created_date': None, 'expiration_date': None,
            },
            'job': None,
            'business_name': '', 'contact_name': '',
            'line_items': [{
                'line_number': 1, 'description': 'Credit',
                'qty': Decimal('1'), 'units': 'ea',
                'price': Decimal('-500.00'), 'total_amount': Decimal('-500.00'),
            }],
            'total': Decimal('-500.00'),
        })
        self.assertIn('-$500.00', html)
        self.assertNotIn('$-500.00', html)


class ChangeOrderPdfNegativeLineRenderTest(TestCase):
    """Renders change_order_pdf.html directly with a negative diff row."""

    def test_negative_line_renders_sign_before_dollar(self):
        html = render_to_string('estimates/change_order_pdf.html', {
            'co': {'change_order_number': 'CO-MONEY-1', 'sent_date': None,
                   'created_date': None, 'expiration_date': None},
            'job': None,
            'business_name': '', 'contact_name': '',
            'estimate_number': 'EST-MONEY-1',
            'deliverable_rows': [],
            'line_rows': [{
                'kind': 'added', 'line_number': 1, 'description': 'Credit',
                'qty': Decimal('1'), 'units': 'ea',
                'price': Decimal('-300.00'), 'amount': Decimal('-300.00'),
            }],
            'prior_total': Decimal('1000.00'),
            'proposed_total': Decimal('700.00'),
            'diff_total': Decimal('-300.00'),
        })
        self.assertIn('-$300.00', html)
        self.assertNotIn('$-300.00', html)
