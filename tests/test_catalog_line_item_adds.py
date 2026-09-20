from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AccountingCategory, AppState
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.inventory.models import InventoryItem


class CatalogLineItemAddTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.category = AccountingCategory.objects.create(code='MAT', name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_superuser(username='boss', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.pli = InventoryItem.objects.create(
            code='WIDGET-1', description='Standard widget', units='ea',
            selling_price=Decimal('42.50'), accounting_category=self.category,
        )

    def test_estimate_catalog_add_copies_pli_fields(self):
        # Add Line Item is back: a catalog/PLI add on a draft estimate copies PLI fields.
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )
        resp = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'inventory_item': self.pli.pk, 'qty': '3'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['inventory_item'], self.pli.pk)
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))

    def test_invoice_catalog_add_copies_pli_fields(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        resp = self.client.post(
            f'/api/invoices/{inv.pk}/line-items/',
            {'inventory_item': self.pli.pk, 'qty': '2'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['inventory_item'], self.pli.pk)
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))

    def test_estimate_catalog_add_with_description_override_is_honored(self):
        # Add Line modal editable-description feature (2026-09-20): an
        # explicit, non-blank description on the inventory-item line POST
        # wins over the PLI-derived one; price/units/AC stay PLI-derived.
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0002', status=Estimate.STATUS_DRAFT,
        )
        resp = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'inventory_item': self.pli.pk, 'qty': '3',
             'description': 'Widget, gift-wrapped'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['description'], 'Widget, gift-wrapped')
        self.assertEqual(resp.data['inventory_item'], self.pli.pk)
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))

    def test_estimate_catalog_add_without_description_derives_as_today(self):
        # Regression pin, explicit per the brief's test list (item 5).
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0003', status=Estimate.STATUS_DRAFT,
        )
        resp = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'inventory_item': self.pli.pk, 'qty': '1'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['description'], 'Standard widget')
