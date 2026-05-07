from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
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
        self.task = Task.objects.create(job=self.job, name='Build-pta', rate_scheme=self.scheme)
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

class WizardTaskAtomHelpersTest(WizardPerTaskAtomsTest):
    def test_resolve_task_atom(self):
        from apps.invoicing.services import InvoiceWizardService
        atom = InvoiceWizardService._resolve_atom({'type': 'task', 'id': self.task.pk})
        self.assertEqual(atom, self.task)

    def test_task_atom_computed_amount_uses_charge(self):
        from apps.invoicing.services import InvoiceWizardService
        amount = InvoiceWizardService._atom_computed_amount(self.task)
        self.assertEqual(amount, Decimal('30.00'))

    def test_task_atom_category_walks_through_charge_scheme(self):
        from apps.invoicing.services import InvoiceWizardService
        cat = InvoiceWizardService._atom_category(self.task)
        self.assertEqual(cat, self.ac)

    def test_task_atom_source_type_returns_source_task(self):
        from apps.invoicing.services import InvoiceWizardService
        from apps.invoicing.models import InvoiceLineItemSource
        st = InvoiceWizardService._atom_source_type(self.task)
        self.assertEqual(st, InvoiceLineItemSource.SOURCE_TASK)


class WizardReadsTaskDirectlyTest(TestCase):
    """Phase B: wizard atom rendering uses task.compute_amount and
    task.rate_scheme, not task.charge.*."""

    def setUp(self):
        from apps.core.models import AccountingCategory, Configuration
        from apps.jobs.models import RateScheme, Job, Task
        from apps.invoicing.models import Invoice
        from apps.contacts.models import Contact, Business

        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')

        ac = AccountingCategory.objects.create(name='Labor')
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Z', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-WIZ', contact=contact, status=Job.STATUS_APPROVED,
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5.00'), unit_label='piece',
            accounting_category=ac,
        )
        self.task = Task.objects.create(
            job=self.job, name='Polish',
            rate_scheme=self.scheme, active_modifiers=[],
            est_qty=Decimal('12'), actual_qty=Decimal('12'),
        )
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

    def test_source_pool_reads_task_directly(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        # Find our task in the tree
        task_entry = next(
            t for t in pool['tasks']
            if t['task_id'] == self.task.pk
        )
        self.assertEqual(len(task_entry['atoms']), 1)
        atom = task_entry['atoms'][0]
        self.assertEqual(atom['atom_type'], 'task')
        self.assertEqual(atom['atom_id'], self.task.pk)
        self.assertEqual(atom['computed_amount'], Decimal('60.00'))
        self.assertIn('Polish', atom['description'])
        self.assertIn('Hourly', atom['description'])  # scheme name in label
        self.assertIn('12', atom['sub_info'])  # qty source label
