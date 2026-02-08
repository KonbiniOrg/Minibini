from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError


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

    def __str__(self):
        return f"{self.job_number}"


class Estimate(models.Model):
    ESTIMATE_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
        ('superseded', 'Superseded'),
    ]

    estimate_id = models.AutoField(primary_key=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    estimate_number = models.CharField(max_length=50)
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=ESTIMATE_STATUS_CHOICES, default='draft')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    created_date = models.DateTimeField(default=timezone.now)
    # date the estimate was sent to the customer and stopped being editable
    sent_date = models.DateTimeField(null=True, blank=True)
    # date the estimate was Approved, Rejected, or Superseded
    closed_date = models.DateTimeField(null=True, blank=True)
    # date the estimate expired; set automatically when est is Sent based on Configuration key est_expire_days
    expiration_date = models.DateTimeField(null=True, blank=True)

    def clean(self):
        """Validate estimate status changes, date immutability, and uniqueness constraints."""
        super().clean()

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            'draft': ['open', 'rejected'],
            'open': ['accepted', 'superseded', 'rejected', 'expired'],
            'accepted': [],  # Terminal state
            'rejected': [],  # Terminal state
            'expired': [],  # Terminal state
            'superseded': [],  # Terminal state
        }

        # Check if this is an update
        if self.pk:
            try:
                old_estimate = Estimate.objects.get(pk=self.pk)
                old_status = old_estimate.status

                # Protect immutable date fields
                if old_estimate.created_date and self.created_date != old_estimate.created_date:
                    self.created_date = old_estimate.created_date

                if old_estimate.sent_date and self.sent_date != old_estimate.sent_date:
                    self.sent_date = old_estimate.sent_date

                if old_estimate.closed_date and self.closed_date != old_estimate.closed_date:
                    self.closed_date = old_estimate.closed_date

                # If status hasn't changed, no validation needed
                if old_status == self.status:
                    return

                # Check if the transition is valid
                valid_next_states = VALID_TRANSITIONS.get(old_status, [])
                if self.status not in valid_next_states:
                    raise ValidationError(
                        f'Cannot transition Estimate from {old_status} to {self.status}. '
                        f'Valid transitions from {old_status} are: {", ".join(valid_next_states) if valid_next_states else "none (terminal state)"}'
                    )

            except Estimate.DoesNotExist:
                pass

        # Only one accepted estimate per job
        if self.status == 'accepted':
            existing_accepted = Estimate.objects.filter(
                job=self.job,
                status='accepted'
            ).exclude(pk=self.pk if self.pk else None)

            if existing_accepted.exists():
                raise ValidationError(f'Job {self.job.job_number} already has an accepted estimate')

    def save(self, *args, **kwargs):
        """Override save to detect status changes, set dates, and send signals if needed."""
        from apps.core.models import Configuration
        from datetime import timedelta

        old_status = None

        # Check if this is an update (not a new object)
        if self.pk:
            try:
                # Fetch the old estimate
                old_estimate = Estimate.objects.get(pk=self.pk)
                old_status = old_estimate.status

                # Handle state transition date setting
                if old_status != self.status:
                    # Transitioning to 'open' - set sent_date and expiration_date
                    if self.status == 'open' and not self.sent_date:
                        self.sent_date = timezone.now()

                        # Set expiration_date if not already set
                        if not self.expiration_date:
                            try:
                                expire_days_config = Configuration.objects.get(key='est_expire_days')
                                expire_days = int(expire_days_config.value)
                            except (Configuration.DoesNotExist, ValueError):
                                expire_days = 30  # Default to 30 days

                            self.expiration_date = timezone.now() + timedelta(days=expire_days)

                    # Transitioning to terminal states - set closed_date
                    if self.status in ['accepted', 'rejected', 'superseded', 'expired'] and not self.closed_date:
                        self.closed_date = timezone.now()

            except Estimate.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

        # Check if status changed and handle updates
        if old_status and old_status != self.status:
            self._maybe_update_worksheet_statuses(old_status)
            self._maybe_update_job_status(old_status)

    def _maybe_update_worksheet_statuses(self, old_status):
        """Send signal to update worksheet statuses if the change is relevant."""
        # Map statuses to worksheet statuses (pure Python, no DB hit)
        old_ws_status = self._get_worksheet_status(old_status)
        new_ws_status = self._get_worksheet_status(self.status)

        # Only send signal if worksheet status should change
        if old_ws_status != new_ws_status and new_ws_status is not None:
            from apps.jobs.signals import estimate_status_changed_for_worksheet
            estimate_status_changed_for_worksheet.send(
                sender=self.__class__,
                estimate=self,
                new_worksheet_status=new_ws_status
            )

    def _get_worksheet_status(self, estimate_status):
        """Map estimate status to worksheet status."""
        if estimate_status == 'draft':
            return 'draft'
        elif estimate_status in ['open', 'accepted', 'rejected']:
            return 'final'
        elif estimate_status == 'superseded':
            return 'superseded'
        return None

    def _maybe_update_job_status(self, old_status):
        """Send signal to update job status if the change is relevant."""
        from apps.jobs.signals import estimate_status_changed_for_job

        # Signal when estimate is accepted
        if self.status == 'accepted' and old_status != 'accepted':
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status='approved'
            )

        # Signal when approved estimate is superseded
        elif self.status == 'superseded' and old_status == 'accepted':
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status='blocked'
            )

    def __str__(self):
        return f"Estimate {self.estimate_number}"

    class Meta:
        unique_together = ['estimate_number', 'version']


