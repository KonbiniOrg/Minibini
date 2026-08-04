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
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import BlepService, JobService, TaskLifecycleService, TaskService
from apps.schedule.services import ScheduleService
from tests.base import BaseTestCase, grant_atoms


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


# ═══════════ Phase 4 Task 2 follow-up: material-subtask guard ═══════════
# Code review finding: MaterialService.assign_task / create_on_job had no
# guard against attaching a Material directly to a subtask, and the
# invoice pool's new parent_task__isnull=True task filter (above) meant
# such a material — no longer surfaced by any per-task group, and not
# task-less either — would become permanently unbillable dead money.
# Fixed both ends: (1) the attach guards below (primary defense), (2) the
# invoice pool's material query also covers Q(task__parent_task=task) as a
# defensive fallback for a row that got there some other way.

class MaterialSubtaskGuardTest(QuantityStructureTestBase):
    """Spec §9 rule 4/5 follow-up: a Material cannot be attached to a
    subtask directly — materials belong to the structure, same doctrine as
    billing pools excluding children. The parent remains a legal target."""

    def setUp(self):
        super().setUp()
        self.parent = self._task('Structure', est_qty=Decimal('5'))
        self.child = self._task(
            'Sub', parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )

    def test_assign_task_rejects_subtask(self):
        mat = MaterialService.create_on_job(
            job=self.job, task=None, description='steel',
            quantity=Decimal('1'), accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.assign_task(mat, self.child)
        self.assertIn('Structure', str(ctx.exception))

    def test_assign_task_allows_parent(self):
        mat = MaterialService.create_on_job(
            job=self.job, task=None, description='steel',
            quantity=Decimal('1'), accounting_category=self.ac,
        )
        MaterialService.assign_task(mat, self.parent)
        mat.refresh_from_db()
        self.assertEqual(mat.task_id, self.parent.pk)

    def test_create_on_job_rejects_subtask(self):
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.create_on_job(
                job=self.job, task=self.child, description='glue',
                quantity=Decimal('1'), accounting_category=self.ac,
            )
        self.assertIn('Structure', str(ctx.exception))

    def test_create_on_job_allows_parent(self):
        mat = MaterialService.create_on_job(
            job=self.job, task=self.parent, description='glue',
            quantity=Decimal('1'), accounting_category=self.ac,
        )
        self.assertEqual(mat.task_id, self.parent.pk)


class MaterialSubtaskGuardApiTest(QuantityStructureTestBase):
    """API-level coverage of the material-subtask guard, both attachment
    routes: POST /api/tasks/{id}/materials/ (create_on_job) and
    POST /api/materials/{id}/assign-task/ (assign_task)."""

    def setUp(self):
        super().setUp()
        self.parent = self._task('Structure', est_qty=Decimal('5'))
        self.child = self._task(
            'Sub', parent=self.parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )
        self.client.force_login(self.user)

    def test_create_material_on_subtask_via_task_endpoint_rejected(self):
        r = self.client.post(
            f'/api/tasks/{self.child.pk}/materials/',
            data={'description': 'glue', 'quantity': '1.00',
                  'accounting_category': self.ac.pk},
            content_type='application/json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_create_material_on_parent_via_task_endpoint_allowed(self):
        r = self.client.post(
            f'/api/tasks/{self.parent.pk}/materials/',
            data={'description': 'glue', 'quantity': '1.00',
                  'accounting_category': self.ac.pk},
            content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_assign_task_to_subtask_via_material_endpoint_rejected(self):
        mat = MaterialService.create_on_job(
            job=self.job, task=None, description='steel',
            quantity=Decimal('1'), accounting_category=self.ac,
        )
        r = self.client.post(
            f'/api/materials/{mat.pk}/assign-task/',
            data={'task': self.child.pk}, content_type='application/json')
        self.assertEqual(r.status_code, 400, r.content)


class InvoicePoolMaterialSurfacingTest(QuantityStructureTestBase):
    """Defensive fallback: a Material that ends up attached to a CHILD task
    some other way (the guards above are the primary defense; this covers
    a QuerySet.update() bypass, which — per CLAUDE.md — skips Model.save()
    and therefore skips those guards entirely) still surfaces, under its
    PARENT's atom group, and is billable — instead of becoming permanently
    unbillable dead money."""

    def test_child_attached_material_bills_under_parent_group(self):
        parent = self._task('Structure', est_qty=Decimal('5'))
        child = self._task(
            'Sub', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('1'),
        )
        mat = MaterialService.create_on_job(
            job=self.job, task=None, description='Planted on child',
            quantity=Decimal('3'), unit_cost=Decimal('2.00'),
            accounting_category=self.ac,
        )
        mat.inventory_item.qty_on_hand = mat.quantity
        mat.inventory_item.save()
        MaterialService.consume(mat)
        # Simulate a pre-guard/bypass row landing on the child — a direct
        # QuerySet.update() (not MaterialService.assign_task), which skips
        # the guard entirely, same as it skips Model.save()'s own
        # normalization per CLAUDE.md's QuerySet.update() rule.
        Material.objects.filter(pk=mat.pk).update(task_id=child.pk)

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(invoice)
        parent_group = next(g for g in pool['tasks'] if g['task_id'] == parent.pk)
        mat_atoms = {a['id']: a for a in parent_group['atoms'] if a['type'] == 'material'}
        self.assertIn(mat.pk, mat_atoms)
        self.assertEqual(mat_atoms[mat.pk]['state'], 'available')
        # The child itself still draws no group of its own — the material
        # rides under the parent, not a resurrected child group.
        self.assertFalse(any(g['task_id'] == child.pk for g in pool['tasks']))


# ═══════════════ Phase 4 Task 3: API + serializers ═══════════════
# Covers rules 2, 6, 7 of docs/plans/2026-08-03-task-owned-money-phase4-plan.md
# at the API layer: TaskSerializer exposes is_parent/expected_qty/
# expected_worker_time/derived_unit_price/qty_scales_with_parent; subtask
# CREATE resolves the unit-keyed qty_scales_with_parent default
# service-side; the Deliverables bridge (Task <-> Deliverable copy actions);
# WorkTemplate product-structure stamping with an explicit quantity N.

class TaskSerializerQuantityFieldsTest(QuantityStructureTestBase):
    """is_parent / expected_qty / expected_worker_time / derived_unit_price
    / qty_scales_with_parent all appear on task payloads."""

    def test_leaf_task_is_parent_false(self):
        leaf = self._task('Leaf', est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/tasks/{leaf.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['is_parent'])

    def test_parent_task_is_parent_true(self):
        parent = self._task('Parent', est_qty=Decimal('5'))
        self._task('Child', parent=parent, est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/tasks/{parent.pk}/')
        self.assertTrue(r.json()['is_parent'])

    def test_child_expected_qty_and_worker_time_reflect_multiplier(self):
        parent = self._task('Parent', est_qty=Decimal('500'))
        self._task(
            'Child', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('20'), est_worker_time=timedelta(minutes=20),
        )
        self.client.force_login(self.user)
        r = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        row = next(t for t in r.json() if t['name'] == 'Child')
        self.assertEqual(row['expected_qty'], '10000.00')
        self.assertEqual(row['expected_worker_time'], '6 22:40:00')

    def test_parent_derived_unit_price_exposed(self):
        parent = self._task('Widget', est_qty=Decimal('10'))
        self._task(
            'Per-unit', parent=parent, qty_scales_with_parent=True,
            est_qty=Decimal('2'), scheme=self._scheme('r1', rate=Decimal('3.00')),
        )
        self.client.force_login(self.user)
        r = self.client.get(f'/api/tasks/{parent.pk}/')
        self.assertEqual(r.json()['derived_unit_price'], '6.00')

    def test_leaf_derived_unit_price_null(self):
        leaf = self._task('Leaf2', est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/tasks/{leaf.pk}/')
        self.assertIsNone(r.json()['derived_unit_price'])

    def test_qty_scales_with_parent_present_on_top_level_task(self):
        top = self._task('Top', est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/tasks/{top.pk}/')
        self.assertIn('qty_scales_with_parent', r.json())
        self.assertTrue(r.json()['qty_scales_with_parent'])


class IsParentQueryCostTest(QuantityStructureTestBase):
    """is_parent must read from a precomputed context set rather than
    querying `.subtasks.exists()` per row — the per-row cost Task 3 flags
    for a list queryset (job task list, job-detail embed)."""

    def test_precomputed_context_avoids_a_query(self):
        parent = self._task('P', est_qty=Decimal('1'))
        child = self._task('C', parent=parent, est_qty=Decimal('1'))
        from apps.api.tasks.serializers import TaskSerializer
        serializer = TaskSerializer(
            context={'parent_task_ids_with_children': {parent.pk}},
        )
        with self.assertNumQueries(0):
            self.assertTrue(serializer.get_is_parent(parent))
            self.assertFalse(serializer.get_is_parent(child))

    def test_subtask_never_queries_even_without_context(self):
        # One level of nesting only (enforced at creation) — a subtask can
        # never itself be a parent, so this short-circuits on parent_task_id
        # with no query regardless of context.
        parent = self._task('P2', est_qty=Decimal('1'))
        child = self._task('C2', parent=parent, est_qty=Decimal('1'))
        from apps.api.tasks.serializers import TaskSerializer
        serializer = TaskSerializer(context={})
        with self.assertNumQueries(0):
            self.assertFalse(serializer.get_is_parent(child))

    def test_top_level_falls_back_to_property_without_context(self):
        # Detail/single-instance rendering has no precomputed set — falls
        # back to the querying property (one query, not zero, but never an
        # N+1 across a list since there's only one instance).
        top = self._task('P3', est_qty=Decimal('1'))
        from apps.api.tasks.serializers import TaskSerializer
        serializer = TaskSerializer(context={})
        with self.assertNumQueries(1):
            self.assertFalse(serializer.get_is_parent(top))

    def test_job_tasklist_endpoint_reports_is_parent_correctly(self):
        parent = self._task('P4', est_qty=Decimal('1'))
        child = self._task('C4', parent=parent, est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        by_name = {t['name']: t for t in r.json()}
        self.assertTrue(by_name['P4']['is_parent'])
        self.assertFalse(by_name['C4']['is_parent'])

    def test_job_detail_endpoint_reports_is_parent_correctly(self):
        parent = self._task('P5', est_qty=Decimal('1'))
        child = self._task('C5', parent=parent, est_qty=Decimal('1'))
        self.client.force_login(self.user)
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        by_name = {t['name']: t for t in r.json()['tasks']}
        self.assertTrue(by_name['P5']['is_parent'])
        self.assertFalse(by_name['C5']['is_parent'])


class SubtaskQtyScalesDefaultTest(QuantityStructureTestBase):
    """The unit-keyed qty_scales_with_parent default (rule 2) resolves
    SERVICE-side, at subtask creation, when the key is absent from the
    request — true iff the parent's unit_label == 'ea'."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_default_true_when_parent_unit_is_ea(self):
        parent_scheme = self._scheme('parent-ea', unit_label='ea')
        parent = self._task('P-ea', est_qty=Decimal('5'), scheme=parent_scheme)
        child_scheme = self._scheme('child-scheme')
        r = self.client.post(
            f'/api/tasks/{parent.pk}/subtasks/',
            {'name': 'Child', 'est_qty': '1.00', 'rate_scheme': child_scheme.pk},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        child = Task.objects.get(pk=r.json()['task_id'])
        self.assertTrue(child.qty_scales_with_parent)

    def test_default_false_when_parent_unit_is_not_ea(self):
        parent_scheme = self._scheme('parent-bf', unit_label='bd ft')
        parent = self._task('P-bf', est_qty=Decimal('5'), scheme=parent_scheme)
        child_scheme = self._scheme('child-scheme-2')
        r = self.client.post(
            f'/api/tasks/{parent.pk}/subtasks/',
            {'name': 'Child', 'est_qty': '1.00', 'rate_scheme': child_scheme.pk},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        child = Task.objects.get(pk=r.json()['task_id'])
        self.assertFalse(child.qty_scales_with_parent)

    def test_explicit_flag_overrides_default(self):
        parent_scheme = self._scheme('parent-ea2', unit_label='ea')
        parent = self._task('P-ea2', est_qty=Decimal('5'), scheme=parent_scheme)
        child_scheme = self._scheme('child-scheme-3')
        r = self.client.post(
            f'/api/tasks/{parent.pk}/subtasks/',
            {'name': 'Child', 'est_qty': '1.00', 'rate_scheme': child_scheme.pk,
             'qty_scales_with_parent': False},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        child = Task.objects.get(pk=r.json()['task_id'])
        self.assertFalse(child.qty_scales_with_parent)

    def test_generic_tasks_endpoint_also_applies_default(self):
        parent_scheme = self._scheme('parent-ea4', unit_label='ea')
        parent = self._task('P-ea4', est_qty=Decimal('5'), scheme=parent_scheme)
        child_scheme = self._scheme('child-scheme-4')
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Child via job endpoint', 'est_qty': '1.00',
             'rate_scheme': child_scheme.pk, 'parent_task': parent.pk},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        child = Task.objects.get(pk=r.json()['task_id'])
        self.assertTrue(child.qty_scales_with_parent)

    def test_flag_editable_post_create_same_as_est_qty_pending(self):
        """Pending: open to any authenticated user — the same C1 gate
        est_qty edits use (no MONEY_FIELDS-style permission add-on)."""
        parent_scheme = self._scheme('parent-ea3', unit_label='ea')
        parent = self._task('P-ea3', est_qty=Decimal('5'), scheme=parent_scheme)
        child = self._task(
            'Child', parent=parent, qty_scales_with_parent=True, est_qty=Decimal('1'),
        )
        r = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{child.pk}/',
            {'qty_scales_with_parent': False},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        child.refresh_from_db()
        self.assertFalse(child.qty_scales_with_parent)


# ═══════════════ Phase 4 Task 3: Deliverables bridge (rule 7) ═══════════════

class DeliverableSourceTaskSerializerTest(QuantityStructureTestBase):

    def test_source_task_and_name_exposed(self):
        task = self._task('Widget task', est_qty=Decimal('5'))
        from apps.deliverables.models import Deliverable
        d = Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('5'),
            units='ea', source_task=task,
        )
        self.client.force_login(self.user)
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/')
        body = r.json()
        self.assertEqual(body['source_task'], task.pk)
        self.assertEqual(body['source_task_name'], 'Widget task')

    def test_source_task_null_when_unlinked(self):
        from apps.deliverables.models import Deliverable
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('1'), units='ea',
        )
        self.client.force_login(self.user)
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/')
        body = r.json()
        self.assertIsNone(body['source_task'])
        self.assertIsNone(body['source_task_name'])


class AddAsDeliverableEndpointTest(QuantityStructureTestBase):
    """POST /api/tasks/{id}/add-as-deliverable/ — permission matches
    deliverable creation today (CanManageJobOrPM)."""

    def setUp(self):
        super().setUp()
        self.pm = User.objects.create_user(username='qs_pm', password='pass')
        self.job.project_manager = self.pm
        self.job.save()

    def test_manager_can_add_task_as_deliverable(self):
        task = self._task('Widget', est_qty=Decimal('7'))
        mgr = grant_atoms(
            User.objects.create_user(username='qs_mgr', password='pass'),
            'can_manage_jobs',
        )
        self.client.force_login(mgr)
        r = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['description'], 'Widget')
        self.assertEqual(body['qty_ordered'], '7.00')
        self.assertEqual(body['units'], 'ea')
        self.assertEqual(body['source_task'], task.pk)
        from apps.deliverables.models import Deliverable
        d = Deliverable.objects.get(pk=body['id'])
        self.assertEqual(d.source_task_id, task.pk)

    def test_pm_can_add_task_as_deliverable(self):
        task = self._task('Widget PM', est_qty=Decimal('3'))
        self.client.force_login(self.pm)
        r = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r.status_code, 201, r.content)

    def test_plain_worker_forbidden(self):
        task = self._task('Widget worker', est_qty=Decimal('3'))
        self.client.force_login(self.user)
        r = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r.status_code, 403)

    def test_subtask_rejected(self):
        parent = self._task('Structure', est_qty=Decimal('5'))
        child = self._task('Child', parent=parent, est_qty=Decimal('1'))
        self.client.force_login(self.pm)
        r = self.client.post(f'/api/tasks/{child.pk}/add-as-deliverable/')
        self.assertEqual(r.status_code, 400)

    def test_already_linked_rejected(self):
        task = self._task('Linked', est_qty=Decimal('2'))
        self.client.force_login(self.pm)
        r1 = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r2.status_code, 400)

    def test_task_with_no_est_qty_rejected(self):
        task = self._task('No qty', est_qty=None)
        self.client.force_login(self.pm)
        r = self.client.post(f'/api/tasks/{task.pk}/add-as-deliverable/')
        self.assertEqual(r.status_code, 400)


class CreateWorkStructureEndpointTest(QuantityStructureTestBase):
    """POST /api/jobs/{job_id}/deliverables/{id}/create-work-structure/ —
    mints a money-less flat task, so the gate matches flat-task creation
    (can_manage_jobs, the job's PM, or financials), not the plain
    CanManageJobOrPM the rest of DeliverableViewSet uses."""

    def setUp(self):
        super().setUp()
        self.pm = User.objects.create_user(username='qs_pm2', password='pass')
        self.job.project_manager = self.pm
        self.job.save()

    def _deliverable(self, **kwargs):
        from apps.deliverables.models import Deliverable
        defaults = dict(
            job=self.job, description='Stool', qty_ordered=Decimal('12'), units='ea',
        )
        defaults.update(kwargs)
        return Deliverable.objects.create(**defaults)

    def test_manager_can_create_work_structure(self):
        mgr = grant_atoms(
            User.objects.create_user(username='qs_mgr2', password='pass'),
            'can_manage_jobs',
        )
        d = self._deliverable()
        self.client.force_login(mgr)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body['name'], 'Stool')
        self.assertEqual(body['est_qty'], '12.00')
        self.assertEqual(body['unit_label'], 'ea')
        self.assertIsNone(body['rate'])
        self.assertIsNone(body['accounting_category'])
        d.refresh_from_db()
        self.assertEqual(d.source_task_id, body['task_id'])

    def test_financials_atom_without_pm_can_create(self):
        fin = grant_atoms(
            User.objects.create_user(username='qs_fin', password='pass'),
            'can_manage_financials',
        )
        d = self._deliverable()
        self.client.force_login(fin)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_can_create(self):
        d = self._deliverable()
        self.client.force_login(self.pm)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_plain_worker_forbidden(self):
        d = self._deliverable()
        self.client.force_login(self.user)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r.status_code, 403)

    def test_already_linked_rejected(self):
        d = self._deliverable()
        self.client.force_login(self.pm)
        r1 = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/create-work-structure/'
        )
        self.assertEqual(r2.status_code, 400)


# ═══════════════ Phase 4 Task 3: Template N (rule 6) ═══════════════

class TemplateProductStructureGenerationTest(QuantityStructureTestBase):

    def setUp(self):
        super().setUp()
        from apps.estimates.models import WorkTemplate, ServiceItem, TemplateTaskAssociation
        self.WorkTemplate = WorkTemplate
        self.ServiceItem = ServiceItem
        self.TemplateTaskAssociation = TemplateTaskAssociation
        self.child_scheme_ea = self._scheme(
            'mill-scheme', unit_label='ea', rate=Decimal('3.00'))
        self.template = WorkTemplate.objects.create(
            template_name='Widget Structure', description='A widget',
            is_product_structure=True,
        )
        self.si = ServiceItem.objects.create(
            template_name='Mill each', rate_scheme=self.child_scheme_ea, is_active=True,
        )
        TemplateTaskAssociation.objects.create(
            work_template=self.template, service_item=self.si,
            est_qty=Decimal('2'), sort_order=1,
        )

    def test_apply_with_quantity_creates_parent_and_subtask(self):
        JobService.populate_from_template(self.job, self.template, quantity=Decimal('10'))
        parent = Task.objects.get(job=self.job, name='Widget Structure')
        self.assertIsNone(parent.parent_task_id)
        self.assertEqual(parent.est_qty, Decimal('10'))
        self.assertEqual(parent.unit_label, 'ea')
        self.assertIsNone(parent.rate)
        self.assertIsNone(parent.accounting_category_id)
        children = list(Task.objects.filter(parent_task=parent))
        self.assertEqual(len(children), 1)
        child = children[0]
        self.assertEqual(child.name, 'Mill each')
        self.assertEqual(child.est_qty, Decimal('2'))
        self.assertTrue(child.qty_scales_with_parent)
        self.assertEqual(child.expected_qty(), Decimal('20'))

    def test_parent_uses_base_price_when_set(self):
        self.template.base_price = Decimal('99.00')
        self.template.save()
        JobService.populate_from_template(self.job, self.template, quantity=Decimal('5'))
        parent = Task.objects.get(job=self.job, name='Widget Structure')
        self.assertEqual(parent.rate, Decimal('99.00'))

    def test_api_endpoint_accepts_quantity_for_structure_template(self):
        mgr = grant_atoms(
            User.objects.create_user(username='tmpl_mgr', password='pass'),
            'can_manage_jobs',
        )
        self.client.force_login(mgr)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': self.template.pk, 'quantity': '4'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        parent = Task.objects.get(job=self.job, name='Widget Structure')
        self.assertEqual(parent.est_qty, Decimal('4'))

    def test_api_rejects_quantity_on_non_structure_template(self):
        flat_template = self.WorkTemplate.objects.create(template_name='Flat template')
        mgr = grant_atoms(
            User.objects.create_user(username='tmpl_mgr2', password='pass'),
            'can_manage_jobs',
        )
        self.client.force_login(mgr)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': flat_template.pk, 'quantity': '3'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_api_rejects_zero_or_negative_quantity(self):
        mgr = grant_atoms(
            User.objects.create_user(username='tmpl_mgr3', password='pass'),
            'can_manage_jobs',
        )
        self.client.force_login(mgr)
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': self.template.pk, 'quantity': '0'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_flat_generation_unchanged_without_quantity(self):
        flat_template = self.WorkTemplate.objects.create(template_name='Flat template 2')
        self.TemplateTaskAssociation.objects.create(
            work_template=flat_template, service_item=self.si,
            est_qty=Decimal('3'), sort_order=1,
        )
        JobService.populate_from_template(self.job, flat_template)
        task = Task.objects.get(job=self.job, name='Mill each')
        self.assertIsNone(task.parent_task_id)
        self.assertEqual(task.est_qty, Decimal('3'))


class WorkTemplateSerializerProductStructureFieldsTest(QuantityStructureTestBase):
    """is_product_structure/base_price ride the existing WorkTemplate CRUD
    permission (CanManageConfig) — no new plumbing needed."""

    def test_fields_present_and_writable(self):
        mgr = grant_atoms(
            User.objects.create_user(username='wt_mgr', password='pass'),
            'can_manage_config',
        )
        self.client.force_login(mgr)
        r = self.client.post(
            '/api/work-templates/',
            {'template_name': 'Structure T', 'is_product_structure': True,
             'base_price': '25.00'},
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertTrue(body['is_product_structure'])
        self.assertEqual(body['base_price'], '25.00')
