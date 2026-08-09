"""Tests for Task 3.3 of the job-owns-atoms refactor.

Verifies:
1. seed_all_atoms creates one line per Fee (in addition to Tasks and Materials).
2. The claim guard (InvoiceLineItemSource unique_together) blocks double-billing
   a Fee on a second invoice.
3. copy_from_estimate maps an accepted-estimate hand-line to its crystallized
   Fee so the Fee is claimed and cannot be double-billed via the wizard.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import InventoryItem, Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceService, InvoiceWizardService, ClaimConflict
from apps.jobs.models import Blep, Fee, Job, RateScheme, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_common(*, tag):
    """Create shared Configuration + AppState rows, return a (contact, cat) tuple."""
    Configuration.objects.create(
        key='invoice_number_sequence', value=f'INV-{tag}' + '-{counter:04d}',
    )
    AppState.objects.create(key='invoice_counter', value='0')
    cat = AccountingCategory.objects.create(name=f'Cat-{tag}', code=tag, is_active=True)
    contact = Contact.objects.create(
        first_name='T', last_name='T', email=f'{tag}@test.com',
    )
    return contact, cat


# ---------------------------------------------------------------------------
# Goal 1: seed_all_atoms seeds Tasks + Materials + Fees together
# ---------------------------------------------------------------------------

class SeedAllAtomsIncludesFeesTest(TestCase):
    """seed_all_atoms creates exactly one line per available atom (Task, Material, Fee)."""

    def setUp(self):
        self.contact, self.cat = _make_common(tag='SAF')
        self.mat_cat = AccountingCategory.objects.create(name='Mat-SAF', code='SAEM', is_active=True)
        self.fee_cat = AccountingCategory.objects.create(name='Fee-SAF', code='SAEF', is_active=True)
        self.user = User.objects.create_user(username='saf_user', password='pw')

        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-SAF-01',
        )

        # --- Task atom (needs to be COMPLETE to be billable) ---
        self.scheme = RateScheme.objects.create(
            name='Hourly-SAF', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='SAF Labor')
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        start = timezone.now() - timezone.timedelta(hours=2)
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=start,
            end_time=start + timezone.timedelta(hours=2),
        )
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()

        # --- Material atom (needs CONSUMED consumption_state to be billable) ---
        self.pli = InventoryItem.objects.create(
            code='WOOD-SAF', description='Plywood',
            selling_price=Decimal('30.00'), accounting_category=self.mat_cat,
        )
        self.material = Material.objects.create(
            job=self.job, task=self.task, description='Plywood',
            quantity=Decimal('2'), sell_price=Decimal('30.00'),
            inventory_item=self.pli, accounting_category=self.mat_cat,
        )
        self.material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        self.material.save(update_fields=['consumption_state'])

        # --- Fee atom (always billable — no completion gate) ---
        self.fee = Fee.objects.create(
            job=self.job, description='Delivery charge',
            quantity=Decimal('3'), unit_rate=Decimal('10.00'),
            accounting_category=self.fee_cat,
        )  # compute_amount() = 3 × 10 = 30.00

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_seed_creates_one_line_per_atom_type(self):
        """seed_all_atoms returns 3: 1 task + 1 material + 1 fee."""
        count = InvoiceWizardService.seed_all_atoms(self.invoice)
        self.assertEqual(count, 3)

    def test_invoice_has_three_line_items(self):
        InvoiceWizardService.seed_all_atoms(self.invoice)
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 3,
        )

    def test_fee_source_record_is_created(self):
        """An InvoiceLineItemSource of type 'fee' is created for the Fee atom."""
        InvoiceWizardService.seed_all_atoms(self.invoice)
        self.assertTrue(
            InvoiceLineItemSource.objects.filter(
                source_type=InvoiceLineItemSource.SOURCE_FEE,
                source_pk=self.fee.pk,
            ).exists()
        )

    def test_fee_line_item_has_correct_price(self):
        """The fee line item copies over quantity × unit_rate from the Fee."""
        InvoiceWizardService.seed_all_atoms(self.invoice)
        src = InvoiceLineItemSource.objects.get(
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        li = src.invoice_line_item
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('10.00'))

    def test_incomplete_task_not_seeded(self):
        """A pending task produces a 'not_billable' atom — seed skips it."""
        # Add a second incomplete task
        pending_task = Task(
            job=self.job, name='Pending',
        )
        pending_task.stamp_from_scheme(self.scheme)
        pending_task.save()  # status = pending by default

        count = InvoiceWizardService.seed_all_atoms(self.invoice)
        # Still 3: the pending task is not_billable and is skipped
        self.assertEqual(count, 3)
        # No source row for the pending task
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(
                source_type=InvoiceLineItemSource.SOURCE_TASK,
                source_pk=pending_task.pk,
            ).exists()
        )

    def test_fee_shows_in_source_pool(self):
        """Before seeding, the fee atom appears in the source pool as 'available'."""
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        fee_group = next((g for g in pool['tasks'] if g['name'] == 'Fees'), None)
        self.assertIsNotNone(fee_group)
        self.assertEqual(len(fee_group['atoms']), 1)
        self.assertEqual(fee_group['atoms'][0]['state'], 'available')
        self.assertEqual(fee_group['atoms'][0]['amount'], Decimal('30.00'))


# ---------------------------------------------------------------------------
# Goal 2: claim guard blocks double-billing a Fee on a second invoice
# ---------------------------------------------------------------------------

class FeeClaimGuardTest(TestCase):
    """The unique_together guard on InvoiceLineItemSource prevents double-billing."""

    def setUp(self):
        self.contact, self.cat = _make_common(tag='FCG')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-FCG-01',
        )
        self.fee = Fee.objects.create(
            job=self.job, description='Setup fee',
            quantity=Decimal('1'), unit_rate=Decimal('150.00'),
            accounting_category=self.cat,
        )

        # seed_all_atoms on invoice1 (only atom is the Fee → 1 line item)
        self.invoice1 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceWizardService.seed_all_atoms(self.invoice1)

        # Transition invoice1 out of DRAFT so we can create invoice2
        # (Invoice.clean requires a line item to leave DRAFT — that exists after seeding)
        self.invoice1.status = Invoice.STATUS_OPEN
        self.invoice1.save()

        self.invoice2 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_direct_add_fee_raises_claim_conflict(self):
        """add_atoms_to_new_line_item raises ClaimConflict for an already-claimed Fee."""
        atoms = [{'type': 'fee', 'id': self.fee.pk}]
        with self.assertRaises(ClaimConflict) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice2, atoms)
        self.assertIn({'type': 'fee', 'id': self.fee.pk}, ctx.exception.atom_ids)

    def test_seed_on_second_invoice_skips_claimed_fee(self):
        """seed_all_atoms returns 0 when every available atom is already claimed."""
        count = InvoiceWizardService.seed_all_atoms(self.invoice2)
        self.assertEqual(count, 0)

    def test_fee_shows_as_claimed_by_other_on_second_invoice(self):
        """get_source_pool marks the Fee as 'claimed_by_other' for the second invoice."""
        pool = InvoiceWizardService.get_source_pool(self.invoice2)
        fee_group = next(g for g in pool['tasks'] if g['name'] == 'Fees')
        atom = fee_group['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_other')
        self.assertEqual(atom['claiming_invoice_id'], self.invoice1.pk)

    def test_cancelled_invoice_releases_fee(self):
        """Cancelling invoice1 makes the Fee available again for invoice2."""
        self.invoice1.status = Invoice.STATUS_CANCELLED
        self.invoice1.save()
        pool = InvoiceWizardService.get_source_pool(self.invoice2)
        fee_group = next(g for g in pool['tasks'] if g['name'] == 'Fees')
        self.assertEqual(fee_group['atoms'][0]['state'], 'available')


# ---------------------------------------------------------------------------
# Goal 3: copy_from_estimate claims the crystallized Fee
# ---------------------------------------------------------------------------

class CopyFromEstimateClaimsFeeTest(TestCase):
    """copy_from_estimate creates an InvoiceLineItemSource for any fee-sourced
    estimate line so the Fee cannot be double-billed via the wizard after a copy.

    Estimate acceptance no longer crystallizes plain hand-lines into Fees, so
    the Fee and its EstimateLineItemSource are seeded directly here (mirroring
    historical / CO-acceptance-created data, which still produces SOURCE_FEE rows).
    """

    def setUp(self):
        self.contact, self.cat = _make_common(tag='CFEF')

        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-CFEF-01',
        )

        # An accepted estimate with one hand-line (no atom source, not an adjustment).
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-CFEF-01', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1,
            description='Custom fabrication fee',
            qty=Decimal('2'), price=Decimal('75.00'),
            units='ea', accounting_category=self.cat,
        )
        # Seed the crystallized Fee and its source row directly (acceptance no
        # longer creates them from plain lines).
        self.fee = Fee.objects.create(
            job=self.job, description='Custom fabrication fee',
            quantity=Decimal('2'), unit_rate=Decimal('75.00'),
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.hand_line,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_fee_is_available_before_copy(self):
        """Baseline: before copy_from_estimate, the Fee is available in the wizard pool."""
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        fee_group = next(g for g in pool['tasks'] if g['name'] == 'Fees')
        self.assertEqual(fee_group['atoms'][0]['state'], 'available')

    def test_copy_creates_invoice_line_for_hand_line(self):
        """copy_from_estimate creates an InvoiceLineItem for the hand-line."""
        created = InvoiceService.copy_from_estimate(self.invoice)
        self.assertEqual(created, 1)  # one line (hand-line only, no adjustment)
        lines = list(InvoiceLineItem.objects.filter(invoice=self.invoice))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].description, 'Custom fabrication fee')

    def test_copy_creates_invoice_line_item_source_for_fee(self):
        """copy_from_estimate creates an InvoiceLineItemSource(type='fee') so
        the Fee is claimed and cannot be double-billed via the wizard."""
        InvoiceService.copy_from_estimate(self.invoice)
        self.assertTrue(
            InvoiceLineItemSource.objects.filter(
                source_type=InvoiceLineItemSource.SOURCE_FEE,
                source_pk=self.fee.pk,
            ).exists()
        )

    def test_fee_shows_as_claimed_by_current_after_copy(self):
        """After copy_from_estimate, the Fee is marked 'claimed_by_current' in
        the wizard pool — the wizard cannot offer it again on the same invoice."""
        InvoiceService.copy_from_estimate(self.invoice)
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        fee_group = next(g for g in pool['tasks'] if g['name'] == 'Fees')
        atom = fee_group['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_current')

    def test_fee_is_not_double_billed_via_wizard_after_copy(self):
        """After copy_from_estimate, adding the Fee atom via the wizard raises
        ClaimConflict — double-billing is blocked at the DB level."""
        InvoiceService.copy_from_estimate(self.invoice)
        atoms = [{'type': 'fee', 'id': self.fee.pk}]
        with self.assertRaises(ClaimConflict):
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)

    def test_adjustment_line_is_not_a_fee_and_has_no_source(self):
        """Adjustment lines in the estimate never become Fees and copy_from_estimate
        must not try to create a fee source for them."""
        # Add an adjustment line to the estimate.
        rush_svc = RateScheme.objects.create(
            name='Rush-CFEF', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2,
            description='Rush 10%', qty=Decimal('1'), price=Decimal('15.00'),
            units='%', adjustment_service=rush_svc,
            adjustment_percent=rush_svc.rate,
        )
        InvoiceService.copy_from_estimate(self.invoice)
        # Only 1 InvoiceLineItemSource of type 'fee' should exist
        fee_sources = InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_FEE,
        )
        self.assertEqual(fee_sources.count(), 1)
        self.assertEqual(fee_sources.first().source_pk, self.fee.pk)
