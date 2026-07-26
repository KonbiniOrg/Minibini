from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import ServiceItem
from apps.invoicing.models import Invoice
from apps.jobs.models import Job, RateScheme, Task


class InvoiceLineFromServiceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.login(username='fin', password='pw')
        self.cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        self.scheme = RateScheme.objects.create(
            name='CNC-hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('90.00'), unit_label='hours',
            accounting_category=self.cat)
        self.svc = ServiceItem.objects.create(
            template_name='CNC Routing', rate_scheme=self.scheme)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        job = Job.objects.create(contact=contact,
                                 job_number='JOB-2026-0001',
                                 status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=job, status=Invoice.STATUS_DRAFT)

    def test_creates_priced_line_no_task(self):
        before = Task.objects.count()
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': self.svc.pk, 'qty': '3'}, format='json')
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['description'], 'CNC Routing')
        self.assertEqual(Decimal(data['qty']), Decimal('3'))
        # No default_active_modifiers on self.svc, so effective_rate == rate.
        self.assertEqual(Decimal(data['price']), Decimal('90.00'))
        self.assertEqual(data['accounting_category'], self.cat.pk)
        self.assertEqual(Task.objects.count(), before)  # no job side effects
        self.assertEqual(data['sources'], [])

    def test_price_uses_effective_rate_with_modifiers(self):
        """Parity with the estimate mirror: price must snapshot
        scheme.effective_rate(service_item.default_active_modifiers), not
        the bare scheme.rate — a pre-checked modifier must be folded in."""
        modifier_scheme = RateScheme.objects.create(
            name='CNC-hourly-messy', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('90.00'), unit_label='hours',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
            accounting_category=self.cat)
        modifier_svc = ServiceItem.objects.create(
            template_name='CNC Routing (messy)', rate_scheme=modifier_scheme,
            default_active_modifiers=['messy'])
        expected_price = modifier_scheme.effective_rate(['messy'])
        self.assertNotEqual(expected_price, modifier_scheme.rate)

        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': modifier_svc.pk, 'qty': '1'}, format='json')
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(Decimal(data['price']), expected_price)
        self.assertNotEqual(Decimal(data['price']), modifier_scheme.rate)

    def test_unknown_service_404(self):
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': 999999, 'qty': '1'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_non_draft_rejected(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.STATUS_OPEN)
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': self.svc.pk, 'qty': '1'}, format='json')
        self.assertEqual(resp.status_code, 400)
