"""Job detail `nav_targets` — the ids the job nav rail links to.

Detail-only serializer field: {'estimate': id|None, 'invoice': id|None,
'po': id|None}, resolving each category's most recent live document.
Null in list context (same rule as the financial rollups).
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import Estimate
from apps.inventory.models import InventoryItem, Material
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class JobNavTargetsTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='navuser', password='p')
        contact = Contact.objects.create(first_name='N', last_name='N', work_number='5')
        self.business = Business.objects.create(business_name='NavCo', default_contact=contact)
        contact.business = self.business
        contact.save()
        self.contact = contact
        self.job = Job.objects.create(job_number='J-NAV-1', contact=contact, description='nav')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _detail(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_empty_job_has_null_targets(self):
        targets = self._detail()['nav_targets']
        self.assertEqual(targets, {'estimate': None, 'invoice': None, 'po': None})

    def test_estimate_target_is_latest_non_superseded_version(self):
        old = Estimate.objects.create(
            job=self.job, estimate_number='EST-NAV-1', version=1,
            status=Estimate.STATUS_SUPERSEDED,
        )
        current = Estimate.objects.create(
            job=self.job, estimate_number='EST-NAV-2', version=2,
            status=Estimate.STATUS_OPEN,
        )
        targets = self._detail()['nav_targets']
        self.assertEqual(targets['estimate'], current.pk)
        self.assertNotEqual(targets['estimate'], old.pk)

    def test_invoice_target_is_latest_non_superseded(self):
        old = Invoice.objects.create(
            job=self.job, invoice_number='INV-NAV-1',
            status=Invoice.STATUS_SUPERSEDED,
        )
        current = Invoice.objects.create(
            job=self.job, invoice_number='INV-NAV-2',
            status=Invoice.STATUS_OPEN,
        )
        targets = self._detail()['nav_targets']
        self.assertEqual(targets['invoice'], current.pk)
        self.assertNotEqual(targets['invoice'], old.pk)

    def test_po_target_resolves_via_job_materials(self):
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        item = InventoryItem.objects.create(
            code='NAV-P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        po = PurchaseOrder.objects.create(business=self.business)
        PurchaseOrderService.add_line_item(
            po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=item.pk, job=self.job.pk,
        )
        # A PO for someone else's job must not be picked up.
        other_job = Job.objects.create(job_number='J-NAV-2', contact=self.contact, description='o')
        other_po = PurchaseOrder.objects.create(business=self.business)
        PurchaseOrderService.add_line_item(
            other_po.pk, description='y', qty=Decimal('1.00'),
            price=Decimal('1.00'), inventory_item=item.pk, job=other_job.pk,
        )
        targets = self._detail()['nav_targets']
        self.assertEqual(targets['po'], po.pk)

    def test_list_context_returns_null_nav_targets(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-NAV-3', version=1,
            status=Estimate.STATUS_OPEN,
        )
        r = self.client.get('/api/jobs/')
        self.assertEqual(r.status_code, 200)
        rows = r.json()['results']
        row = next(j for j in rows if j['job_id'] == self.job.pk)
        self.assertIsNone(row['nav_targets'])
