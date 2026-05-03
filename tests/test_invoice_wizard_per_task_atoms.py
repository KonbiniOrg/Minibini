from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from tests.base import BaseTestCase


class WizardPerTaskAtomsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job, Task, TaskCharge, Blep
        from apps.invoicing.models import Invoice
        from apps.contacts.models import Business, Contact

        self.ac = AccountingCategory.objects.create(code='X-pta', name='X-pta')
        self.scheme = RateScheme.objects.create(
            name='Hourly-pta', algorithm='elapsed_time', rate=Decimal('60'),
            unit_label='hours', accounting_category=self.ac,
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-pta@l.test',
        )
        biz = Business.objects.create(
            business_name='B-pta', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-pta', contact=contact)
        self.task = Task.objects.create(job=self.job, name='Build-pta')
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        # 30 minutes of work = $30 (60/hr × 0.5)
        now = timezone.now()
        Blep.objects.create(
            task=self.task,
            start_time=now - timedelta(minutes=30),
            end_time=now,
        )
        self.invoice = Invoice.objects.create(
            invoice_number='INV-pta', job=self.job,
            status=Invoice.STATUS_DRAFT,
        )

    def test_pool_exposes_one_atom_per_task_with_charge_total(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        task_entries = [t for t in pool['tasks'] if t['task_id'] == self.task.pk]
        self.assertEqual(len(task_entries), 1)
        atoms = task_entries[0]['atoms']
        self.assertEqual(len(atoms), 1)
        atom = atoms[0]
        self.assertEqual(atom['atom_type'], 'task')
        self.assertEqual(atom['atom_id'], self.task.pk)
        self.assertEqual(atom['computed_amount'], Decimal('30.00'))

    def test_blep_visible_as_read_only_detail(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        task_entries = [t for t in pool['tasks'] if t['task_id'] == self.task.pk]
        self.assertIn('bleps', task_entries[0])
        self.assertEqual(len(task_entries[0]['bleps']), 1)
