from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AccountingCategory
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.inventory.models import Material, PriceListItem
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource


class InvoiceLineItemSerializerSourcesTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Labor', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )

    def test_get_line_items_includes_sources(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/line-items/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIn('sources', data[0])
        self.assertEqual(len(data[0]['sources']), 1)
        source = data[0]['sources'][0]
        self.assertEqual(source['source_type'], 'blep')
        self.assertEqual(source['source_pk'], self.blep.pk)
        self.assertIn('description', source)
        self.assertIn('computed_amount', source)


class SourcePoolEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_returns_tree_shape(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('work_orders', data)
        self.assertEqual(len(data['work_orders']), 1)
        wo = data['work_orders'][0]
        self.assertIn('tasks', wo)
        self.assertEqual(len(wo['tasks']), 1)
        task = wo['tasks'][0]
        self.assertEqual(task['name'], 'Labor')
        self.assertTrue(task['has_billable_atoms'])
        self.assertEqual(len(task['atoms']), 1)
        atom = task['atoms'][0]
        self.assertEqual(atom['atom_type'], 'blep')
        self.assertEqual(atom['state'], 'available')

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 403)

    def test_requires_can_manage_financials(self):
        user2 = User.objects.create_user(username='noperm', password='pw')
        client2 = APIClient()
        client2.login(username='noperm', password='pw')
        response = client2.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 403)
