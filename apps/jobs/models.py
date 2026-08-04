from datetime import timedelta
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import AbstractWorkContainer, TimeChangeRequest
from apps.core.history import history
from apps.core.services import ServiceError
from apps.core.timeutils import floor_to_minute, timedelta_to_hours
from apps.core.units import HOUR_UNIT


class SchemeInactiveError(ServiceError):
    """Raised when a task-creation path stamps from an inactive RateScheme
    preset (``is_active=False``) without ``allow_inactive_scheme=True``.

    Replaces the old supersession-based ``SchemeSupersededError`` — Task 4
    retires ``RateScheme.replaced_by``/``supersede()`` in favor of a plain
    ``is_active`` flag; this is the guard's new (and permanent) name.
    """
    pass


# Palette used to auto-assign Job.accent_color. Order matters for tie-breaking
# (earlier entries win). Mirrors the legacy BoardService.ACCENT_COLORS list.
JOB_ACCENT_COLOR_PALETTE = (
    '#f97066', '#f59e0b', '#14b8a6', '#8b5cf6',
    '#38bdf8', '#fb7185', '#84cc16', '#f97316',
)


def _pick_least_used_accent_color():
    """Return the color from JOB_ACCENT_COLOR_PALETTE least represented among
    active Jobs (submitted, approved, in_progress). Ties broken by palette
    order (first matching color wins).
    """
    from django.db.models import Count
    active_statuses = ('submitted', 'approved', 'in_progress')
    counts = dict.fromkeys(JOB_ACCENT_COLOR_PALETTE, 0)
    qs = Job.objects.filter(
        status__in=active_statuses,
        accent_color__in=JOB_ACCENT_COLOR_PALETTE,
    ).values('accent_color').annotate(n=Count('pk'))
    for row in qs:
        counts[row['accent_color']] = row['n']
    return min(
        JOB_ACCENT_COLOR_PALETTE,
        key=lambda c: (counts[c], JOB_ACCENT_COLOR_PALETTE.index(c)),
    )


def copy_active_modifiers(value):
    """Return a deep copy of an atom's active_modifiers snapshot list.

    Task-owned money (Phase 1): active_modifiers now holds
    ``[{key, label, percent}]`` snapshot dicts stamped at task-creation time,
    not scheme-relative modifier keys — so it deep-copies each dict rather
    than aliasing the source list. Legacy shapes can't be resolved without a
    scheme and collapse to ``[]``: a bare dict (the old
    ``{'flat_fee_price': ...}`` shape — fixed charges are now the Fee atom,
    not a RateScheme algorithm) and a list of bare modifier-key strings (the
    pre-Phase-1 snapshot shape).
    """
    if isinstance(value, dict):
        return []
    value = value or []
    if any(not isinstance(m, dict) for m in value):
        return []
    return [dict(m) for m in value]


