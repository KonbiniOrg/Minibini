from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import AbstractWorkContainer, TimeChangeRequest
from apps.core.history import history
from apps.core.timeutils import floor_to_minute


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
    """Return a copy of an atom's active_modifiers JSON, preserving its shape.

    flat_fee atoms store a dict ({'flat_fee_price': str}); other algorithms
    store a list of modifier keys. A bare list(value) would silently reduce a
    dict to a list of its keys, dropping the price.
    """
    if isinstance(value, dict):
        return dict(value)
    return list(value or [])


@history(exclude=['job_id'])
class Job(AbstractWorkContainer):
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_ON_HOLD = 'on_hold'
    STATUS_WORK_COMPLETE = 'work_complete'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    JOB_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_IN_PROGRESS, 'In Progress'),  # NEW — between approved and work_complete
        (STATUS_ON_HOLD, 'On Hold'),
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
    hold_reason = models.TextField(blank=True, default='')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
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
            Job.STATUS_APPROVED: [Job.STATUS_IN_PROGRESS, Job.STATUS_ON_HOLD, Job.STATUS_CANCELLED],
            Job.STATUS_IN_PROGRESS: [Job.STATUS_WORK_COMPLETE, Job.STATUS_ON_HOLD, Job.STATUS_CANCELLED],  # NEW
            Job.STATUS_ON_HOLD: [Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS, Job.STATUS_CANCELLED],
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

                # Handle state transition date setting
                if old_status != self.status:
                    # Transitioning to 'approved' - set start_date
                    if self.status == Job.STATUS_APPROVED and not self.start_date:
                        self.start_date = timezone.now()

                    # Transitioning to terminal states - set completed_date
                    if self.status in [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED,
                                       Job.STATUS_REJECTED] and not self.completed_date:
                        self.completed_date = timezone.now()

                    # Leaving on_hold into an active status — clear the hold reason
                    if old_status == Job.STATUS_ON_HOLD and self.status in (
                        Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS
                    ):
                        self.hold_reason = ''

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
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    est_worker_time = models.DurationField(
        null=True, blank=True,
        help_text="Estimated worker time for scheduling"
    )
    est_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Estimated billable quantity in the rate scheme's units. "
            "Required at the application layer on PlanTask; optional on Task."
        ),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class PlanTask(TaskBase):
    """Planning task on an EstWorksheet. No lifecycle, no hierarchy, no bleps."""
    plan_task_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_tasks'
    )
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT,
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    # est_qty is now inherited from TaskBase (nullable at DB level; PlanTask.clean()
    # enforces non-null in Phase B).

    class Meta:
        db_table = 'plan_tasks'

    def clean(self):
        super().clean()
        if self.est_qty is None:
            raise ValidationError({
                'est_qty': 'Required: every PlanTask must have an estimated quantity.',
            })

    def save(self, *args, **kwargs):
        """Auto-assign sort_order at the worksheet level."""
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                max_order = PlanTask.objects.filter(
                    est_worksheet=self.est_worksheet
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this plan task.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface.
        Returns Decimal('0.00') when rate_scheme or est_qty is unset
        — i.e., billing not yet configured.
        """
        if not self.rate_scheme_id or self.est_qty is None:
            return Decimal('0.00')
        charge = self.rate_scheme.compute_charge(
            self.est_qty, self.active_modifiers,
        )
        return charge.quantize(Decimal('0.01'))

    def effective_rate(self):
        if not self.rate_scheme_id:
            return None
        return self.rate_scheme.effective_rate(self.active_modifiers)

    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category


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
    source_template = models.ForeignKey(
        'estimates.TaskTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="TaskTemplate this task was created from"
    )
    source_plan_task = models.OneToOneField(
        'jobs.PlanTask',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='carried_task',
        help_text="PlanTask this task was carried over from (carry-over idempotency)",
    )
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
    blocked_reason = models.TextField(blank=True, default='')
    worker_queue = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Position in assignee's work queue on the board"
    )
    # Billing fields (Phase B: rate_scheme is NOT NULL at the DB level).
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.PROTECT,
        related_name='task_set',
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    actual_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Worker-entered actual quantity for ENTERED_QTY schemes. "
            "Null for ELAPSED_TIME (qty derived from bleps) and FLAT_FEE."
        ),
    )
    # est_qty inherited from TaskBase (nullable on Task).

    class Meta:
        db_table = 'tasks'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk:
            old_status = Task.objects.get(pk=self.pk).status
            if old_status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old_status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        {'status': f"Cannot transition from '{old_status}' to '{self.status}'."}
                    )
        # An assigned task must carry an estimated worker time: assigned work
        # has to be schedulable, and it can't be scheduled without a duration.
        # TaskService.assign enforces the same rule on the board's update()
        # path, which bypasses full_clean().
        if self.assignee_id and not self.est_worker_time:
            raise ValidationError({
                'est_worker_time':
                    'An assigned task must have an estimated worker time.',
            })
        # charge guard removed in B4. rate_scheme is NOT NULL at DB level (B8).

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

    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this task.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface shared
        with PlanTask/Material/PlanMaterial.
        """
        qty = self.rate_scheme.get_actual_qty(self)
        charge = self.rate_scheme.compute_charge(qty, self.active_modifiers)
        return charge.quantize(Decimal('0.01'))

    def effective_rate(self):
        return self.rate_scheme.effective_rate(self.active_modifiers)


class Blep(models.Model):
    blep_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('core.User', on_delete=models.PROTECT, null=True, blank=True)
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
    FLAT_FEE = 'flat_fee'

    ALGORITHM_CHOICES = [
        (ELAPSED_TIME, 'Based on time worked'),
        (ENTERED_QTY, 'Worker enters quantity'),
        (FLAT_FEE, 'Fixed charge'),
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
    replaced_by = models.ForeignKey(
        'self', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='replaces',
    )
    replaced_at = models.DateTimeField(null=True, blank=True)

    # Fields that, once any reference exists, may not be changed
    # (replaced_by and replaced_at are the only allowed mutations).
    FROZEN_FIELDS = (
        'name', 'description', 'algorithm', 'rate', 'unit_label',
        'modifiers', 'accounting_category',
    )

    class Meta:
        db_table = 'rate_schemes'

    def clean(self):
        super().clean()
        if self.accounting_category_id is None:
            from django.core.exceptions import ValidationError
            raise ValidationError({
                'accounting_category': 'Required: every RateScheme must have an AccountingCategory.',
            })
        if self.pk and self.is_referenced():
            old = RateScheme.objects.get(pk=self.pk)
            changed = [
                f for f in self.FROZEN_FIELDS
                if getattr(self, f) != getattr(old, f)
            ]
            if changed:
                from django.core.exceptions import ValidationError
                raise ValidationError({
                    f: 'Scheme is referenced; create a new version instead of editing.'
                    for f in changed
                })

    def save(self, *args, **kwargs):
        # Belt-and-braces: ensure clean() runs even on bare .save() calls.
        if self.pk:
            self.full_clean()
        super().save(*args, **kwargs)

    @staticmethod
    def _flat_fee_price(active_modifiers):
        """Pull the flat-fee unit price out of an atom's active_modifiers JSON.

        flat_fee atoms store the price as {'flat_fee_price': <str>}; every
        other algorithm stores a list of modifier keys. Returns a Decimal, or
        None when no price is present (caller falls back to the scheme rate).
        """
        if isinstance(active_modifiers, dict):
            raw = active_modifiers.get('flat_fee_price')
            if raw is not None and raw != '':
                return Decimal(str(raw))
        return None

    def effective_rate(self, active_modifiers=None):
        """Compute the per-unit rate.

        For flat_fee the per-unit price rides on the atom (active_modifiers);
        self.rate is only a fallback. For time/qty schemes, apply additive
        modifier surcharges.
        """
        if self.algorithm == self.FLAT_FEE:
            price = self._flat_fee_price(active_modifiers)
            return price if price is not None else self.rate
        modifier_percent = sum(
            m['percent'] for m in self.modifiers if m['key'] in (active_modifiers or [])
        )
        return self.rate * (1 + Decimal(modifier_percent) / 100)

    def compute_charge(self, qty, active_modifiers=None):
        """Compute total charge for the given quantity."""
        return qty * self.effective_rate(active_modifiers)

    def get_actual_qty(self, task):
        """Resolve actual quantity based on algorithm."""
        if self.algorithm == self.ELAPSED_TIME:
            total_seconds = sum(
                b.elapsed.total_seconds() for b in task.blep_set.all() if b.elapsed is not None
            )
            # Quantize to 2 places: a raw seconds/3600 division is
            # non-terminating (~28 digits) and overflows the line item qty
            # field (max_digits=10) when carried into the invoice wizard.
            return (Decimal(str(total_seconds)) / 3600).quantize(Decimal('0.01'))
        elif self.algorithm == self.ENTERED_QTY:
            return task.actual_qty or Decimal('0')
        else:  # FLAT_FEE
            # flat_fee bills a fixed unit price x estimated quantity. est_qty
            # comes from the worksheet, carried to the Task and editable there;
            # fall back to 1 for a genuine one-off fee with no quantity.
            return task.est_qty if task.est_qty is not None else Decimal('1')

    def get_modifier_inputs(self):
        """Return modifiers list for UI rendering."""
        return list(self.modifiers)

    def is_referenced(self):
        """True if any PlanTask, Task, or TaskTemplate points at this scheme."""
        from apps.estimates.models import TaskTemplate
        if PlanTask.objects.filter(rate_scheme=self).exists():
            return True
        if Task.objects.filter(rate_scheme=self).exists():
            return True
        if TaskTemplate.objects.filter(rate_scheme=self).exists():
            return True
        return False

    def reference_counts(self):
        """Return reference counts for the outdated-schemes UI."""
        from apps.estimates.models import TaskTemplate
        return {
            'plan_task_count': PlanTask.objects.filter(rate_scheme=self).count(),
            'task_count': Task.objects.filter(rate_scheme=self).count(),
            'task_template_count': TaskTemplate.objects.filter(rate_scheme=self).count(),
        }

    def supersede(self, **overrides):
        """Create a new RateScheme inheriting this one's fields, set replaced_by/at.

        The old row is renamed in place to "<orig> (v{N})" where N is the count
        of pre-existing predecessors + 1. The new row takes the original name
        (or whatever the caller overrides). This preserves the DB-level unique
        constraint on `name` without needing a partial-unique index.
        """
        from django.db import transaction
        from django.utils import timezone

        if self.replaced_by is not None:
            raise ValueError('Cannot supersede an already-superseded scheme.')

        # Count predecessors (the chain leading to self). Each scheme has at
        # most one direct replacement, so the chain is linear.
        version = 1
        pred = self.replaces.first()
        while pred is not None:
            version += 1
            pred = pred.replaces.first()
        retired_name = f'{self.name} (v{version})'

        defaults = {
            'name': self.name,
            'description': self.description,
            'algorithm': self.algorithm,
            'rate': self.rate,
            'unit_label': self.unit_label,
            'modifiers': list(self.modifiers),
            'accounting_category': self.accounting_category,
        }
        defaults.update(overrides)

        with transaction.atomic():
            # Rename old first to free the unique name slot for the new row.
            # update() bypasses full_clean(), which is what we want — `name`
            # is in FROZEN_FIELDS, but renaming during supersede is the one
            # exception, alongside replaced_by/replaced_at.
            RateScheme.objects.filter(pk=self.pk).update(name=retired_name)
            self.name = retired_name  # keep the in-memory instance in sync
            new = RateScheme.objects.create(**defaults)
            replaced_at = timezone.now()
            RateScheme.objects.filter(pk=self.pk).update(
                replaced_by=new, replaced_at=replaced_at,
            )
            self.replaced_by = new
            self.replaced_at = replaced_at
        return new

    def __str__(self):
        return self.name


@history(exclude=['request_id'])
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



