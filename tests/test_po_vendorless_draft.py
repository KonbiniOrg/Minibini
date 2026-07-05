"""Order-from-material needs a draft PO before the vendor is known (spec Path 1)."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.core.models import AppState, Configuration
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class VendorlessDraftTests(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')

    def test_draft_po_without_business(self):
        po = PurchaseOrderService.create_po()
        self.assertIsNone(po.business_id)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)

    def test_issue_requires_business(self):
        po = PurchaseOrderService.create_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.update_status(po.pk, PurchaseOrder.STATUS_ISSUED)
