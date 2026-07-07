"""
Tests for the "Apply everything" invoice seeding action.

POST /api/invoices/{id}/apply-everything/ seeds all available atoms onto the
invoice, one line per atom. Already-claimed and not-billable atoms are skipped.
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AppState, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceWizardService


def _make_numbering():
    """Create the invoice numbering rows needed for Invoice creation."""
    Configuration.objects.get_or_create(
        key='invoice_number_sequence',
        defaults={'value': 'INV-{year}-{counter:04d}'},
    )
    AppState.objects.get_or_create(key='invoice_counter', defaults={'value': '0'})


class ApplyEverythingServiceTest(TestCase):
    """Low-level service tests for seed_all_atoms."""

    def setUp(self):
        _make_numbering()

        self.cat = AccountingCategory.objects.create(
            code='LAB-AE', name='Labor-AE', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='App', last_name='Ly', email='apply@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_WORK_COMPLETE,
            job_number='JOB-AE-0001',
        )

        # A completed task with a rate scheme
        self.rs = RateScheme.objects.create(
            name='Flat-AE', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100.00'), unit_label='ea',
            accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Task A', status=Task.STATUS_COMPLETE,
            rate_scheme=self.rs, sort_order=1,
        )

        # A consumed material attached to the task
        self.mat = Material.objects.create(
            job=self.job, task=self.task,
            description='Widget', quantity=Decimal('2'),
            sell_price=Decimal('10.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )

        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

    def test_seed_all_atoms_creates_one_line_per_available_atom(self):
        """A completed task + consumed material → two lines created."""
        count = InvoiceWizardService.seed_all_atoms(self.invoice)
        self.assertEqual(count, 2)
        self.assertEqual(InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 2)

    def test_seed_all_atoms_atoms_become_claimed_by_current(self):
        """After seeding, both atoms show as claimed_by_current in source pool."""
        InvoiceWizardService.seed_all_atoms(self.invoice)
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        atoms = []
        for group in pool['tasks']:
            atoms.extend(group['atoms'])
        for atom in atoms:
            self.assertEqual(
                atom['state'], 'claimed_by_current',
                f"Expected claimed_by_current for atom type={atom.get('type')} id={atom.get('id')}, got {atom['state']}"
            )

    def test_seed_all_atoms_raises_if_invoice_already_has_lines(self):
        """seed_all_atoms raises ValidationError if the invoice already has lines."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='ea', description='Existing', price=Decimal('50.00'),
        )
        with self.assertRaises(DjangoValidationError):
            InvoiceWizardService.seed_all_atoms(self.invoice)

    def test_seed_all_atoms_raises_if_invoice_not_draft(self):
        """seed_all_atoms raises ValidationError if the invoice is not draft."""
        # Bypass Invoice.save() validation (which blocks status change from draft
        # without a line item) since we only need to test seed_all_atoms rejects non-draft.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)
        self.invoice.refresh_from_db()
        with self.assertRaises(DjangoValidationError):
            InvoiceWizardService.seed_all_atoms(self.invoice)

    def test_seed_all_atoms_skips_not_billable_atoms(self):
        """An incomplete task and unconsumed material are skipped (not_billable)."""
        # Add an incomplete task
        Task.objects.create(
            job=self.job, name='Incomplete Task', status=Task.STATUS_PENDING,
            rate_scheme=self.rs, sort_order=2,
        )
        # Add an unconsumed material (pending = not yet consumed)
        Material.objects.create(
            job=self.job, task=self.task,
            description='Unconsumed Widget', quantity=Decimal('1'),
            sell_price=Decimal('5.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_PENDING,
        )
        # Should still only create 2 lines (the original complete task + consumed mat)
        count = InvoiceWizardService.seed_all_atoms(self.invoice)
        self.assertEqual(count, 2)

    def test_second_invoice_seeds_only_unclaimed_atoms(self):
        """A second draft invoice gets only atoms not yet claimed by the first."""
        # Seed the first invoice (claims both atoms)
        InvoiceWizardService.seed_all_atoms(self.invoice)

        # Add a new consumed material (not yet claimed)
        new_mat = Material.objects.create(
            job=self.job, task=self.task,
            description='New Widget', quantity=Decimal('3'),
            sell_price=Decimal('15.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )

        # Transition the first invoice to open (bypass save() validation)
        # so we can create a new draft for the same job.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)

        # Create a second draft invoice
        second_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

        count = InvoiceWizardService.seed_all_atoms(second_invoice)
        # Only the new material should be seeded (task + old mat already claimed)
        self.assertEqual(count, 1)
        line = InvoiceLineItem.objects.get(invoice=second_invoice)
        src = InvoiceLineItemSource.objects.get(invoice_line_item=line)
        self.assertEqual(src.source_type, InvoiceLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, new_mat.pk)


class ApplyEverythingAPITest(TestCase):
    """API-level tests for POST /api/invoices/{id}/apply-everything/."""

    def setUp(self):
        _make_numbering()

        self.cat = AccountingCategory.objects.create(
            code='LAB-API', name='Labor-API', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Api', last_name='Test', email='apitest@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_WORK_COMPLETE,
            job_number='JOB-API-0001',
        )

        self.rs = RateScheme.objects.create(
            name='Flat-API', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('200.00'), unit_label='ea',
            accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Task B', status=Task.STATUS_COMPLETE,
            rate_scheme=self.rs, sort_order=1,
        )
        self.mat = Material.objects.create(
            job=self.job, task=self.task,
            description='Bolt', quantity=Decimal('5'),
            sell_price=Decimal('3.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )

        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

        self.user = User.objects.create_user(username='fin-ae', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _url(self, invoice=None):
        inv = invoice or self.invoice
        return f'/api/invoices/{inv.pk}/apply-everything/'

    def test_apply_everything_returns_200_with_created_count(self):
        """Successful apply-everything returns 200 with created count."""
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('created', resp.data)
        self.assertEqual(resp.data['created'], 2)

    def test_apply_everything_creates_lines_in_db(self):
        """Lines are actually persisted."""
        self.client.post(self._url())
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 2
        )

    def test_apply_everything_returns_400_if_invoice_has_lines(self):
        """Returns 400 when the invoice already has a line item."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='ea', description='Pre-existing', price=Decimal('10.00'),
        )
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)

    def test_apply_everything_second_invoice_skips_claimed_atoms(self):
        """A second invoice gets only atoms unclaimed by the first invoice."""
        # Seed first invoice
        self.client.post(self._url())

        # Add a new unclaimed material
        new_mat = Material.objects.create(
            job=self.job, task=self.task,
            description='New Bolt', quantity=Decimal('1'),
            sell_price=Decimal('8.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )

        # Transition first invoice out of draft (bypass save() validation) so
        # we can create a second draft for the same job.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)

        # Create second invoice
        second_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )
        resp = self.client.post(self._url(second_invoice))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 1)

        line = InvoiceLineItem.objects.get(invoice=second_invoice)
        src = InvoiceLineItemSource.objects.get(invoice_line_item=line)
        self.assertEqual(src.source_pk, new_mat.pk)

    def test_apply_everything_skips_not_billable_atoms(self):
        """Incomplete task and unconsumed material are not billed."""
        # Add non-billable atoms
        Task.objects.create(
            job=self.job, name='Pending Task', status=Task.STATUS_PENDING,
            rate_scheme=self.rs, sort_order=2,
        )
        Material.objects.create(
            job=self.job, task=self.task,
            description='Uncons Bolt', quantity=Decimal('1'),
            sell_price=Decimal('2.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_PENDING,
        )
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 200, resp.data)
        # Still only the original complete task + consumed mat
        self.assertEqual(resp.data['created'], 2)

    def test_apply_everything_requires_can_manage_financials(self):
        """Non-financial user gets 403."""
        plain_user = User.objects.create_user(username='plain-ae', password='pw')
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.post(self._url())
        self.assertEqual(resp.status_code, 403)