@history(exclude=['job_id'])
class Job(AbstractWorkContainer):
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_WORK_COMPLETE = 'work_complete'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    JOB_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_WORK_COMPLETE, 'Work Complete'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    job_id = models.AutoField(primary_key=True)
    job_number = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=50, default='', blank=True)
    created_date = models.DateTimeField(default=timezone.now)
    start_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=JOB_STATUS_CHOICES, default=STATUS_DRAFT)
    # on_hold is an orthogonal pause flag, not a status: a held job keeps its
    # true pipeline position underneath. Set/cleared via JobService.hold_job /
    # release_job (and cleared by change-order acceptance).
    on_hold = models.BooleanField(default=False)
    hold_reason = models.TextField(blank=True, default='')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
    project_manager = models.ForeignKey(
        'core.User',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='managed_jobs',
        help_text='Informational owner of the job; no business-logic side effects.',
    )
    customer_po_number = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    accent_color = models.CharField(
        max_length=7, null=True, blank=True,
        help_text=(
            "Auto-assigned hex color (e.g. '#dc2626') used to identify the "
            "job in board and schedule views. Set on first save; persistent."
        ),
    )

    def clean(self):
        """Validate Job state transitions and protect immutable date fields."""
        super().clean()

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            Job.STATUS_DRAFT: [Job.STATUS_SUBMITTED, Job.STATUS_REJECTED],
            Job.STATUS_SUBMITTED: [Job.STATUS_APPROVED, Job.STATUS_REJECTED, Job.STATUS_DRAFT],
            Job.STATUS_APPROVED: [Job.STATUS_IN_PROGRESS, Job.STATUS_CANCELLED],
            Job.STATUS_IN_PROGRESS: [Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED],
            Job.STATUS_WORK_COMPLETE: [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED, Job.STATUS_IN_PROGRESS],
            Job.STATUS_REJECTED: [],  # Terminal state
            Job.STATUS_COMPLETED: [],  # Terminal state
            Job.STATUS_CANCELLED: [Job.STATUS_IN_PROGRESS],  # reactivatable (undo accidental cancel)
        }

        # Check if this is an update
        if self.pk:
            try:
                old_job = Job.objects.get(pk=self.pk)
                old_status = old_job.status

                # Protect immutable date fields
                if old_job.created_date and self.created_date != old_job.created_date:
                    self.created_date = old_job.created_date

                if old_job.start_date and self.start_date != old_job.start_date:
                    self.start_date = old_job.start_date

                reactivating = (
                    old_status in (Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED)
                    and self.status == Job.STATUS_IN_PROGRESS
                )
                if reactivating:
                    # Reactivating a closed job — it is active again, so it
                    # must not carry a completed_date.
                    self.completed_date = None
                elif old_job.completed_date and self.completed_date != old_job.completed_date:
                    self.completed_date = old_job.completed_date

                # Contact is only reassignable while the job is still a draft
                # (before it's been submitted for approval).
                if old_job.contact_id != self.contact_id and old_status != Job.STATUS_DRAFT:
                    raise ValidationError(
                        'Cannot change the contact once a Job has left draft status.'
                    )

                # If status hasn't changed, no validation needed
                if old_status == self.status:
                    return

                # Check if the transition is valid
                valid_next_states = VALID_TRANSITIONS.get(old_status, [])
                if self.status not in valid_next_states:
                    raise ValidationError(
                        f'Cannot transition Job from {old_status} to {self.status}. '
                        f'Valid transitions from {old_status} are: {", ".join(valid_next_states) if valid_next_states else "none (terminal state)"}'
                    )

            except Job.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        """Override save to validate state transitions and set dates."""
        old_status = None

        if self.accent_color is None:
            self.accent_color = _pick_least_used_accent_color()

        # Check if this is an update (not a new object)
        if self.pk:
            try:
                old_job = Job.objects.get(pk=self.pk)
                old_status = old_job.status

                # Releasing the hold — clear the hold reason
                if old_job.on_hold and not self.on_hold:
                    self.hold_reason = ''

                # Handle state transition date setting
                if old_status != self.status:
                    # Transitioning to 'approved' - set start_date
                    if self.status == Job.STATUS_APPROVED and not self.start_date:
                        self.start_date = timezone.now()

                    # Transitioning to terminal states - set completed_date
                    if self.status in [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED,
                                       Job.STATUS_REJECTED] and not self.completed_date:
                        self.completed_date = timezone.now()

            except Job.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'jobs'

    def __str__(self):
        return f"{self.job_number}"


