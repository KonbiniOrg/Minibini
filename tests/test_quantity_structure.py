"""§9 quantity structure — Phase 4 Tasks 1-2.

Covers the binding rules from docs/plans/2026-08-03-task-owned-money-phase4-plan.md
(rules 1-5 + 8): the blessed multiplier (`Task._parent_multiplier()` /
`expected_qty()` / `expected_worker_time()`), `Task.derived_unit_price()`,
non-startable enforcement (start/blep/assign rejection on a parent,
first-subtask-on-a-started-task rejection, parent completion
offered-not-auto with a children-terminal gate, parent cancel requiring
children individually handled), schedule bar derivation (parent draws no
bar; a child's bar duration is the derived expectation, not its raw
per-unit estimate), and — Phase 4 Task 2 — billing: wizard source pools
excluding children, the shared claim/add path rejecting a direct child
claim, `Task.effective_rate()` falling back to `derived_unit_price()` on a
parent with no explicit rate, the detach-while-claimed guard, and parent
amount math flowing through the existing `compute_estimate_amount()` /
`compute_amount()` paths.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.estimates.services import EstimateWizardService
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import BlepService, TaskLifecycleService, TaskService
from apps.schedule.services import ScheduleService
from tests.base import BaseTestCase


class QuantityStructureTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ac = AccountingCategory.objects.get_or_create(
            code='QTYSTR', defaults={'name': 'Quantity structure test AC'},
        )[0]
        self.contact = Contact.objects.create(first_name='Q', last_name='Struct')
        self.job = Job.objects.create(
            job_number=f'QS-{timezone.now().timestamp()}',
            contact=self.contact,
        )
        self.user = User.objects.create_user(username='qs_worker', password='pass')

    def _scheme(self, name, *, algorithm=RateScheme.ENTERED_QTY,
                unit_label='ea', rate=Decimal('10.00')):
        return RateScheme.objects.create(
            name=name, algorithm=algorithm, rate=rate, unit_label=unit_label,
            accounting_category=self.ac,
        )

    def _task(self, name, *, parent=None, scheme=None, est_qty=None,
              est_worker_time=None, qty_scales_with_parent=True,
              status=Task.STATUS_PENDING, assignee=None):
        scheme = scheme or self._scheme(f'{name} scheme')
        task = Task(
            job=self.job, name=name, parent_task=parent, status=status,
            assignee=assignee, qty_scales_with_parent=qty_scales_with_parent,
        )
        task.stamp_from_scheme(scheme)
        task.est_qty = est_qty
        task.est_worker_time = est_worker_time
        task.save()
        return task


# ─────────────────────────── multiplier math ───────────────────────────

class ParentMultiplierTest(QuantityStructureTestBase):
    """Task._parent_multiplier() / expected_qty() / expected_worker_time() —
    the ONE blessed derivation (rule 3)."""

    def test_flag_true_multiplies_by_parent_qty(self):
        parent = self._task('Batch of boards', est_qty=Decimal('500'))
        child = self._task(
            'Mill per board', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('20'), est_worker_time=timedelta(minutes=20),
        )
        self.assertEqual(child.expected_qty(), Decimal('10000'))
        self.assertEqual(child.expected_worker_time(), timedelta(minutes=10000))

    def test_flag_false_multiplier_is_one_regardless_of_parent_qty(self):
        parent = self._task('Batch', est_qty=Decimal('500'))
        child = self._task(
            'Batch setup', parent=parent, qty_scales_with_parent=False,
            est_qty=Decimal('30'), est_worker_time=timedelta(minutes=45),
        )
        self.assertEqual(child.expected_qty(), Decimal('30'))
        self.assertEqual(child.expected_worker_time(), timedelta(minutes=45))

    def test_top_level_task_multiplier_is_inert(self):
        # Flag true but no parent at all — must not multiply by anything.
        top = self._task('Standalone', est_qty=Decimal('7'),
                         qty_scales_with_parent=True)
        self.assertEqual(top.expected_qty(), Decimal('7'))

    def test_flag_true_child_of_parent_with_no_est_qty_falls_back_to_one(self):
        parent = self._task('No qty yet', est_qty=None)
        child = self._task(
            'Per unit', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('4'),
        )
        self.assertEqual(child.expected_qty(), Decimal('4'))

    def test_expected_qty_none_when_own_est_qty_none(self):
        top = self._task('No estimate', est_qty=None)
        self.assertIsNone(top.expected_qty())

    def test_expected_worker_time_none_when_own_field_none(self):
        top = self._task('No worker time', est_qty=Decimal('1'),
                         est_worker_time=None)
        self.assertIsNone(top.expected_worker_time())

    def test_is_parent_true_only_with_subtasks(self):
        parent = self._task('Has children', est_qty=Decimal('1'))
        self.assertFalse(parent.is_parent)
        self._task('Child', parent=parent, est_qty=Decimal('1'))
        parent.refresh_from_db()
        self.assertTrue(parent.is_parent)


# ─────────────────────────── derived unit price ───────────────────────────

class DerivedUnitPriceTest(QuantityStructureTestBase):
    """Task.derived_unit_price() (rule 4) — parent effective per-unit price
    aggregated from its children."""

    def test_not_a_parent_returns_none(self):
        leaf = self._task('Leaf', est_qty=Decimal('1'))
        self.assertIsNone(leaf.derived_unit_price())

    def test_mixed_flags_sum_correctly(self):
        parent = self._task('Widget', est_qty=Decimal('10'))
        self._task(
            'Per-unit labor', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'),
            scheme=self._scheme('per-unit-rate', rate=Decimal('3.00')),
        )
        self._task(
            'Batch setup', parent=parent, qty_scales_with_parent=False,
            est_qty=Decimal('100'),
            scheme=self._scheme('batch-rate', rate=Decimal('0.50')),
        )
        # flag-true: 2 * 3.00 = 6.00 (already per-unit, adds straight in)
        # flag-false: 100 * 0.50 = 50.00 total / parent qty 10 = 5.00/unit
        # total = 11.00
        self.assertEqual(parent.derived_unit_price(), Decimal('11.00'))

    def test_quantizes_to_cents_at_the_end(self):
        parent = self._task('Widget3', est_qty=Decimal('3'))
        self._task(
            'Batch only', parent=parent, qty_scales_with_parent=False,
            est_qty=Decimal('10.00'),
            scheme=self._scheme('div3-rate', rate=Decimal('1.00')),
        )
        # 10.00 / 3 = 3.3333... -> quantized to 3.33
        self.assertEqual(parent.derived_unit_price(), Decimal('3.33'))

    def test_falsy_parent_est_qty_treats_flag_false_divisor_as_one(self):
        parent = self._task('No qty parent', est_qty=None)
        self._task(
            'Batch only 2', parent=parent, qty_scales_with_parent=False,
            est_qty=Decimal('4.00'),
            scheme=self._scheme('divfallback-rate', rate=Decimal('2.50')),
        )
        # batch total = 4.00 * 2.50 = 10.00; parent est_qty falsy -> /1
        self.assertEqual(parent.derived_unit_price(), Decimal('10.00'))


# ─────────────────────────── non-startable enforcement ───────────────────

class NonStartableEnforcementTest(QuantityStructureTestBase):
    """A task with ≥1 subtask cannot start/blep/assign; PM functions live on
    the children (rule 1)."""

    def _parent_with_child(self, parent_status=Task.STATUS_PENDING):
        parent = self._task('Parent', est_qty=Decimal('5'), status=parent_status)
        child = self._task('Child', parent=parent, est_qty=Decimal('1'))
        parent.refresh_from_db()
        return parent, child

    def test_start_work_rejects_parent(self):
        parent, _child = self._parent_with_child()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(parent.pk, self.user)

    def test_create_historical_blep_rejects_parent(self):
        parent, _child = self._parent_with_child()
        now = timezone.now()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(
                self.user, parent, now - timedelta(hours=1), now,
            )

    def test_assign_rejects_parent(self):
        parent, _child = self._parent_with_child()
        with self.assertRaises(ValidationError):
            TaskService.assign(parent, self.user.pk,
                               est_worker_time=timedelta(hours=1))

    def test_first_subtask_rejected_on_in_progress_parent(self):
        leaf = self._task('Started leaf', est_qty=Decimal('1'))
        TaskLifecycleService.start_work(leaf.pk, self.user)
        leaf.refresh_from_db()
        self.assertEqual(leaf.status, Task.STATUS_IN_PROGRESS)
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                self.job, 'Child of started',
                rate_scheme_id=self._scheme('cos-scheme').pk,
                parent_task_id=leaf.pk,
            )
        self.assertFalse(Task.objects.filter(parent_task=leaf).exists())

    def test_first_subtask_rejected_on_complete_parent(self):
        leaf = self._task('Complete leaf', est_qty=None)
        TaskLifecycleService.complete_task(leaf.pk, add_qty=Decimal('1'))
        leaf.refresh_from_db()
        self.assertEqual(leaf.status, Task.STATUS_COMPLETE)
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                self.job, 'Child of complete',
                rate_scheme_id=self._scheme('coc-scheme').pk,
                parent_task_id=leaf.pk,
            )

    def test_first_subtask_allowed_on_blocked_parent(self):
        leaf = self._task('Blocked leaf', est_qty=Decimal('1'))
        TaskLifecycleService.block_task(leaf.pk, reason='waiting', user=self.user)
        leaf.refresh_from_db()
        self.assertEqual(leaf.status, Task.STATUS_BLOCKED)
        child = TaskService.create_direct(
            self.job, 'Child of blocked',
            rate_scheme_id=self._scheme('cob-scheme').pk,
            parent_task_id=leaf.pk,
        )
        self.assertEqual(child.parent_task_id, leaf.pk)

    def test_first_subtask_allowed_on_pending_parent(self):
        leaf = self._task('Pending leaf', est_qty=Decimal('1'))
        child = TaskService.create_direct(
            self.job, 'Child of pending',
            rate_scheme_id=self._scheme('cop-scheme').pk,
            parent_task_id=leaf.pk,
        )
        self.assertEqual(child.parent_task_id, leaf.pk)


class ParentCompletionAndCancelTest(QuantityStructureTestBase):
    """Parent completion is OFFERED (not automatic) once every child is
    terminal; parent cancel does not cascade — every child must be handled
    individually first (rule 1)."""

    def test_parent_completion_rejected_with_open_children_listed(self):
        parent = self._task('Parent A', est_qty=Decimal('2'))
        self._task('Child A1', parent=parent, est_qty=Decimal('1'))
        self._task('Child A2', parent=parent, est_qty=Decimal('1'))
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.complete_task(parent.pk, add_qty=Decimal('2'))
        message = str(ctx.exception)
        self.assertIn('Child A1', message)
        self.assertIn('Child A2', message)

    def test_parent_completion_offered_once_children_terminal(self):
        parent = self._task('Parent B', est_qty=Decimal('2'))
        child1 = self._task('Child B1', parent=parent, est_qty=Decimal('1'))
        child2 = self._task('Child B2', parent=parent, est_qty=Decimal('1'))
        TaskLifecycleService.complete_task(child1.pk, add_qty=Decimal('1'))
        TaskLifecycleService.cancel_task(child2.pk)
        result = TaskLifecycleService.complete_task(parent.pk, add_qty=Decimal('2'))
        self.assertEqual(result.status, Task.STATUS_COMPLETE)

    def test_parent_cancel_rejected_with_open_children_listed(self):
        parent = self._task('Parent C', est_qty=Decimal('2'))
        self._task('Child C1', parent=parent, est_qty=Decimal('1'))
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.cancel_task(parent.pk)
        self.assertIn('Child C1', str(ctx.exception))

    def test_parent_cancel_succeeds_once_children_terminal(self):
        parent = self._task('Parent D', est_qty=Decimal('2'))
        child = self._task('Child D1', parent=parent, est_qty=Decimal('1'))
        TaskLifecycleService.cancel_task(child.pk)
        result = TaskLifecycleService.cancel_task(parent.pk)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)


# ─────────────────────────── schedule bar derivation ───────────────────

class ScheduleBarDerivationTest(QuantityStructureTestBase):
    """Rule 8: a parent (non-startable) draws no bar once it has children;
    a child's bar duration is the derived expectation, not its raw
    per-unit estimate."""

    def setUp(self):
        super().setUp()
        # Work-active job status so planned work forecasts.
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                       Job.STATUS_IN_PROGRESS):
            self.job.status = status
            self.job.save()

    def test_parent_draws_no_bar_child_bar_uses_expected_worker_time(self):
        # The parent carries an assignee directly (bypassing
        # TaskService.assign(), which now rejects this) to exercise the
        # ScheduleService-level exclusion defensively, not just rely on the
        # assign() guard never having let this state happen.
        parent = self._task(
            'Widget run', est_qty=Decimal('5'),
            est_worker_time=timedelta(hours=1),
            status=Task.STATUS_PENDING, assignee=self.user,
        )
        child = self._task(
            'Per-unit step', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('20'), est_worker_time=timedelta(minutes=6),
            status=Task.STATUS_PENDING, assignee=self.user,
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        lane = next(
            w for w in result['workers'] if w['user']['id'] == self.user.pk
        )
        bars = lane['bars']
        self.assertFalse(any(b['task_id'] == parent.pk for b in bars))
        child_bars = [b for b in bars if b['task_id'] == child.pk]
        self.assertTrue(child_bars, 'expected at least one bar for the child task')
        # 6 min/unit * 5 units (parent est_qty) = 30 expected minutes.
        self.assertEqual(child_bars[0]['est_minutes'], 30)


class ScheduleQueryBudgetTest(QuantityStructureTestBase):
    """Regression guard: Task.expected_worker_time() dereferences
    self.parent_task for a flag-true subtask, where the old plain
    `est_worker_time` field read touched no relation. ScheduleService's
    querysets whose tasks flow into expected_worker_time() must
    select_related('parent_task') (directly, or via 'task__parent_task' for
    Blep querysets) so that N children sharing one parent don't each trigger
    a separate query to re-fetch that same parent row."""

    def setUp(self):
        super().setUp()
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                       Job.STATUS_IN_PROGRESS):
            self.job.status = status
            self.job.save()
        self.parent = self._task(
            'Query-budget parent', est_qty=Decimal('3'),
            status=Task.STATUS_PENDING,
        )

    def _add_child(self, name):
        return self._task(
            name, parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'), est_worker_time=timedelta(minutes=10),
            status=Task.STATUS_PENDING, assignee=self.user,
        )

    def test_schedule_build_does_not_refetch_shared_parent_per_child(self):
        """Direct, deterministic version of the regression check (tighter
        than an aggregate query-count budget, which a full schedule build's
        fixture-driven noise — other workers' unrelated lanes, etc. — made
        too fuzzy to pin a per-child query delta on: an aggregate delta
        comparison across two full builds doesn't isolate cleanly enough to
        catch a 1-extra-query-per-child regression against that noise
        floor).

        A single-row `WHERE tasks.task_id = <parent.pk> LIMIT ...` query is
        exactly what Django emits when `.parent_task` is lazily dereferenced
        WITHOUT select_related having already joined it in. With
        select_related('parent_task') present at every site whose tasks
        flow into expected_worker_time(), this exact query must never
        appear — not once — no matter how many children share the parent.
        Without it, each child accessing `self.parent_task` in
        `_parent_multiplier()` re-issues this query separately (Django's ORM
        has no instance-spanning FK identity cache), so 2 children would
        show it twice.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._add_child('Child 1')
        self._add_child('Child 2')

        with CaptureQueriesContext(connection) as ctx:
            ScheduleService.get_schedule(now=timezone.now())

        parent_refetch_pattern = f'`tasks`.`task_id` = {self.parent.pk} LIMIT'
        refetches = [
            q['sql'] for q in ctx.captured_queries
            if parent_refetch_pattern in q['sql']
        ]
        self.assertEqual(
            refetches, [],
            f'expected zero separate parent-task refetch queries for '
            f'parent {self.parent.pk}, found {len(refetches)} — check '
            f"select_related('parent_task') on the querysets whose tasks "
            f'flow into Task.expected_worker_time().'
        )

    def test_schedule_build_does_not_refetch_shared_parent_for_running_blep(self):
        """Same regression via the OTHER site: `window_bleps` (the running-
        blep projection in `_compute_axis`) is a separate queryset from
        `_build_lane`'s `tasks_qs` — a distinct `Blep`/`Task` Python object
        per row, so its own `select_related('task', 'task__parent_task')` is
        what prevents ITS `b.task.expected_worker_time()` call from
        re-fetching the parent, independent of whether `tasks_qs` has the
        fix."""
        from apps.jobs.models import Blep
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        child = self._add_child('Running-blep child')
        Blep.objects.create(task=child, user=self.user, start_time=timezone.now())

        with CaptureQueriesContext(connection) as ctx:
            ScheduleService.get_schedule(now=timezone.now())

        parent_refetch_pattern = f'`tasks`.`task_id` = {self.parent.pk} LIMIT'
        refetches = [
            q['sql'] for q in ctx.captured_queries
            if parent_refetch_pattern in q['sql']
        ]
        self.assertEqual(
            refetches, [],
            f'expected zero separate parent-task refetch queries for '
            f'parent {self.parent.pk}, found {len(refetches)} — check '
            f"select_related('task', 'task__parent_task') on window_bleps."
        )


