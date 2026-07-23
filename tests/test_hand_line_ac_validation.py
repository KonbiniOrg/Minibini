"""
TDD tests for the accounting-category requirement on estimate hand-lines.

Hand-lines (no source atom, not an adjustment) MUST have an accounting_category.
Atom-backed lines and adjustment lines are exempt.
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.estimates.services import EstimateService
from apps.jobs.models import Fee, Job, RateScheme, Task


class HandLineACValidationSetup(TestCase):
    """Shared setUp for hand-line AC validation tests."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='jd@test.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Setup', rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_DRAFT,
        )

        # Hand-line with accounting category (the valid baseline)
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush handling',
            qty=Decimal('3'), price=Decimal('25.00'), accounting_category=self.cat,
        )

        # Atom-backed line (sources exist — exempt from AC requirement)
        self.atom_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Setup labor',
            qty=Decimal('2'), price=Decimal('200.00'),
            # accounting_category intentionally left None to confirm exemption
            accounting_category=None,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.atom_line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

        # Adjustment line (adjustment_service set — exempt from AC requirement)
        self.adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        self.adj_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=None,  # also None to confirm adjustment exemption
            adjustment_service=self.adj_scheme,
        )


class UpdateHandLineACValidationTest(HandLineACValidationSetup):
    """EstimateService.update_line_item() must enforce the AC requirement."""

    def test_clearing_ac_on_hand_line_raises_validation_error(self):
        """Removing accounting_category from a hand-line raises ValidationError (not 500)."""
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(
                self.hand_line.pk,
                accounting_category=None,
            )
        msg = str(ctx.exception)
        self.assertIn('accounting', msg.lower())

    def test_updating_hand_line_with_ac_succeeds(self):
        """A hand-line with a valid accounting_category can be updated without error."""
        updated = EstimateService.update_line_item(
            self.hand_line.pk,
            description='Rush handling updated',
            accounting_category=self.cat.pk,
        )
        self.assertEqual(updated.description, 'Rush handling updated')
        self.assertEqual(updated.accounting_category, self.cat)

    def test_atom_backed_line_without_ac_is_exempt(self):
        """Atom-backed lines (sources exist) are exempt from the AC requirement."""
        # atom_line already has accounting_category=None; confirm update also allows it
        updated = EstimateService.update_line_item(
            self.atom_line.pk,
            description='Updated setup',
        )
        self.assertEqual(updated.description, 'Updated setup')
        self.assertIsNone(updated.accounting_category)

    def test_adjustment_line_without_ac_is_exempt(self):
        """Adjustment lines (adjustment_service set) are exempt from the AC requirement."""
        updated = EstimateService.update_line_item(
            self.adj_line.pk,
            description='Updated adjustment',
        )
        self.assertEqual(updated.description, 'Updated adjustment')
        self.assertIsNone(updated.accounting_category)

    def test_updating_hand_line_keeping_existing_ac_succeeds(self):
        """Updating other fields on a hand-line that already has AC succeeds."""
        updated = EstimateService.update_line_item(
            self.hand_line.pk,
            qty=Decimal('5'),
        )
        self.assertEqual(updated.qty, Decimal('5'))
        self.assertEqual(updated.accounting_category, self.cat)


class EstimateSendACGuardTest(HandLineACValidationSetup):
    """Sending an estimate (mark_open) is blocked while any hand-line lacks an
    accounting category — the AC-required rule is hoisted from acceptance to send."""

    def _add_deliverable(self):
        from apps.deliverables.models import Deliverable
        Deliverable.objects.create(
            job=self.job, description='Sign', qty_ordered=Decimal('1'), units='ea',
        )

    def test_mark_open_blocked_when_hand_line_missing_ac(self):
        self._add_deliverable()
        # Plant a hand-line with no AC (bypass the service's own create validation).
        EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.mark_open(self.estimate.pk)
        self.assertIn('accounting', str(ctx.exception).lower())
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_DRAFT)  # not opened

    def test_mark_open_succeeds_when_all_hand_lines_have_ac(self):
        # Baseline: hand_line has AC; the null-AC atom_line and adj_line are exempt,
        # so they must NOT block the send.
        self._add_deliverable()
        result = EstimateService.mark_open(self.estimate.pk)
        self.assertEqual(result.status, Estimate.STATUS_OPEN)


class AcceptanceDefensiveGuardTest(HandLineACValidationSetup):
    """EstimateAcceptanceService.on_accept() must raise a clear ValidationError
    (not IntegrityError) when a hand-line has no accounting_category."""

    def setUp(self):
        super().setUp()
        # Create a hand-line with NULL AC via ORM bypass (simulates bad historical data).
        # We skip the service to bypass the new service-level validation.
        self.bad_hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='No-category fee',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=None,  # the problem condition
        )
        # Advance the estimate to open so on_accept can run.
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()

    def test_accept_with_null_ac_hand_line_raises_clear_validation_error(self):
        """on_accept() raises ValidationError (not IntegrityError) for a null-AC hand-line."""
        from django.db import IntegrityError

        # Must raise ValidationError — not IntegrityError — so callers get a
        # meaningful message, not a cryptic DB constraint failure.
        with self.assertRaises(ValidationError) as ctx:
            EstimateAcceptanceService.on_accept(self.estimate)
        msg = str(ctx.exception)
        # Should mention the line or accounting category in a useful way
        self.assertIn('accounting', msg.lower())

    def test_accept_with_ac_hand_line_succeeds(self):
        """on_accept() succeeds when every hand-line has an accounting_category."""
        # The bad_hand_line would fail; give it a category so the test verifies success.
        EstimateLineItem.objects.filter(pk=self.bad_hand_line.pk).update(
            accounting_category=self.cat,
        )
        self.bad_hand_line.refresh_from_db()

        # Also remove atom_line and adj_line's null-AC items from the picture by
        # ensuring they're properly handled (atom-backed + adjustment — both fine).
        result = EstimateAcceptanceService.on_accept(self.estimate)
        # hand_line (cat=self.cat) + bad_hand_line (now cat=self.cat) = 2 fees
        self.assertGreaterEqual(result['fees_created'], 1)