class AbstractWorkContainer(models.Model):
    """Abstract base class for WorkOrder and EstWorksheet containing common fields."""
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    template = models.ForeignKey('WorkOrderTemplate', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        abstract = True


class WorkOrder(AbstractWorkContainer):
    WORK_ORDER_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('incomplete', 'Incomplete'),
        ('blocked', 'Blocked'),
        ('complete', 'Complete'),
    ]

    work_order_id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=20, choices=WORK_ORDER_STATUS_CHOICES, default='draft')

    def __str__(self):
        return f"Work Order {self.pk}"


class EstWorksheet(AbstractWorkContainer):
    EST_WORKSHEET_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('final', 'Final'),
        ('superseded', 'Superseded'),
    ]

    est_worksheet_id = models.AutoField(primary_key=True)
    estimate = models.ForeignKey(Estimate, on_delete=models.SET_NULL, null=True, blank=True, related_name='worksheets')
    status = models.CharField(max_length=20, choices=EST_WORKSHEET_STATUS_CHOICES, default='draft')
    version = models.IntegerField(default=1)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    created_date = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        """Override save to set initial status based on Estimate if creating new worksheet."""
        # Only set status from estimate on creation, not updates
        if not self.pk and self.estimate:
            if self.estimate.status == 'draft':
                self.status = 'draft'
            elif self.estimate.status in ['open', 'accepted', 'rejected']:
                self.status = 'final'
            elif self.estimate.status == 'superseded':
                self.status = 'superseded'
        super().save(*args, **kwargs)

    def create_new_version(self):
        """Create a new version of this worksheet, marking this one as superseded."""
        # Mark current worksheet as superseded
        self.status = 'superseded'
        self.save()

        # Create new worksheet with this one as parent
        new_worksheet = EstWorksheet.objects.create(
            job=self.job,
            template=self.template,
            status='draft',
            version=self.version + 1,
            parent=self,  # New worksheet points to this one as parent
            estimate=None  # New version starts without an estimate
        )

        # Copy all tasks to the new worksheet
        for task in self.task_set.all():
            Task.objects.create(
                parent_task=task.parent_task,
                assignee=task.assignee,
                est_worksheet=new_worksheet,
                name=task.name,
                units=task.units,
                rate=task.rate,
                est_qty=task.est_qty,
                template=task.template
            )

        return new_worksheet

    def __str__(self):
        return f"EstWorksheet {self.pk} v{self.version}"