# ═══════════════════════ Phase 4 Task 2: billing ═══════════════════════

class SourcePoolExclusionTest(QuantityStructureTestBase):
    """Wizard source pools (estimate + invoice) exclude subtasks — the
    parent is the sole unit of billing (rule 4/5)."""

    def setUp(self):
        super().setUp()
        self.parent = self._task('Widget run', est_qty=Decimal('5'))
        self.child = self._task(
            'Per-unit step', parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )

    def test_estimate_pool_excludes_child_includes_parent(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-QS-1', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        pool = EstimateWizardService.get_source_pool(estimate)
        atom_ids = {(a['type'], a['id']) for a in pool['atoms']}
        self.assertIn(('task', self.parent.pk), atom_ids)
        self.assertNotIn(('task', self.child.pk), atom_ids)

    def test_invoice_pool_excludes_child_includes_parent(self):
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(invoice)
        task_ids = {t['task_id'] for t in pool['tasks']}
        self.assertIn(self.parent.pk, task_ids)
        self.assertNotIn(self.child.pk, task_ids)


class DirectClaimRejectionTest(QuantityStructureTestBase):
    """A child can't be claimed via the shared claim/add path even when a
    caller bypasses pool listing and posts its id directly — the base
    `_assert_atom_billable` check rejects it before the invoice/estimate
    subclass's own lifecycle checks run (rule 4/5)."""

    def setUp(self):
        super().setUp()
        self.parent = self._task('Batch', est_qty=Decimal('5'))
        self.child = self._task(
            'Per-unit', parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )

    def test_estimate_add_atoms_rejects_child(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-QS-2', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                estimate, [{'type': 'task', 'id': self.child.pk}])
        self.assertIn('Batch', str(ctx.exception))

    def test_invoice_add_atoms_rejects_child(self):
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                invoice, [{'type': 'task', 'id': self.child.pk}])
        self.assertIn('Batch', str(ctx.exception))

    def test_invoice_add_atoms_to_existing_line_rejects_child(self):
        # append-to-existing-line path (add_atoms_to_line_item), not just
        # the new-line-item path — both funnel through the same
        # _assert_atom_billable gate.
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        other = self._task('Loose task', est_qty=Decimal('1'))
        TaskLifecycleService.complete_task(other.pk, add_qty=Decimal('1'))
        line = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': other.pk}])
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_line_item(
                line, [{'type': 'task', 'id': self.child.pk}])


class EffectiveRateTest(QuantityStructureTestBase):
    """Task.effective_rate() — rate None + is_parent falls back to
    derived_unit_price(); an explicit parent.rate overrides; a childless
    task with no rate still prices 0 (rule 4)."""

    def test_derived_when_rate_none_and_is_parent(self):
        parent = self._task('Widget', est_qty=Decimal('10'))
        parent.rate = None
        parent.save()
        self._task(
            'Per-unit labor', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'),
            scheme=self._scheme('per-unit-rate-eff', rate=Decimal('3.00')),
        )
        parent.refresh_from_db()
        self.assertEqual(parent.effective_rate(), parent.derived_unit_price())
        self.assertEqual(parent.effective_rate(), Decimal('6.00'))

    def test_explicit_rate_overrides_derivation(self):
        parent = self._task(
            'Widget2', est_qty=Decimal('10'),
            scheme=self._scheme('parent-explicit', rate=Decimal('99.00')),
        )
        self._task(
            'Per-unit labor 2', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'),
            scheme=self._scheme('per-unit-rate-eff2', rate=Decimal('3.00')),
        )
        parent.refresh_from_db()
        self.assertEqual(parent.effective_rate(), Decimal('99.00'))
        self.assertNotEqual(parent.effective_rate(), parent.derived_unit_price())

    def test_childless_no_rate_prices_zero(self):
        leaf = self._task('Leaf money-less', est_qty=Decimal('1'))
        leaf.rate = None
        leaf.save()
        self.assertEqual(leaf.effective_rate(), Decimal('0.00'))


class ParentAmountMathTest(QuantityStructureTestBase):
    """Parent estimate/actual amounts flow through the EXISTING
    `compute_estimate_amount()` / `compute_amount()` paths using the
    derived (or explicit) `effective_rate()` — no separate parent-pricing
    path exists (rule 4). Estimate side bills the parent's own `est_qty`
    (the structure quantity); actual side bills `get_actual_qty()` (for an
    entered-qty parent, the completion-time "quantity made")."""

    def _parent_with_derived_price(self, parent_est_qty=Decimal('10')):
        parent = self._task('Structure', est_qty=parent_est_qty)
        parent.rate = None
        parent.save()
        self._task(
            'Sub', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'),
            scheme=self._scheme('sub-rate-amt', rate=Decimal('3.00')),
        )
        parent.refresh_from_db()
        return parent

    def test_compute_estimate_amount_uses_derived_rate_times_own_est_qty(self):
        parent = self._parent_with_derived_price(parent_est_qty=Decimal('10'))
        # derived_unit_price = 2 * 3.00 = 6.00; est amount = est_qty(10) * 6.00
        self.assertEqual(parent.derived_unit_price(), Decimal('6.00'))
        self.assertEqual(parent.compute_estimate_amount(), Decimal('60.00'))

    def test_compute_amount_uses_actual_qty_times_effective_rate(self):
        parent = self._parent_with_derived_price(parent_est_qty=Decimal('10'))
        parent.actual_qty = Decimal('7')
        parent.save()
        self.assertEqual(parent.get_actual_qty(), Decimal('7'))
        # 7 * 6.00 = 42.00
        self.assertEqual(parent.compute_amount(), Decimal('42.00'))


class DetachGuardTest(QuantityStructureTestBase):
    """Detaching (or reparenting) a child away from a PARENT that is
    claimed by a non-draft document is rejected; a claim held only by a
    DRAFT document doesn't block detach — the draft is still editable
    (rule 5)."""

    def setUp(self):
        super().setUp()
        self.parent = self._task('Structure', est_qty=Decimal('5'))
        self.child = self._task(
            'Sub', parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )

    def _claim_parent_via_estimate(self, status):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number=f'EST-DG-{status}', version=1,
            status=status,
        )
        li = EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('1'), units='ea',
            price=Decimal('10'), description='', accounting_category=self.ac,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.parent.pk,
        )
        return estimate

    def _claim_parent_via_invoice(self, status):
        invoice = Invoice.objects.create(job=self.job, status=status)
        li = InvoiceLineItem.objects.create(
            invoice=invoice, qty=Decimal('1'), units='ea',
            price=Decimal('10'), description='', accounting_category=self.ac,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.parent.pk,
        )
        return invoice

    def test_detach_allowed_when_parent_unclaimed(self):
        updated = TaskService.update_task(self.child.pk, parent_task=None)
        self.assertIsNone(updated.parent_task_id)

    def test_detach_blocked_when_parent_claimed_by_open_estimate(self):
        self._claim_parent_via_estimate(Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.update_task(self.child.pk, parent_task=None)
        self.assertIn('Structure', str(ctx.exception))

    def test_detach_allowed_when_parent_claimed_only_by_draft_estimate(self):
        self._claim_parent_via_estimate(Estimate.STATUS_DRAFT)
        updated = TaskService.update_task(self.child.pk, parent_task=None)
        self.assertIsNone(updated.parent_task_id)

    def test_detach_blocked_when_parent_claimed_by_open_invoice(self):
        self._claim_parent_via_invoice(Invoice.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            TaskService.update_task(self.child.pk, parent_task=None)

    def test_detach_allowed_when_parent_claimed_only_by_draft_invoice(self):
        self._claim_parent_via_invoice(Invoice.STATUS_DRAFT)
        updated = TaskService.update_task(self.child.pk, parent_task=None)
        self.assertIsNone(updated.parent_task_id)

    def test_reparent_to_other_parent_also_guarded(self):
        self._claim_parent_via_estimate(Estimate.STATUS_OPEN)
        other_parent = self._task('Other structure', est_qty=Decimal('2'))
        with self.assertRaises(ValidationError):
            TaskService.update_task(self.child.pk, parent_task=other_parent)

    def test_detach_allowed_after_estimate_claim_released_by_rejection(self):
        # A rejected estimate releases its EstimateLineItemSource rows
        # (apps.estimates.claims.DEAD_DOCUMENT_STATUSES) — no live claim
        # remains, so detach is allowed again.
        estimate = self._claim_parent_via_estimate(Estimate.STATUS_OPEN)
        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()
        updated = TaskService.update_task(self.child.pk, parent_task=None)
        self.assertIsNone(updated.parent_task_id)


class WizardComposeParentAtomTest(QuantityStructureTestBase):
    """Composing a parent atom through the wizard's shared add-atoms path
    (rule 4): solo-atom copy-over prices via the derived rate; a parent
    mixed into a multi-atom bundle with a differently-rated atom falls
    back to the non-uniform summary (parent.rate is None, which
    `_uniform_money_bundle` already treats as non-uniform) instead of
    crashing."""

    def _parent_with_derived_price(self):
        parent = self._task('Structure', est_qty=Decimal('4'))
        parent.rate = None
        parent.save()
        self._task(
            'Sub', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'),
            scheme=self._scheme('sub-rate-bundle', rate=Decimal('5.00')),
        )
        parent.refresh_from_db()
        return parent

    def test_estimate_solo_compose_uses_derived_price(self):
        parent = self._parent_with_derived_price()
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-QS-3', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        line = EstimateWizardService.add_atoms_to_new_line_item(
            estimate, [{'type': 'task', 'id': parent.pk}])
        self.assertEqual(line.qty, Decimal('4'))
        self.assertEqual(line.price, Decimal('10.00'))  # derived: 2 * 5.00

    def test_multi_atom_bundle_with_parent_falls_back_gracefully(self):
        parent = self._parent_with_derived_price()
        other = self._task('Flat task', est_qty=Decimal('1'))
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-QS-4', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        line = EstimateWizardService.add_atoms_to_new_line_item(
            estimate,
            [{'type': 'task', 'id': parent.pk}, {'type': 'task', 'id': other.pk}],
        )
        self.assertEqual(line.units, 'none')
        self.assertEqual(line.qty, Decimal('1'))
