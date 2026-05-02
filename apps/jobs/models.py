from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import AbstractWorkContainer
from apps.core.history import history


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
        (STATUS_IN_PROGRESS, 'In Progress'),  # NEW — between approved and work_complete
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
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
    customer_po_number = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)

    def clean(self):
        """Validate Job state transitions and protect immutable date fields."""
        super().clean()

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            Job.STATUS_DRAFT: [Job.STATUS_SUBMITTED, Job.STATUS_REJECTED],
            Job.STATUS_SUBMITTED: [Job.STATUS_APPROVED, Job.STATUS_REJECTED],
            Job.STATUS_APPROVED: [Job.STATUS_IN_PROGRESS, Job.STATUS_CANCELLED],
            Job.STATUS_IN_PROGRESS: [Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED],  # NEW
            Job.STATUS_WORK_COMPLETE: [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED],
            Job.STATUS_REJECTED: [],  # Terminal state
            Job.STATUS_COMPLETED: [],  # Terminal state
            Job.STATUS_CANCELLED: [],  # Terminal state
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

                if old_job.completed_date and self.completed_date != old_job.completed_date:
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
                    if self.status in [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED] and not self.completed_date:
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
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    est_worker_time = models.DurationField(
        null=True, blank=True,
        help_text="Estimated worker time for scheduling"
    )
    units = models.CharField(max_length=50, default='none')
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Type of line item this task produces when mapped directly"
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
        'jobs.RateScheme', on_delete=models.PROTECT, null=True, blank=True,
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    estimated_billable_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )

    class Meta:
        db_table = 'plan_tasks'

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
        Returns Decimal('0.00') when rate_scheme or estimated_billable_qty is unset
        — i.e., billing not yet configured.
        """
        if not self.rate_scheme_id or self.estimated_billable_qty is None:
            return Decimal('0.00')
        return self.rate_scheme.compute_charge(
            self.estimated_billable_qty, self.active_modifiers,
        )

    def effective_rate(self):
        if not self.rate_scheme_id:
            return None
        return self.rate_scheme.effective_rate(self.active_modifiers)


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
    source_plan_charge = models.OneToOneField(
        'jobs.PlanCharge',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='carried_task',
        help_text="PlanCharge this task was carried over from (carry-over idempotency)"
    )
    source_plan_task = models.OneToOneField(
        'jobs.PlanTask',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='carried_task_new',  # temporary; renamed to 'carried_task' after old field is dropped in Task 12
    )
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
    blocked_reason = models.TextField(blank=True, default='')
    worker_queue = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Position in assignee's work queue on the board"
    )

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
    minimum_charge = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    modifiers = models.JSONField(default=list, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT, null=True, blank=True,
    )

    class Meta:
        db_table = 'rate_schemes'

    def effective_rate(self, active_modifiers=None):
        """Compute rate with additive modifier surcharges."""
        modifier_percent = sum(
            m['percent'] for m in self.modifiers if m['key'] in (active_modifiers or [])
        )
        return self.rate * (1 + Decimal(modifier_percent) / 100)

    def compute_charge(self, qty, active_modifiers=None):
        """Compute total charge for the given quantity."""
        total = qty * self.effective_rate(active_modifiers)
        if self.minimum_charge:
            total = max(total, self.minimum_charge)
        return total

    def get_actual_qty(self, task):
        """Resolve actual quantity based on algorithm."""
        if self.algorithm == self.ELAPSED_TIME:
            total_seconds = sum(
                b.elapsed.total_seconds() for b in task.blep_set.all() if b.elapsed is not None
            )
            return Decimal(total_seconds) / 3600
        elif self.algorithm == self.ENTERED_QTY:
            return task.charge.actuals.get('qty', 0)
        else:  # FLAT_FEE
            return Decimal('1')

    def get_modifier_inputs(self):
        """Return modifiers list for UI rendering."""
        return list(self.modifiers)

    def __str__(self):
        return self.name


class TaskCharge(models.Model):
    """The filled-in billing form for a Task. One per Task (OneToOne)."""
    task_charge_id = models.AutoField(primary_key=True)
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name='charge')
    rate_scheme = models.ForeignKey(RateScheme, on_delete=models.PROTECT)
    active_modifiers = models.JSONField(default=list, blank=True)
    actuals = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'task_charges'

    def __str__(self):
        return f"Charge for {self.task}"

    def compute(self):
        """Compute charge using scheme's algorithm and this charge's specifics."""
        qty = self.rate_scheme.get_actual_qty(self.task)
        return self.rate_scheme.compute_charge(qty, self.active_modifiers)

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this charge.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface shared with
        Material/PlanMaterial.
        """
        return self.compute()

    def effective_rate(self):
        return self.rate_scheme.effective_rate(self.active_modifiers)

    def has_actuals(self):
        if self.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
            return bool(self.actuals.get('qty'))
        return True  # elapsed_time and flat_fee don't need manual entry


class PlanCharge(models.Model):
    """Same shape as TaskCharge but for PlanTask (worksheet/estimate stage). No actuals."""
    plan_charge_id = models.AutoField(primary_key=True)
    plan_task = models.OneToOneField(PlanTask, on_delete=models.CASCADE, related_name='charge')
    rate_scheme = models.ForeignKey(RateScheme, on_delete=models.PROTECT)
    active_modifiers = models.JSONField(default=list, blank=True)
    estimated_billable_qty = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'plan_charges'

    def __str__(self):
        return f"Charge for {self.plan_task}"

    def compute(self):
        return self.rate_scheme.compute_charge(self.estimated_billable_qty, self.active_modifiers)

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this charge.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface.
        """
        return self.compute()

    def effective_rate(self):
        return self.rate_scheme.effective_rate(self.active_modifiers)
