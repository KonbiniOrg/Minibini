from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import AbstractWorkContainer
from apps.core.history import history


@history(exclude=['job_id'])
class Job(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    JOB_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
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
            Job.STATUS_APPROVED: [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED],
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


@history(exclude=['work_order_id'])
class WorkOrder(AbstractWorkContainer):
    STATUS_INCOMPLETE = 'incomplete'
    STATUS_BLOCKED = 'blocked'
    STATUS_COMPLETE = 'complete'

    WORK_ORDER_STATUS_CHOICES = [
        (STATUS_INCOMPLETE, 'Incomplete'),
        (STATUS_BLOCKED, 'Blocked'),
        (STATUS_COMPLETE, 'Complete'),
    ]

    VALID_TRANSITIONS = {
        STATUS_INCOMPLETE: [STATUS_BLOCKED, STATUS_COMPLETE],
        STATUS_BLOCKED: [STATUS_INCOMPLETE],
        STATUS_COMPLETE: [],
    }

    work_order_id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=20, choices=WORK_ORDER_STATUS_CHOICES, default=STATUS_INCOMPLETE)

    def clean(self):
        super().clean()
        if self.pk:
            try:
                old_wo = WorkOrder.objects.get(pk=self.pk)
                old_status = old_wo.status
                if old_status != self.status:
                    valid_next = self.VALID_TRANSITIONS.get(old_status, [])
                    if self.status not in valid_next:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(
                            f'Cannot transition WorkOrder from {old_status} to {self.status}. '
                            f'Valid transitions: {", ".join(valid_next) if valid_next else "none (terminal state)"}'
                        )
            except WorkOrder.DoesNotExist:
                pass

    class Meta:
        db_table = 'workorders'

    def __str__(self):
        return f"Work Order {self.pk}"


class TaskBase(models.Model):
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
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

    MAPPING_CHOICES = [
        ('direct', 'Direct'),
        ('bundle', 'Bundle'),
        ('exclude', 'Exclude'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(
        'PlanBundle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plan_tasks'
    )

    class Meta:
        db_table = 'plan_tasks'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.mapping_strategy == 'bundle' and not self.bundle:
            raise ValidationError("Bundled plan tasks must have a bundle assigned")
        if self.bundle and self.mapping_strategy != 'bundle':
            raise ValidationError("Plan tasks with a bundle must use 'bundle' mapping strategy")

    def save(self, *args, **kwargs):
        """Auto-assign sort_order at the worksheet level (tasks + bundles share the ordering space)."""
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                if self.bundle:
                    max_order = PlanTask.objects.filter(bundle=self.bundle).aggregate(
                        models.Max('sort_order')
                    )['sort_order__max'] or 0
                else:
                    max_task = PlanTask.objects.filter(
                        bundle__isnull=True, est_worksheet=self.est_worksheet
                    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                    max_bundle = PlanBundle.objects.filter(
                        est_worksheet=self.est_worksheet
                    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                    max_order = max(max_task, max_bundle)
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)


class Task(TaskBase):
    """Work task on a WorkOrder. Has lifecycle, hierarchy, bleps."""
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
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
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
                    work_order=self.work_order
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)


class PlanBundle(models.Model):
    """Instance-level grouping of PlanTasks within a worksheet.

    Parallel to TemplateBundle, but lives on the worksheet instance.
    PlanTasks with mapping_strategy='bundle' point to a PlanBundle, and
    the bundle becomes a single line item on the estimate.
    """
    plan_bundle_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_bundles'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField(default=0)
    source_template_bundle = models.ForeignKey(
        'estimates.TemplateBundle', on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        db_table = 'plan_bundles'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.est_worksheet} - {self.name}"


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
