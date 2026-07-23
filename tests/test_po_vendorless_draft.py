"""Order-from-material needs a draft PO before the vendor is known (spec Path 1).

The invariant is "a PO that is not draft has a vendor". It lives in
PurchaseOrder.clean() (unconditional — new and existing instances alike);
the service-level checks in update_status/send_po are pre-emptive duplicates
that give a clean field error before other clean() noise.

No cancelled exemption: cancelled is only reachable from issued (model
VALID_TRANSITIONS + cancel_po's issued-only check), issued implies a vendor,
and the vendor cannot be nulled after draft — so every cancelled PO has a
business. Vendor-less drafts are deleted, not cancelled.
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AppState, Configuration, User
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class VendorlessDraftTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})

    def test_draft_po_without_business(self):
        po = PurchaseOrderService.create_po()
        self.assertIsNone(po.business_id)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)

    def test_issue_requires_business(self):
        po = PurchaseOrderService.create_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.update_status(po.pk, PurchaseOrder.STATUS_ISSUED)

    def test_model_rejects_nondraft_without_business(self):
        """The invariant lives in PurchaseOrder.clean(): any save of a
        non-draft vendor-less PO fails, including brand-new instances
        (clean()'s transition checks only run for self.pk, so this guard
        must be unconditional)."""
        po = PurchaseOrder(status=PurchaseOrder.STATUS_ISSUED)
        with self.assertRaises(ValidationError) as cm:
            po.save()
        self.assertIn('business', cm.exception.message_dict)


class VendorlessDraftAPITests(TestCase):
    """The REST endpoints must not be able to bypass the issue gate."""

    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(
            username='po_admin', password='x', is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _vendor(self):
        contact = Contact.objects.create(
            first_name='Vendor', last_name='Person', email='v@example.com')
        business = Business.objects.create(
            business_name='Vendor Co', default_contact=contact)
        contact.business = business
        contact.save()
        return business

    def test_api_create_issued_without_business_rejected(self):
        """POST with status=issued and no business must 400 (status is a
        writable serializer field; create_po runs full_clean on a new
        instance where the pk-guarded transition checks don't fire)."""
        response = self.client.post(
            '/api/purchase-orders/', {'status': 'issued'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('business', response.data)
        self.assertFalse(
            PurchaseOrder.objects.filter(status=PurchaseOrder.STATUS_ISSUED).exists())

    def test_api_cannot_null_business_on_issued_po(self):
        """PATCH {'business': null} on an issued PO must 400 — the field is
        nullable now, so without the model guard update_po's setattr +
        full_clean would let the vendor vanish from an issued PO."""
        business = self._vendor()
        po = PurchaseOrderService.create_po(business=business)
        PurchaseOrderService.add_line_item(
            po.pk, description='Widget', qty=Decimal('1'), price=Decimal('10'))
        PurchaseOrderService.update_status(po.pk, PurchaseOrder.STATUS_ISSUED)

        response = self.client.patch(
            f'/api/purchase-orders/{po.pk}/', {'business': None}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('business', response.data)
        po.refresh_from_db()
        self.assertEqual(po.business_id, business.pk)

    def test_api_can_null_business_on_draft_po(self):
        """Clearing the vendor on a draft stays legal — that's the point of
        the feature."""
        business = self._vendor()
        po = PurchaseOrderService.create_po(business=business)
        response = self.client.patch(
            f'/api/purchase-orders/{po.pk}/', {'business': None}, format='json')
        self.assertEqual(response.status_code, 200)
        po.refresh_from_db()
        self.assertIsNone(po.business_id)