class TaskBase(models.Model):
    """Abstract base for Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    service_item = models.ForeignKey(
        'estimates.ServiceItem', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
        help_text='Catalog identity: the ServiceItem this task was generated from.',
    )
    est_worker_time = models.DurationField(
        null=True, blank=True,
        help_text="Estimated worker time for scheduling"
    )
    est_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Estimated billable quantity in the task's own units "
            "(unit_label). Optional on Task."
        ),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    def copy_fields(self):
        """Canonical TaskBase field set for cloning to another container.

        Excludes identity, status, document provenance (``source_scheme`` —
        task-owned-money Phase 1 made it a pure provenance pointer, never
        read for money math), hierarchy, and assignee — callers add those.
        ``service_item_id`` IS included: it is catalog identity ("this task
        is an instance of this sellable service"), not document provenance,
        and must survive cloning so the QBO invoice push can resolve the
        clone's Item. The task-owned money fields (``qty_source``, ``rate``,
        ``unit_label``, ``accounting_category_id``) are the task's own price
        of record and are copied directly — they no longer route through a
        RateScheme. Returned in ``_id``/plain-value form so the dict splats
        straight into ``Task.objects.create()``-style callers; Django's
        ``.objects.create()`` accepts the ``_id`` form too. ``active_modifiers``
        is deep-copied here to keep raw-create callers safe from
        shared-reference bugs.
        """
        return dict(
            name=self.name,
            description=self.description,
            sort_order=self.sort_order,
            est_worker_time=self.est_worker_time,
            est_qty=self.est_qty,
            qty_source=self.qty_source,
            rate=self.rate,
            unit_label=self.unit_label,
            accounting_category_id=self.accounting_category_id,
            service_item_id=self.service_item_id,
            active_modifiers=copy_active_modifiers(self.active_modifiers),
        )


# worker_queue is excluded from history: board-queue position is cosmetic
# (same class as sort_order's freeze exemption), and the bump-to-front on
# every clock-in would spam the audit trail.
@history(exclude=['task_id', 'worker_queue'])
class Task(TaskBase):
    """Work task on a Job. Has lifecycle, hierarchy, bleps."""
    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_BLOCKED = 'blocked'
    STATUS_COMPLETE = 'complete'
    STATUS_CANCELLED = 'cancelled'

    TASK_STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_BLOCKED, 'Blocked'),
        (STATUS_COMPLETE, 'Complete'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    VALID_TRANSITIONS = {
        STATUS_PENDING: [STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_IN_PROGRESS: [STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_BLOCKED: [STATUS_IN_PROGRESS, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_COMPLETE: [],
        STATUS_CANCELLED: [],
    }

    task_id = models.AutoField(primary_key=True)
    parent_task = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtasks'
    )
    assignee = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
    blocked_reason = models.TextField(blank=True, default='')
    worker_queue = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Position in assignee's work queue on the board"
    )
    # source_scheme: provenance ONLY (task-owned-money Phase 1) — the preset
    # this task was last stamped from. Never read for money math; the task's
    # own qty_source/rate/unit_label/accounting_category fields below are the
    # price of record. Nullable/SET_NULL so deleting a preset never blocks on
    # its stamped tasks.
    source_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stamped_tasks',
    )
    # Task-owned money (task-owned-money Phase 1, Task 1): snapshot-at-stamp
    # fields that will become the price of record. qty_source strings match
    # RateScheme.ELAPSED_TIME / ENTERED_QTY so the data migration is a copy.
    QTY_ELAPSED = 'elapsed_time'
    QTY_ENTERED = 'entered_qty'
    QTY_SOURCE_CHOICES = [(QTY_ELAPSED, 'Timeslips'), (QTY_ENTERED, 'Entered quantity')]

    qty_source = models.CharField(
        max_length=20, choices=QTY_SOURCE_CHOICES, default=QTY_ENTERED,
    )
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unit_label = models.CharField(max_length=50, default='none')
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    actual_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Worker-entered actual quantity for ENTERED_QTY schemes. "
            "Null for ELAPSED_TIME (qty derived from bleps)."
        ),
    )
    # est_qty inherited from TaskBase (nullable on Task).

    # Quantity structure (spec §9, task-owned-money Phase 4 Task 1): only
    # functional on a subtask (parent_task set) — inert on a top-level row,
    # and rendered only on subtask forms. DB default True; the unit-keyed
    # default (True when the parent's unit_label == 'ea', else False) is
    # applied at subtask-CREATION time by the service layer, not here — this
    # is just the column's fallback for rows that bypass that path.
    qty_scales_with_parent = models.BooleanField(
        default=True,
        help_text=(
            "Subtask only: when true, this task's raw est_qty/"
            "est_worker_time are PER-UNIT and multiply by the parent's "
            "est_qty to get the expected total (Task.expected_qty() / "
            "expected_worker_time()). When false, the raw values are "
            "already a per-batch total (multiplier 1). Inert on a "
            "top-level task (no parent)."
        ),
    )

    class Meta:
        db_table = 'tasks'

    def clean(self):
        if self.pk:
            old_status = Task.objects.get(pk=self.pk).status
            if old_status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old_status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        {'status': f"Cannot transition from '{old_status}' to '{self.status}'."}
                    )
        # The "assigned work needs an estimated worker time" invariant lives
        # on the EXPLICIT assign gestures (TaskService.assign / create_direct
        # / update_task), NOT here: auto-assign on start_work deliberately
        # claims a task for its first worker without demanding a duration
        # mid-clock-in, so assignee-without-est-time is a legal model state.
        # charge guard removed in B4. Task-owned money (Phase 1): the task
        # owns its money fields (qty_source/rate/unit_label/
        # accounting_category/active_modifiers) directly; source_scheme is
        # nullable (SET_NULL on preset deletion) and provenance-only — no
        # NOT-NULL invariant to enforce here anymore.

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                max_order = Task.objects.filter(
                    job=self.job
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # No estimate/CO source row may outlive its atom.
        from apps.estimates.claims import purge_source_rows_for_atom
        pk = self.pk
        result = super().delete(*args, **kwargs)
        purge_source_rows_for_atom('task', pk)
        return result

    @property
    def effective_accounting_category(self):
        return self.accounting_category

    def stamp_from_scheme(self, scheme, modifier_keys=None):
        """Copy a RateScheme preset's money fields onto this task (task-owned
        money Phase 1). Every creation path calls this BEFORE the task's
        first save, so the task gets its own permanent copy of the preset's
        pricing — later edits to the preset (or its supersession/retirement)
        never reprice an already-stamped task.

        Sets: ``qty_source`` (from ``scheme.algorithm``), ``rate``,
        ``unit_label``, ``accounting_category``, ``source_scheme`` (provenance
        only — never read for money math, see the field's docstring), and
        ``active_modifiers`` — resolved from ``modifier_keys`` (a list of
        ``scheme.modifiers`` ``key`` strings, the same convention as
        ``RateScheme.effective_rate``'s ``active_modifiers`` arg) into full
        ``{key, label, percent}`` snapshot dicts. ``modifier_keys=None``
        (the default) activates no modifiers — callers that want a
        ServiceItem's predefined defaults pass
        ``modifier_keys=service_item.default_active_modifiers`` explicitly.

        Raises ``ValueError`` for percentage schemes: those are document-level
        adjustments (rush/discount lines), not task-billing presets.
        """
        if scheme.algorithm == RateScheme.PERCENTAGE:
            raise ValueError(
                'Percentage services are document adjustments and cannot '
                'stamp a task.'
            )
        keys = modifier_keys or []
        self.qty_source = scheme.algorithm
        self.rate = scheme.rate
        self.unit_label = scheme.unit_label
        self.accounting_category = scheme.accounting_category
        self.source_scheme = scheme
        self.active_modifiers = [
            dict(m) for m in scheme.modifiers if m.get('key') in keys
        ]

    def effective_rate(self):
        """Per-unit rate: own ``rate`` plus own ``active_modifiers``
        surcharges (task-owned-money Phase 1 — no RateScheme lookup)."""
        if self.rate is None:
            return Decimal('0.00')
        pct = Decimal('0')
        for m in (self.active_modifiers or []):
            # The real gate is TaskSerializer.validate_active_modifiers; this
            # is belt-and-braces so one bad legacy/migrated row degrades the
            # price instead of 500ing every list/detail read.
            if not isinstance(m, dict):
                continue
            pct += Decimal(str(m.get('percent', 0)))
        return (self.rate * (1 + pct / 100)).quantize(Decimal('0.01'))

    def get_actual_qty(self):
        """Resolve actual quantity from own qty_source (task-owned-money
        Phase 1 — no RateScheme lookup)."""
        if self.qty_source == self.QTY_ELAPSED:
            total = sum(
                (b.elapsed for b in self.blep_set.all() if b.elapsed is not None),
                timedelta(),
            )
            # Quantize to 2 places: a raw seconds/3600 division is
            # non-terminating (~28 digits) and overflows the line item qty
            # field (max_digits=10) when carried into the invoice wizard.
            return timedelta_to_hours(total).quantize(Decimal('0.01'))
        return self.actual_qty or Decimal('0')

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this task.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface shared
        with Material.
        """
        return (self.get_actual_qty() * self.effective_rate()).quantize(Decimal('0.01'))

    def compute_estimate_amount(self, active_modifiers=None):
        """Estimate-side amount: bills est_qty, not actuals.

        The estimate wizard projects what the job is *expected* to cost, so it
        uses est_qty. (compute_amount() resolves qty from actuals — bleps /
        actual_qty — which is what the *invoice* wizard wants.) Ignores the
        active_modifiers argument (uses self.active_modifiers) to match the
        BillableAtom interface.
        """
        return ((self.est_qty or Decimal('0')) * self.effective_rate()).quantize(Decimal('0.01'))

    @property
    def is_parent(self):
        """True when this task has ≥1 subtask — the non-startable state
        (spec §9 rule 1). Delegates PM functions (start/blep/assign) to its
        children; only the children's own bleps/status move."""
        return self.subtasks.exists()

    def _parent_multiplier(self):
        """The ONE multiplier used by both `expected_qty()` and
        `expected_worker_time()` — no other code may re-derive it (spec §9
        rule 3).

        1 for a top-level task (no parent — the flag is inert there) and for
        a flag-false subtask (its raw estimate is already a per-batch
        total). For a flag-true subtask, the parent's own `est_qty` — the
        parent IS the entered quantity and the multiplier is unit-agnostic
        (no 'ea' requirement, spec §9 rule 2). A flag-true subtask whose
        parent has no `est_qty` yet stamped falls back to 1 (nothing to
        multiply by yet) rather than raising or propagating None.
        """
        if self.parent_task_id is None or not self.qty_scales_with_parent:
            return Decimal('1')
        return self.parent_task.est_qty or Decimal('1')

    def expected_qty(self):
        """Expected total quantity: raw `est_qty` × `_parent_multiplier()`
        (spec §9 rules 2/3). None when this task carries no `est_qty` of its
        own — there's nothing to expect."""
        if self.est_qty is None:
            return None
        return self.est_qty * self._parent_multiplier()

    def expected_worker_time(self):
        """Expected total worker time: raw `est_worker_time` ×
        `_parent_multiplier()`. Schedule bars, expected-vs-logged displays,
        and estimate composition all read the expectation through here —
        never through raw `est_worker_time` directly (spec §9 rule 3). None
        when this task carries no `est_worker_time` of its own."""
        if self.est_worker_time is None:
            return None
        return self.est_worker_time * float(self._parent_multiplier())

    def derived_unit_price(self):
        """Parent's per-unit price derived from its children (spec §9 rule
        4): Σ flag-true children (`est_qty` × `effective_rate()`) — already
        per-unit, so they add straight in — plus Σ flag-false children
        (`est_qty` × `effective_rate()`), a per-batch total, divided by this
        parent's own `est_qty` to spread it per unit. Quantized to cents
        only at the very end (child amounts are NOT individually
        quantized first).

        Returns None when this task is not a parent (no subtasks) — there
        is nothing to derive.

        Decision (documented per plan, not left implicit): when the
        flag-false sum is non-zero but this parent's own `est_qty` is
        falsy (None or 0), the divisor is treated as 1 rather than raising
        or returning None — there's no unit count yet to spread the batch
        total over, so the raw flag-false total stands as-is until the
        parent gets an `est_qty`.
        """
        if not self.is_parent:
            return None
        per_unit_total = Decimal('0')
        batch_total = Decimal('0')
        for child in self.subtasks.all():
            child_amount = (child.est_qty or Decimal('0')) * child.effective_rate()
            if child.qty_scales_with_parent:
                per_unit_total += child_amount
            else:
                batch_total += child_amount
        divisor = self.est_qty or Decimal('1')
        return (per_unit_total + batch_total / divisor).quantize(Decimal('0.01'))


class Blep(models.Model):
    blep_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('core.User', on_delete=models.PROTECT)
    task = models.ForeignKey(Task, on_delete=models.PROTECT)  # Changed from CASCADE - protect audit trail
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bleps'

    @property
    def elapsed(self):
        """Return elapsed timedelta, or None if no start_time."""
        if not self.start_time:
            return None
        end = self.end_time or timezone.now()
        return end - self.start_time

    @property
    def elapsed_display(self):
        """Human-readable elapsed time string."""
        delta = self.elapsed
        if delta is None:
            return "-"
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def save(self, *args, **kwargs):
        self.start_time = floor_to_minute(self.start_time)
        self.end_time = floor_to_minute(self.end_time)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Blep {self.pk} for Task {self.task.pk}"


class RateScheme(models.Model):
    ELAPSED_TIME = 'elapsed_time'
    ENTERED_QTY = 'entered_qty'
    PERCENTAGE = 'percentage'

    ALGORITHM_CHOICES = [
        (ELAPSED_TIME, 'Based on time worked'),
        (ENTERED_QTY, 'Worker enters quantity'),
        (PERCENTAGE, 'Percentage of other lines'),
    ]

    rate_scheme_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')
    algorithm = models.CharField(max_length=20, choices=ALGORITHM_CHOICES)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    unit_label = models.CharField(max_length=50)
    modifiers = models.JSONField(default=list, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT,
    )
    # Retirement flag (task-owned-money Phase 1, Task 4) — replaces the old
    # replaced_by/replaced_at supersession mechanism. RateSchemes are freely
    # editable presets now: a Task stamps its own permanent copy of the
    # preset's money fields at creation time (Task.stamp_from_scheme), so
    # editing (or retiring, or deleting) a preset never reprices or orphans
    # a task that already stamped from it. is_active is read only by the
    # creation-time guard (SchemeInactiveError) — it hides the preset from
    # *new* stampings, nothing else.
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'rate_schemes'

    def _normalize_modifiers(self):
        """Drop fully-blank modifier rows (no key/label, no percent) — the
        editor's untouched "add modifier" row is a no-op, not data."""
        self.modifiers = [
            m for m in (self.modifiers or [])
            if (m.get('key') or '').strip() or (m.get('label') or '').strip()
            or m.get('percent')
        ]

    def clean(self):
        super().clean()
        self._normalize_modifiers()
        if any(not (m.get('key') or '').strip() for m in self.modifiers):
            raise ValidationError({
                'modifiers': 'Each modifier needs a name (key); a percent '
                             'without one can never be activated.',
            })
        if self.accounting_category_id is None:
            raise ValidationError({
                'accounting_category': 'Required: every RateScheme must have an AccountingCategory.',
            })
        if self.algorithm != self.PERCENTAGE and self.rate is not None and self.rate < 0:
            raise ValidationError({'rate': 'Only percentage services may have a negative rate.'})
        if self.algorithm == self.ELAPSED_TIME and self.unit_label != HOUR_UNIT:
            raise ValidationError({
                'unit_label': 'Time-based schemes are billed in hours; '
                              f'unit must be "{HOUR_UNIT}".',
            })

    def save(self, *args, **kwargs):
        # Normalize on create too — full_clean below covers both create and update.
        self._normalize_modifiers()
        # Belt-and-braces: ensure clean() runs even on bare .save() calls.
        self.full_clean()
        super().save(*args, **kwargs)


    def effective_rate(self, active_modifiers=None):
        """Compute the per-unit rate.

        For time/qty schemes, apply additive modifier surcharges.

        Preset preview only — never called with a task (task-owned-money
        Phase 1: Task.effective_rate() computes from the task's own
        rate/active_modifiers instead). Retained for the RateSchemeManager
        preview and the serializer detail view.
        """
        if self.algorithm == self.PERCENTAGE:
            raise ValueError('percentage services compute at the document layer, not per-unit')
        modifier_percent = sum(
            m['percent'] for m in self.modifiers if m['key'] in (active_modifiers or [])
        )
        # Quantize to cents: a percentage modifier divides by 100, so the
        # product can carry >2 places (99.99 × 1.05 = 104.9895). This is a
        # per-unit money rate that becomes a line item price (2-decimal field)
        # — trim at the source so every caller is safe, not just the ones that
        # remembered to .quantize().
        rate = self.rate * (1 + Decimal(modifier_percent) / 100)
        return rate.quantize(Decimal('0.01'))

    def compute_charge(self, qty, active_modifiers=None):
        """Compute total charge for the given quantity.

        Preset preview only — never called with a task (task-owned-money
        Phase 1: Task.compute_amount()/compute_estimate_amount() compute
        from the task's own fields instead).
        """
        return qty * self.effective_rate(active_modifiers)

    def get_actual_qty(self, task):
        """Resolve actual quantity based on algorithm.

        Preset preview only — never called with a task (task-owned-money
        Phase 1: Task.get_actual_qty() reads the task's own qty_source
        instead).
        """
        if self.algorithm == self.PERCENTAGE:
            raise ValueError('percentage services are document adjustments, not task billing')
        if self.algorithm == self.ELAPSED_TIME:
            from datetime import timedelta
            from apps.core.timeutils import timedelta_to_hours
            total = sum(
                (b.elapsed for b in task.blep_set.all() if b.elapsed is not None),
                timedelta(),
            )
            # Quantize to 2 places: a raw seconds/3600 division is
            # non-terminating (~28 digits) and overflows the line item qty
            # field (max_digits=10) when carried into the invoice wizard.
            return timedelta_to_hours(total).quantize(Decimal('0.01'))
        elif self.algorithm == self.ENTERED_QTY:
            return task.actual_qty or Decimal('0')
        else:
            raise ValueError(f'unknown algorithm: {self.algorithm}')

    def get_modifier_inputs(self):
        """Return modifiers list for UI rendering."""
        return list(self.modifiers)

    def is_referenced(self):
        """True if any Task has stamped from this scheme, or any ServiceItem
        points at it. Display only (outdated-schemes UI, reference counts) —
        no longer gates edits or deletes (task-owned-money Phase 1, Task 4):
        stamped tasks own a permanent copy of their money fields, and
        ServiceItem's FK is still PROTECT at the DB level."""
        from apps.estimates.models import ServiceItem
        if self.stamped_tasks.exists():
            return True
        if ServiceItem.objects.filter(rate_scheme=self).exists():
            return True
        return False

    def reference_counts(self):
        """Return reference counts for the outdated-schemes UI."""
        from apps.estimates.models import ServiceItem
        return {
            'task_count': self.stamped_tasks.count(),
            'service_item_count': ServiceItem.objects.filter(rate_scheme=self).count(),
        }

    def __str__(self):
        return self.name


class Fee(models.Model):
    """A fixed charge owned by the Job — the crystallized form of an accepted
    hand-line. Frozen quantity × unit_rate; no actual lifecycle. `unit_rate`
    may be negative (a credit is a negative Fee) but never zero — enforced
    in FeeService, not here (see FeeService.create_on_job/update)."""
    fee_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='fees')
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_rate = models.DecimalField(max_digits=10, decimal_places=2)
    accounting_category = models.ForeignKey('core.AccountingCategory', on_delete=models.PROTECT)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'fees'

    def compute_amount(self, active_modifiers=None):
        return (self.quantity * self.unit_rate).quantize(Decimal('0.01'))

    def delete(self, *args, **kwargs):
        # No estimate/CO source row may outlive its atom.
        from apps.estimates.claims import purge_source_rows_for_atom
        pk = self.pk
        result = super().delete(*args, **kwargs)
        purge_source_rows_for_atom('fee', pk)
        return result

    @property
    def effective_accounting_category(self):
        return self.accounting_category

    @property
    def units(self):
        return 'none'

    def __str__(self):
        return f'Fee {self.pk}: {self.description} ({self.quantity}×{self.unit_rate})'


class BlepChangeRequest(TimeChangeRequest):
    request_id = models.AutoField(primary_key=True)
    blep = models.ForeignKey('jobs.Blep', on_delete=models.PROTECT,
                             null=True, blank=True, related_name='change_requests')
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT,
                             null=True, blank=True, related_name='+')

    class Meta(TimeChangeRequest.Meta):
        abstract = False
        db_table = 'blep_change_requests'

    @property
    def target_user(self):
        return self.blep.user if self.blep_id else self.requester

    def would_conflict(self):
        from apps.core.time_integrity import enclosing_shift_for_blep
        return enclosing_shift_for_blep(
            self.target_user, self.requested_start, self.requested_end) is None

    def conflicting_records(self):
        """When no shift encloses the requested time, the worker's shifts that
        overlap it are the candidates a manager would widen. Empty when an
        enclosing shift already exists (no conflict) or none overlaps."""
        from apps.core.time_integrity import (enclosing_shift_for_blep,
                                              overlapping_shifts_for_blep)
        if enclosing_shift_for_blep(self.target_user, self.requested_start,
                                    self.requested_end) is not None:
            return []
        return list(overlapping_shifts_for_blep(
            self.target_user, self.requested_start, self.requested_end))

    def apply_requested(self, reviewer):
        from apps.jobs.services import BlepService
        if self.blep_id:
            return BlepService.update(self.blep, actor=reviewer,
                                      start_time=self.requested_start,
                                      end_time=self.requested_end)
        return BlepService.create_historical(
            actor=reviewer, task=self.task,
            start_time=self.requested_start, end_time=self.requested_end,
            target_user=self.requester)



