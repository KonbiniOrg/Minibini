from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import AbstractWorkContainer
from apps.core.history import history


@history(exclude=['job_id'])
class Job(models.Model):
    JOB_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    job_id = models.AutoField(primary_key=True)
    job_number = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=50, default='', blank=True)
    created_date = models.DateTimeField(default=timezone.now)
    start_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=JOB_STATUS_CHOICES, default='draft')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
    customer_po_number = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)

    def clean(self):
        """Validate Job state transitions and protect immutable date fields."""
        super().clean()

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            'draft': ['submitted', 'rejected'],
            'submitted': ['approved', 'rejected'],
            'approved': ['completed', 'cancelled'],
            'rejected': [],  # Terminal state
            'completed': [],  # Terminal state
            'cancelled': [],  # Terminal state
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
                    if self.status == 'approved' and not self.start_date:
                        self.start_date = timezone.now()

                    # Transitioning to terminal states - set completed_date
                    if self.status in ['completed', 'cancelled'] and not self.completed_date:
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
    WORK_ORDER_STATUS_CHOICES = [
        ('incomplete', 'Incomplete'),
        ('blocked', 'Blocked'),
        ('complete', 'Complete'),
    ]

    VALID_TRANSITIONS = {
        'incomplete': ['blocked', 'complete'],
        'blocked': ['incomplete'],
        'complete': [],
    }

    work_order_id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=20, choices=WORK_ORDER_STATUS_CHOICES, default='incomplete')

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


class Task(models.Model):
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

    task_id = models.AutoField(primary_key=True)
    parent_task = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtasks')
    assignee = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, null=True, blank=True)
    est_worksheet = models.ForeignKey('estimates.EstWorksheet', on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    units = models.CharField(max_length=50, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
    line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Type of line item this task produces when mapped directly"
    )

    VALID_TRANSITIONS = {
        STATUS_PENDING: [STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_IN_PROGRESS: [STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_BLOCKED: [STATUS_IN_PROGRESS, STATUS_CANCELLED],
        STATUS_COMPLETE: [],
        STATUS_CANCELLED: [],
    }

    def clean(self):
        from django.core.exceptions import ValidationError
        # Validate status transitions on existing tasks
        if self.pk:
            old_status = Task.objects.get(pk=self.pk).status
            if old_status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old_status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        {'status': f"Cannot transition from '{old_status}' to '{self.status}'."}
                    )
        # Must belong to exactly one container
        if self.work_order and self.est_worksheet:
            raise ValidationError("Task cannot be attached to both WorkOrder and EstWorksheet")
        if not self.work_order and not self.est_worksheet:
            raise ValidationError("Task must be attached to either WorkOrder or EstWorksheet")
        # Bundle consistency
        if self.mapping_strategy == 'bundle' and not self.bundle:
            raise ValidationError("Bundled tasks must have a bundle assigned")
        if self.bundle and self.mapping_strategy != 'bundle':
            raise ValidationError("Tasks with a bundle must use 'bundle' mapping strategy")

    def save(self, *args, **kwargs):
        """Override save to auto-generate sort order.

        sort_order means different things depending on context:
        - Unbundled tasks: position at the container level (alongside bundles)
        - Bundled tasks: position within the bundle
        """
        from django.db import transaction

        if self.sort_order is None:
            with transaction.atomic():
                container = self.work_order or self.est_worksheet
                if container:
                    if self.bundle:
                        # Within-bundle: max among tasks in the same bundle
                        max_order = Task.objects.filter(
                            bundle=self.bundle
                        ).aggregate(
                            models.Max('sort_order')
                        )['sort_order__max']
                    else:
                        # Container-level: max among unbundled tasks AND TaskBundles
                        if self.work_order:
                            container_kwargs = {'work_order': container}
                            bundle_kwargs = {'work_order': container}
                        else:
                            container_kwargs = {'est_worksheet': container}
                            bundle_kwargs = {'est_worksheet': container}

                        max_task = Task.objects.filter(
                            bundle__isnull=True, **container_kwargs
                        ).aggregate(
                            models.Max('sort_order')
                        )['sort_order__max'] or 0

                        max_bundle = TaskBundle.objects.filter(
                            **bundle_kwargs
                        ).aggregate(
                            models.Max('sort_order')
                        )['sort_order__max'] or 0

                        max_order = max(max_task, max_bundle)

                    self.sort_order = (max_order or 0) + 1

        self.full_clean()
        super().save(*args, **kwargs)

    def get_container(self):
        """Return the container (WorkOrder or EstWorksheet) this task belongs to."""
        return self.work_order or self.est_worksheet

    # Mapping config for estimate generation
    MAPPING_CHOICES = [
        ('direct', 'Direct'),
        ('bundle', 'Bundle'),
        ('exclude', 'Exclude'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(
        'TaskBundle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks'
    )

    class Meta:
        db_table = 'tasks'

    def __str__(self):
        return self.name


class TaskBundle(models.Model):
    """
    Instance-level grouping of Tasks within a worksheet or work order.

    Parallel to TemplateBundle, but lives on the instance container.
    Tasks with mapping_strategy='bundle' point to a TaskBundle, and
    the bundle becomes a single line item on the estimate.
    """
    # Dual FK pattern (same as Task)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE,
        null=True, blank=True, related_name='bundles'
    )
    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.CASCADE,
        null=True, blank=True, related_name='bundles'
    )

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField(default=0)

    # Traceability
    source_template_bundle = models.ForeignKey(
        'estimates.TemplateBundle', on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        db_table = 'task_bundles'
        ordering = ['sort_order', 'name']

    def get_container(self):
        return self.est_worksheet or self.work_order

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.est_worksheet) == bool(self.work_order):
            raise ValidationError("TaskBundle must belong to exactly one container")

    def __str__(self):
        container = self.get_container()
        return f"{container} - {self.name}"


class Blep(models.Model):
    blep_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('core.User', on_delete=models.PROTECT, null=True, blank=True)
    task = models.ForeignKey(Task, on_delete=models.PROTECT)  # Changed from CASCADE - protect audit trail
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bleps'

    def __str__(self):
        return f"Blep {self.pk} for Task {self.task.pk}"
