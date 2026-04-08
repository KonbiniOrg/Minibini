"""Tests that the API line item endpoints route through service methods.

These tests verify that:
1. Create/update/reorder check parent document status via services
2. PLI-based creates populate fields via the service
3. The mixin delegates to the service, not serializer.save()
"""
from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Business
from apps.inventory.models import PriceListItem
from apps.estimates.models import Estimate, EstimateLineItem


class POLineItemStatusCheckTest(BaseTestCase):
    """API must reject line item operations on non-draft POs."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.business = Business.objects.first()

    def _make_po(self, status=PurchaseOrder.STATUS_DRAFT):
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number=f'PO-LI-TEST-{status}',
            status=status,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Existing item',
            qty=5, price=10,
        )
        return po

    def test_create_line_item_rejected_on_issued_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_ISSUED)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/',
            {'description': 'New item', 'qty': 1, 'price': 10},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_line_item_allowed_on_draft_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_DRAFT)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/',
            {'description': 'New item', 'qty': 1, 'price': 10},
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])

    def test_update_line_item_rejected_on_issued_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_ISSUED)
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.patch(
            f'/api/purchase-orders/{po.po_id}/line-items/{li.line_item_id}/',
            {'description': 'Changed'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_update_line_item_allowed_on_draft_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_DRAFT)
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.patch(
            f'/api/purchase-orders/{po.po_id}/line-items/{li.line_item_id}/',
            {'description': 'Changed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.description, 'Changed')

    def test_reorder_rejected_on_issued_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_ISSUED)
        # Add a second line item so reorder is meaningful
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Second item',
            qty=3, price=15,
        )
        item_ids = list(
            PurchaseOrderLineItem.objects.filter(purchase_order=po)
            .order_by('line_number')
            .values_list('line_item_id', flat=True)
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/reorder/',
            {'item_ids': list(reversed(item_ids))},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_allowed_on_draft_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_DRAFT)
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Second item',
            qty=3, price=15,
        )
        item_ids = list(
            PurchaseOrderLineItem.objects.filter(purchase_order=po)
            .order_by('line_number')
            .values_list('line_item_id', flat=True)
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/reorder/',
            {'item_ids': list(reversed(item_ids))},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_rejected_on_issued_po(self):
        po = self._make_po(status=PurchaseOrder.STATUS_ISSUED)
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.delete(
            f'/api/purchase-orders/{po.po_id}/line-items/{li.line_item_id}/',
        )
        self.assertEqual(response.status_code, 400)


class POLineItemPLIPopulationTest(BaseTestCase):
    """API must populate line item fields from PLI when creating via PLI."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.business = Business.objects.first()
        self.pli = PriceListItem.objects.create(
            code='TEST-PLI-LI',
            description='Widget from catalog',
            units='ea',
            purchase_price=Decimal('42.50'),
            selling_price=Decimal('85.00'),
        )

    def test_create_from_pli_populates_fields(self):
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-PLI-TEST',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/',
            {'price_list_item': self.pli.pk, 'qty': 5},
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])
        self.assertEqual(response.data['description'], 'Widget from catalog')
        self.assertEqual(response.data['units'], 'ea')
        self.assertEqual(Decimal(response.data['price']), Decimal('42.50'))

    def test_create_from_pli_respects_explicit_overrides(self):
        """If caller provides description/price, those take precedence over PLI."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-PLI-OVERRIDE',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/line-items/',
            {
                'price_list_item': self.pli.pk,
                'qty': 5,
                'description': 'Custom description',
                'price': '99.99',
            },
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])
        self.assertEqual(response.data['description'], 'Custom description')
        self.assertEqual(Decimal(response.data['price']), Decimal('99.99'))


class EstimateLineItemStatusCheckTest(BaseTestCase):
    """API must reject line item operations on non-draft estimates."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def _make_estimate(self, status=Estimate.STATUS_DRAFT):
        from apps.jobs.models import Job
        job = Job.objects.first()
        est = Estimate.objects.create(
            job=job,
            estimate_number=f'EST-LI-TEST-{status}',
            status=status,
        )
        EstimateLineItem.objects.create(
            estimate=est, description='Existing item',
            qty=5, price=10,
        )
        return est

    def test_create_rejected_on_open_estimate(self):
        est = self._make_estimate(status=Estimate.STATUS_OPEN)
        response = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'description': 'New item', 'qty': 1, 'price': 10},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_allowed_on_draft_estimate(self):
        est = self._make_estimate(status=Estimate.STATUS_DRAFT)
        response = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'description': 'New item', 'qty': 1, 'price': 10},
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])

    def test_update_rejected_on_open_estimate(self):
        est = self._make_estimate(status=Estimate.STATUS_OPEN)
        li = EstimateLineItem.objects.filter(estimate=est).first()
        response = self.client.patch(
            f'/api/estimates/{est.pk}/line-items/{li.line_item_id}/',
            {'description': 'Changed'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