class Task(models.Model):
    task_id = models.AutoField(primary_key=True)
    parent_task = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtasks')
    assignee = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, null=True, blank=True)
    est_worksheet = models.ForeignKey(EstWorksheet, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255)
    line_number = models.PositiveIntegerField(blank=True, null=True)
    units = models.CharField(max_length=50, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    template = models.ForeignKey('TaskTemplate', on_delete=models.SET_NULL, null=True, blank=True)

    def clean(self):
        """Ensure task is attached to either WorkOrder or EstWorksheet, but not both."""
        from django.core.exceptions import ValidationError
        if self.work_order and self.est_worksheet:
            raise ValidationError("Task cannot be attached to both WorkOrder and EstWorksheet")
        if not self.work_order and not self.est_worksheet:
            raise ValidationError("Task must be attached to either WorkOrder or EstWorksheet")

    def save(self, *args, **kwargs):
        """Override save to auto-generate line numbers."""
        from django.db import transaction

        if self.line_number is None:
            with transaction.atomic():
                container = self.work_order or self.est_worksheet
                if container:
                    # Determine the filter based on container type
                    if self.work_order:
                        filter_kwargs = {'work_order': container}
                    else:
                        filter_kwargs = {'est_worksheet': container}

                    # Get max line number for this container
                    max_line = Task.objects.filter(**filter_kwargs).aggregate(
                        models.Max('line_number')
                    )['line_number__max']

                    self.line_number = (max_line or 0) + 1

        self.full_clean()
        super().save(*args, **kwargs)

    def get_container(self):
        """Return the container (WorkOrder or EstWorksheet) this task belongs to."""
        return self.work_order or self.est_worksheet

    def __str__(self):
        return self.name


class Blep(models.Model):
    blep_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('core.User', on_delete=models.PROTECT, null=True, blank=True)
    task = models.ForeignKey(Task, on_delete=models.PROTECT)  # Changed from CASCADE - protect audit trail
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Blep {self.pk} for Task {self.task.pk}"


from apps.core.models import BaseLineItem


class WorkOrderTemplate(models.Model):
    """Template for creating WorkOrders/EstWorksheets with product structure"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Pricing
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.template_name

    def generate_tasks_for_worksheet(self, worksheet, quantity=1):
        """Generate all tasks for a worksheet, with proper product grouping"""
        generated_tasks = []

        for instance in range(1, quantity + 1):
            bundle_identifier = f"{self.template_name}_{worksheet.est_worksheet_id}_{instance}"

            # Get task template associations for this work order template
            associations = TemplateTaskAssociation.objects.filter(
                work_order_template=self,
                task_template__parent_template__isnull=True,  # Root-level templates only
                task_template__is_active=True
            ).order_by('sort_order', 'task_template__template_name')

            for association in associations:
                task = association.task_template.generate_task(
                    worksheet,
                    est_qty=association.est_qty,
                    bundle_identifier=bundle_identifier,
                    product_instance=instance if quantity > 1 else None
                )
                generated_tasks.append(task)

        return generated_tasks


class TemplateTaskAssociation(models.Model):
    """Association between WorkOrderTemplate and TaskTemplate with customizable quantities"""
    work_order_template = models.ForeignKey(WorkOrderTemplate, on_delete=models.CASCADE)
    task_template = models.ForeignKey('TaskTemplate', on_delete=models.CASCADE)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ['work_order_template', 'task_template']
        ordering = ['sort_order', 'task_template__template_name']

    def __str__(self):
        return f"{self.work_order_template.template_name} -> {self.task_template.template_name} ({self.est_qty})"


class TaskTemplate(models.Model):
    """Template for creating Tasks with predefined settings"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    units = models.CharField(max_length=50, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Relationships
    work_order_templates = models.ManyToManyField(WorkOrderTemplate, through='TemplateTaskAssociation', related_name='task_templates')
    parent_template = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_templates')

    created_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.template_name

    def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None, assignee=None):
        """Generate a Task from this template with specified quantity"""
        task = Task.objects.create(
            work_order=container if isinstance(container, WorkOrder) else None,
            est_worksheet=container if isinstance(container, EstWorksheet) else None,
            name=self.template_name,
            units=self.units,
            rate=self.rate,
            est_qty=est_qty,
            template=self,
            assignee=assignee
        )

        # Generate child tasks if this template has children
        for child_template in self.child_templates.filter(is_active=True):
            child_task = child_template.generate_task(
                container,
                est_qty=est_qty,  # Pass the same quantity to child tasks
                bundle_identifier=bundle_identifier,
                product_instance=product_instance,
                assignee=assignee
            )
            child_task.parent_task = task
            child_task.save()

        return task


class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Estimate Line Item"
        verbose_name_plural = "Estimate Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'estimate'

    def __str__(self):
        return f"Estimate Line Item {self.pk} for {self.estimate.estimate_number}"
