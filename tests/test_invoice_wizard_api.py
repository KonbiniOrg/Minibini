from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AccountingCategory
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, Blep, RateScheme, TaskCharge
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-ils', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        start = timezone.now() - timezone.timedelta(hours=2)
        Blep.objects.create(
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
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

    def test_get_line_items_includes_sources(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/line-items/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIn('sources', data[0])
        self.assertEqual(len(data[0]['sources']), 1)
        source = data[0]['sources'][0]
        self.assertEqual(source['source_type'], 'task')
        self.assertEqual(source['source_pk'], self.task.pk)
        self.assertIn('description', source)
        self.assertIn('computed_amount', source)

    def test_task_source_renders_task_name_as_description(self):
        """A Task-typed source should render the task's name (not its blank
        long-form description) so the wizard line item card shows something
        between the arrow and the X."""
        # setUp already claims self.task; create a second task for this test.
        other_task = Task.objects.create(job=self.job, name='Cleanup', rate_scheme=self.scheme)
        TaskCharge.objects.create(task=other_task, rate_scheme=self.scheme)
        task_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='', qty=Decimal('1'), price=Decimal('0.00'),
            line_number=2,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=task_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=other_task.pk,
        )
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/line-items/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        task_li_data = next(li for li in data if li['line_item_id'] == task_li.pk)
        self.assertEqual(len(task_li_data['sources']), 1)
        self.assertEqual(task_li_data['sources'][0]['description'], 'Cleanup')


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
        self.scheme = RateScheme.objects.create(
            name='Hourly-spe', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_returns_tree_shape(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('tasks', data)
        # tasks list includes task groups + the "Materials (no task)" sentinel group
        task = next(t for t in data['tasks'] if t['name'] == 'Labor')
        self.assertTrue(task['has_billable_atoms'])
        self.assertEqual(len(task['atoms']), 1)
        atom = task['atoms'][0]
        # Per-task atom computed via task.compute_amount() (post-B5)
        self.assertEqual(atom['atom_type'], 'task')
        self.assertEqual(atom['atom_id'], self.task.pk)
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


class LineItemsFromAtomsEndpointTest(TestCase):
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-lifa', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_creates_line_item_with_sources(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        # Single task-atom copy-over: qty=1, price=total ($50), units track scheme.
        self.assertEqual(data['qty'], '1.00')
        self.assertEqual(data['price'], '50.00')
        self.assertEqual(len(data['sources']), 1)

    def test_returns_409_on_claim_conflict(self):
        # Pre-claim the task atom
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Prior', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data['error'], 'atoms_already_claimed')
        self.assertIn({'type': 'task', 'id': self.task.pk}, data['atom_ids'])

    def test_returns_400_on_non_draft_invoice(self):
        # Need a line item to transition out of draft
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Item', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.category,
        )
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class AddAtomsEndpointTest(TestCase):
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-aae', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        # task1 with a 2h blep — task atom = $50
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        start = timezone.now() - timezone.timedelta(hours=4)
        Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        # task2 with a 1h blep — task atom = $25
        self.task2 = Task.objects.create(
            job=self.job, name='Cleanup', rate_scheme=self.scheme,
        )
        TaskCharge.objects.create(task=self.task2, rate_scheme=self.scheme)
        Blep.objects.create(
            task=self.task2,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        from apps.invoicing.services import InvoiceWizardService
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': self.task.pk}],
        )

    def test_adds_atoms_and_returns_updated_line_item(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/add-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task2.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['sources']), 2)
        # Single task-atom copy-over set qty=1, price=$50. Adding task2 atom
        # keeps qty=1 and recomputes per-unit price: ($50 + $25) / 1 = $75.00.
        self.assertEqual(data['price'], '75.00')

    def test_returns_409_on_claim_conflict(self):
        # Claim task2 on a different line item first
        other_li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Other', qty=Decimal('1'),
            price=Decimal('25.00'), accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task2.pk,
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/add-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task2.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 409)


class RemoveAtomsEndpointTest(TestCase):
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-rae', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        # task1 with a 2h blep — task atom = $50
        self.task1 = Task.objects.create(job=self.job, name='Labor 1', rate_scheme=self.scheme)
        TaskCharge.objects.create(task=self.task1, rate_scheme=self.scheme)
        start = timezone.now() - timezone.timedelta(hours=4)
        Blep.objects.create(
            task=self.task1, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        # task2 with a 1h blep — task atom = $25
        self.task2 = Task.objects.create(job=self.job, name='Labor 2', rate_scheme=self.scheme)
        TaskCharge.objects.create(task=self.task2, rate_scheme=self.scheme)
        Blep.objects.create(
            task=self.task2,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        from apps.invoicing.services import InvoiceWizardService
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [
                {'type': 'task', 'id': self.task1.pk},
                {'type': 'task', 'id': self.task2.pk},
            ],
        )

    def test_removes_partial_sources(self):
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)
            .values_list('source_id', flat=True)
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/remove-atoms/',
            {'source_ids': source_ids},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['line_item_deleted'])
        self.assertEqual(data['line_item']['price'], '25.00')  # blep2 remains
        self.assertEqual(len(data['line_item']['sources']), 1)

    def test_deletes_line_item_when_all_removed(self):
        source_ids = list(self.line_item.sources.values_list('source_id', flat=True))
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/remove-atoms/',
            {'source_ids': source_ids},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['line_item_deleted'])
        self.assertIsNone(data.get('line_item'))


class StartInvoiceWizardEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

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

        self.approved_job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.draft_job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002')

    def test_creates_draft_and_returns_id(self):
        response = self.client.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('invoice_id', data)
        invoice = Invoice.objects.get(pk=data['invoice_id'])
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.approved_job)

    def test_returns_existing_draft(self):
        Invoice.objects.create(job=self.approved_job, status=Invoice.STATUS_DRAFT)
        response = self.client.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.filter(job=self.approved_job).count(), 1)

    def test_refuses_pre_approval_job(self):
        response = self.client.post(
            f'/api/jobs/{self.draft_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_financials(self):
        user2 = User.objects.create_user(username='noperm', password='pw')
        client2 = APIClient()
        client2.login(username='noperm', password='pw')
        response = client2.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 403)

    def test_can_manage_jobs_user_can_start_wizard(self):
        # Either can_manage_jobs OR can_manage_financials grants access
        user3 = User.objects.create_user(username='jobsonly', password='pw')
        user3.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs')
        )
        client3 = APIClient()
        client3.login(username='jobsonly', password='pw')
        response = client3.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 200)
