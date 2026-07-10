"""
Tests for the job-overview redesign (phase 2).

Task 1 covers `spend_breakdown(job)` in `apps/jobs/financials.py` — the
labor/materials split of the same figure `compute_job_financials(job)['spent']`
reports, built so the two can never drift apart (`_spent` is refactored to
return `spend_breakdown(job)['total']`).

Task 2 will extend this module with the overview aggregate endpoint tests.

Fixed dates throughout — no wall-clock-relative test data (see the
midnight-flake lesson in docs/designs).
"""
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from tests.base import FixtureTestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.expenses.models import Expense
from apps.inventory.models import Material
from apps.jobs.models import Blep, Job, RateScheme, Task


def _job(contact):
    return Job.objects.create(
        job_number=f'JOB-OV-{Job.objects.count() + 1:04d}',
        name='Overview Test Job', status=Job.STATUS_IN_PROGRESS, contact=contact,
    )


def _aware(y, m, d, hh=9, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


class SpendBreakdownTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='ov-spend', password='x')
        self.cat = AccountingCategory.objects.create(code='OV-S', name='ov-s')
        self.job = _job(self.contact)

    def _blep(self, hours):
        scheme = RateScheme.objects.create(
            name=f'Hr-ov-{hours}', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hours', accounting_category=self.cat)
        task = Task.objects.create(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS,
            rate_scheme=scheme)
        start = _aware(2026, 1, 15, 9, 0)
        end = _aware(2026, 1, 15, 9 + int(hours), 0)
        return Blep.objects.create(
            task=task, user=self.user, start_time=start, end_time=end)

    def _expense(self, amount, material=None):
        return Expense.objects.create(
            entered_by=self.user, amount=Decimal(str(amount)),
            purchased_on=_aware(2026, 1, 15).date(),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC',
            job=self.job, material=material,
        )

    def _material(self, qty, cost, state=Material.CONSUMPTION_STATE_CONSUMED):
        return Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal(str(qty)), unit_cost=Decimal(str(cost)),
            consumption_state=state,
        )

    def test_breakdown_terms_on_fixtured_job(self):
        from apps.jobs.financials import spend_breakdown
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '25'})
        self._blep(3)  # 3h * $25/h = $75 labor
        self._expense(40)  # material-less cash outlay
        self._material(2, 15)  # consumed, no expense: 2 * 15 = $30

        breakdown = spend_breakdown(self.job)

        self.assertEqual(breakdown['labor'], Decimal('75.00'))
        self.assertEqual(breakdown['labor_hours'], Decimal('3'))
        self.assertEqual(breakdown['materials_bought'], Decimal('70.00'))
        self.assertEqual(breakdown['total'], Decimal('145.00'))

    def test_total_matches_compute_job_financials_spent(self):
        from apps.jobs.financials import compute_job_financials, spend_breakdown
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '25'})
        self._blep(3)
        self._expense(40)
        self._material(2, 15)

        breakdown = spend_breakdown(self.job)
        fin = compute_job_financials(self.job)

        self.assertEqual(breakdown['total'], fin['spent'])

    def test_labor_zero_when_config_unset(self):
        from apps.jobs.financials import spend_breakdown
        Configuration.objects.filter(key='average_labor_cost').delete()
        self._blep(3)

        breakdown = spend_breakdown(self.job)

        self.assertEqual(breakdown['labor'], Decimal('0.00'))

    def test_labor_zero_when_config_blank(self):
        from apps.jobs.financials import spend_breakdown
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '  '})
        self._blep(3)

        breakdown = spend_breakdown(self.job)

        self.assertEqual(breakdown['labor'], Decimal('0.00'))

    def test_parts_sum_to_total_with_fractional_cents(self):
        """Regression test: parts must sum to total after quantization.

        Reproduces the round-then-sum vs sum-then-round issue: if we
        quantize labor and materials independently, then sum, we may get
        a different total than quantizing the unquantized sum first.

        Case: 30 minutes at $60.01/h produces labor = 30.005 which rounds
        to 30.00. Consumed material 1.01 qty * 0.50 cost = 0.505 rounds to
        0.50. But the sum 30.005 + 0.505 = 30.510 rounds to 30.51, not to
        30.50 + 0.50. The mismatch: 30.50 != 30.51.
        """
        from apps.jobs.financials import spend_breakdown, compute_job_financials

        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '60.01'})

        # 30 minutes = 0.5 hours
        # 0.5 * $60.01/h = $30.005 → quantizes to $30.00
        scheme = RateScheme.objects.create(
            name='Hr-fractional', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hours', accounting_category=self.cat)
        task = Task.objects.create(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS,
            rate_scheme=scheme)
        start = _aware(2026, 1, 15, 9, 0)
        end = _aware(2026, 1, 15, 9, 30)  # 30 minutes
        Blep.objects.create(
            task=task, user=self.user, start_time=start, end_time=end)

        # Material: 1.01 qty * 0.50 cost = 0.505
        # This quantizes to 0.50, but when added to the unquantized labor
        # (30.005 + 0.505 = 30.510) and quantized, it becomes 30.51
        # So the invariant breaks: 30.00 + 0.50 = 30.50 != 30.51 (the total)
        Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal('1.01'), unit_cost=Decimal('0.50'),
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED)

        breakdown = spend_breakdown(self.job)
        fin = compute_job_financials(self.job)

        # The key invariant: parts must sum to the displayed total
        # This fails with the current code where total is computed before
        # quantizing the parts
        self.assertEqual(
            breakdown['labor'] + breakdown['materials_bought'],
            breakdown['total'],
            f"Parts ({breakdown['labor']} + {breakdown['materials_bought']}) "
            f"do not sum to total ({breakdown['total']})"
        )

        # Total in breakdown must match the spent figure
        self.assertEqual(breakdown['total'], fin['spent'])
