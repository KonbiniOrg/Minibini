from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import ServicePrice


class AdjustmentFieldsTest(TestCase):
    def test_estimate_line_can_hold_adjustment_service(self):
        from apps.estimates.models import EstimateLineItem
        # field presence is the assertion; construction covered in later tasks
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_target_categories'))

    def test_invoice_line_can_hold_adjustment_service(self):
        from apps.invoicing.models import InvoiceLineItem
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_target_categories'))
