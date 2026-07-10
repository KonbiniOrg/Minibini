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
from datetime import date, datetime
from decimal import Decimal

from rest_framework.test import APIClient

from django.utils import timezone

from tests.base import FixtureTestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.expenses.models import Expense
from apps.inventory.models import Material
from apps.jobs.models import Blep, Job, RateScheme, Task
from apps.schedule.calendar_arithmetic import WeekEnvelope


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


class DueCountdownTests(FixtureTestCase):
    """Working-day countdown math against a fixed Mon-Fri envelope and
    pinned dates. All dates are hand-picked, never wall-clock relative:

        Mon 2026-07-06, Tue 07, Wed 08, Thu 09, Fri 10,
        Sat 11 (off), Sun 12 (off), Mon 13.
    """

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.envelope = WeekEnvelope.default()  # Mon-Fri working, Sat/Sun off

    def test_countdown_spans_a_weekend(self):
        from apps.jobs.overview import JobOverviewService

        job = _job(self.contact)
        job.due_date = timezone.make_aware(datetime(2026, 7, 13, 12, 0))  # Mon
        job.save()
        today = date(2026, 7, 8)  # Wed

        result = JobOverviewService.summary(job, today=today, envelope=self.envelope)

        # Working days strictly after Wed 08 through Mon 13 inclusive:
        # Thu 09, Fri 10, Mon 13 (Sat/Sun excluded) = 3
        self.assertEqual(result['due'], {'date': '2026-07-13', 'working_days_left': 3})

    def test_due_today_is_zero(self):
        from apps.jobs.overview import JobOverviewService

        job = _job(self.contact)
        job.due_date = timezone.make_aware(datetime(2026, 7, 10, 12, 0))  # Fri
        job.save()
        today = date(2026, 7, 10)  # same Fri

        result = JobOverviewService.summary(job, today=today, envelope=self.envelope)

        self.assertEqual(result['due'], {'date': '2026-07-10', 'working_days_left': 0})

    def test_overdue_is_negative_count_of_missed_working_days(self):
        from apps.jobs.overview import JobOverviewService

        job = _job(self.contact)
        job.due_date = timezone.make_aware(datetime(2026, 7, 8, 12, 0))  # Wed
        job.save()
        today = date(2026, 7, 13)  # Mon

        result = JobOverviewService.summary(job, today=today, envelope=self.envelope)

        # Working days strictly after Wed 08 through Mon 13 inclusive:
        # Thu 09, Fri 10, Mon 13 = 3 missed working days -> -3
        self.assertEqual(result['due'], {'date': '2026-07-08', 'working_days_left': -3})

    def test_no_due_date_is_null(self):
        from apps.jobs.overview import JobOverviewService

        job = _job(self.contact)  # due_date left unset
        today = date(2026, 7, 8)

        result = JobOverviewService.summary(job, today=today, envelope=self.envelope)

        self.assertIsNone(result['due'])


class WorkAggregatesTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.cat = AccountingCategory.objects.create(code='OV-W', name='ov-w')
        self.scheme = RateScheme.objects.create(
            name='Hr-ov-work', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hours', accounting_category=self.cat)
        self.worker = User.objects.create_user(
            username='ov-worker', password='x', first_name='Dana', last_name='')
        self.job = _job(self.contact)

    def _task(self, status, hours=None, name='t'):
        from datetime import timedelta
        return Task.objects.create(
            job=self.job, name=name, status=status, rate_scheme=self.scheme,
            est_worker_time=timedelta(hours=hours) if hours is not None else None,
        )

    def test_progress_and_working_now_aggregates(self):
        from apps.jobs.overview import JobOverviewService

        complete_task = self._task(Task.STATUS_COMPLETE, hours=10, name='done')
        active_task = self._task(Task.STATUS_IN_PROGRESS, hours=20, name='active')
        self._task(Task.STATUS_BLOCKED, hours=5, name='blocked')
        # Cancelled work is excluded from tasks_total / est_time_total_hours
        # (board precedent: BoardService.strip_jobs_payload computes progress
        # with .exclude(status=STATUS_CANCELLED), so progress can reach 100%
        # when all live tasks complete) but still counts in tasks_terminal.
        self._task(Task.STATUS_CANCELLED, hours=3, name='cancelled')
        self._task(Task.STATUS_PENDING, hours=None, name='pending')

        # An open (running) blep on the in-progress task.
        Blep.objects.create(
            task=active_task, user=self.worker,
            start_time=_aware(2026, 1, 15, 9, 0), end_time=None,
        )
        # A closed blep shouldn't show up in working_now.
        Blep.objects.create(
            task=complete_task, user=self.worker,
            start_time=_aware(2026, 1, 15, 9, 0), end_time=_aware(2026, 1, 15, 10, 0),
        )

        result = JobOverviewService.summary(
            self.job, today=date(2026, 1, 15), envelope=WeekEnvelope.default())
        work = result['work']

        self.assertEqual(work['tasks_total'], 4)  # cancelled excluded
        self.assertEqual(work['tasks_complete'], 1)
        self.assertEqual(work['tasks_blocked'], 1)
        self.assertEqual(work['tasks_terminal'], 2)  # complete + cancelled
        # 10+20+5 — the cancelled task's 3h must NOT appear here.
        self.assertEqual(work['est_time_total_hours'], '35.0')
        self.assertEqual(work['est_time_complete_hours'], '10.0')
        self.assertEqual(
            work['working_now'],
            [{'task_name': 'active', 'worker_name': 'Dana'}],
        )

    def test_spend_section_matches_spend_breakdown(self):
        from apps.jobs.financials import spend_breakdown
        from apps.jobs.overview import JobOverviewService

        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '25'})
        task = self._task(Task.STATUS_IN_PROGRESS, hours=None, name='billable')
        Blep.objects.create(
            task=task, user=self.worker,
            start_time=_aware(2026, 1, 15, 9, 0), end_time=_aware(2026, 1, 15, 12, 0),
        )
        Expense.objects.create(
            entered_by=self.worker, amount=Decimal('40'),
            purchased_on=date(2026, 1, 15), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC', job=self.job,
        )

        breakdown = spend_breakdown(self.job)
        result = JobOverviewService.summary(
            self.job, today=date(2026, 1, 15), envelope=WeekEnvelope.default())

        self.assertEqual(result['spend'], {
            'labor': str(breakdown['labor']),
            'labor_hours': '3.0',
            'materials_bought': str(breakdown['materials_bought']),
            'total': str(breakdown['total']),
        })


class OverviewEndpointTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.job = _job(self.contact)
        self.user = User.objects.get(username='admin')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_overview_endpoint_returns_summary_shape(self):
        response = self.client.get(f'/api/jobs/{self.job.pk}/overview/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('due', data)
        self.assertIn('spend', data)
        self.assertIn('work', data)
        self.assertEqual(
            set(data['spend'].keys()),
            {'labor', 'labor_hours', 'materials_bought', 'total'},
        )
        self.assertEqual(
            set(data['work'].keys()),
            {
                'tasks_total', 'tasks_complete', 'tasks_blocked', 'tasks_terminal',
                'est_time_total_hours', 'est_time_complete_hours', 'working_now',
            },
        )

    def test_overview_endpoint_anonymous_rejected(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(f'/api/jobs/{self.job.pk}/overview/')

        self.assertIn(response.status_code, (401, 403))
