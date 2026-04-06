from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import BaseLineItem, AbstractWorkContainer
from apps.core.history import history


@history(exclude=['estimate_id'])
class Estimate(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_OPEN = 'open'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_EXPIRED = 'expired'
    STATUS_SUPERSEDED = 'superseded'

    ESTIMATE_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_OPEN, 'Open'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_SUPERSEDED, 'Superseded'),
    ]

    estimate_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    estimate_number = models.CharField(max_length=50)
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=ESTIMATE_STATUS_CHOICES, default=STATUS_DRAFT)
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
            Estimate.STATUS_DRAFT: [Estimate.STATUS_OPEN, Estimate.STATUS_REJECTED],
            Estimate.STATUS_OPEN: [Estimate.STATUS_ACCEPTED, Estimate.STATUS_SUPERSEDED, Estimate.STATUS_REJECTED, Estimate.STATUS_EXPIRED],
            Estimate.STATUS_ACCEPTED: [],  # Terminal state
            Estimate.STATUS_REJECTED: [],  # Terminal state
            Estimate.STATUS_EXPIRED: [],  # Terminal state
            Estimate.STATUS_SUPERSEDED: [],  # Terminal state
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

                # If transitioning out of draft, ensure at least one line item exists
                if old_status == Estimate.STATUS_DRAFT and self.status != Estimate.STATUS_DRAFT:
                    if not EstimateLineItem.objects.filter(estimate=self).exists():
                        raise ValidationError(
                            'Cannot change Estimate status from Draft without at least one line item.'
                        )

            except Estimate.DoesNotExist:
                pass

        # Only one accepted estimate per job
        if self.status == Estimate.STATUS_ACCEPTED:
            existing_accepted = Estimate.objects.filter(
                job=self.job,
                status=Estimate.STATUS_ACCEPTED
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
                    if self.status == Estimate.STATUS_OPEN and not self.sent_date:
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
                    if self.status in [Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED, Estimate.STATUS_SUPERSEDED, Estimate.STATUS_EXPIRED] and not self.closed_date:
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
            from apps.estimates.signals import estimate_status_changed_for_worksheet
            estimate_status_changed_for_worksheet.send(
                sender=self.__class__,
                estimate=self,
                new_worksheet_status=new_ws_status
            )

    def _get_worksheet_status(self, estimate_status):
        """Map estimate status to worksheet status."""
        if estimate_status == Estimate.STATUS_DRAFT:
            return EstWorksheet.STATUS_DRAFT
        elif estimate_status in [Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED]:
            return EstWorksheet.STATUS_FINAL
        elif estimate_status == Estimate.STATUS_SUPERSEDED:
            return EstWorksheet.STATUS_SUPERSEDED
        return None

    def _maybe_update_job_status(self, old_status):
        """Send signal to update job status if the change is relevant."""
        from apps.estimates.signals import estimate_status_changed_for_job, estimate_accepted

        # Signal when estimate is sent (draft → open): job should become submitted
        if self.status == Estimate.STATUS_OPEN and old_status == Estimate.STATUS_DRAFT:
            from apps.jobs.models import Job
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status=Job.STATUS_SUBMITTED
            )

        # Signal when estimate is accepted
        if self.status == Estimate.STATUS_ACCEPTED and old_status != Estimate.STATUS_ACCEPTED:
            from apps.jobs.models import Job
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status=Job.STATUS_APPROVED
            )
            estimate_accepted.send(
                sender=self.__class__,
                estimate=self,
            )

        # Signal when approved estimate is superseded
        elif self.status == Estimate.STATUS_SUPERSEDED and old_status == Estimate.STATUS_ACCEPTED:
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status='blocked'  # NOTE: 'blocked' is not in Job's status choices
            )

    def __str__(self):
        return f"Estimate {self.estimate_number}"

    class Meta:
        db_table = 'estimates'
        unique_together = ['estimate_number', 'version']


@history(exclude=['est_worksheet_id'])
class EstWorksheet(AbstractWorkContainer):
    STATUS_DRAFT = 'draft'
    STATUS_FINAL = 'final'
    STATUS_SUPERSEDED = 'superseded'

    EST_WORKSHEET_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_FINAL, 'Final'),
        (STATUS_SUPERSEDED, 'Superseded'),
    ]

    est_worksheet_id = models.AutoField(primary_key=True)
    estimate = models.ForeignKey(Estimate, on_delete=models.SET_NULL, null=True, blank=True, related_name='worksheets')
    status = models.CharField(max_length=20, choices=EST_WORKSHEET_STATUS_CHOICES, default=STATUS_DRAFT)
    version = models.IntegerField(default=1)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    created_date = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        """Override save to set initial status based on Estimate if creating new worksheet."""
        # Only set status from estimate on creation, not updates
        if not self.pk and self.estimate:
            if self.estimate.status == Estimate.STATUS_DRAFT:
                self.status = EstWorksheet.STATUS_DRAFT
            elif self.estimate.status in [Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED]:
                self.status = EstWorksheet.STATUS_FINAL
            elif self.estimate.status == Estimate.STATUS_SUPERSEDED:
                self.status = EstWorksheet.STATUS_SUPERSEDED
        super().save(*args, **kwargs)

    def create_new_version(self):
        """Create a new version of this worksheet, marking this one as superseded."""
        from apps.jobs.models import PlanTask, PlanBundle
        from apps.inventory.models import PlanMaterial

        # Mark current worksheet as superseded
        self.status = EstWorksheet.STATUS_SUPERSEDED
        self.save()

        # Create new worksheet with this one as parent
        new_worksheet = EstWorksheet.objects.create(
            job=self.job,
            template=self.template,
            status=EstWorksheet.STATUS_DRAFT,
            version=self.version + 1,
            parent=self,  # New worksheet points to this one as parent
            estimate=None  # New version starts without an estimate
        )

        # Copy PlanBundles, mapping old bundle PKs to new ones
        bundle_mapping = {}
        for bundle in self.plan_bundles.all():
            new_bundle = PlanBundle.objects.create(
                est_worksheet=new_worksheet,
                name=bundle.name,
                accounting_category=bundle.accounting_category,
                sort_order=bundle.sort_order,
                source_template_bundle=bundle.source_template_bundle,
            )
            bundle_mapping[bundle.pk] = new_bundle

        # Copy all plan tasks to the new worksheet
        for plan_task in self.plan_tasks.all():
            new_bundle = bundle_mapping.get(plan_task.bundle_id) if plan_task.bundle_id else None
            new_plan_task = PlanTask.objects.create(
                est_worksheet=new_worksheet,
                name=plan_task.name,
                description=plan_task.description,
                units=plan_task.units,
                rate=plan_task.rate,
                est_qty=plan_task.est_qty,
                accounting_category=plan_task.accounting_category,
                mapping_strategy=plan_task.mapping_strategy,
                bundle=new_bundle,
            )

            # Copy plan materials to the new plan task
            for plan_material in plan_task.plan_materials.all():
                PlanMaterial.objects.create(
                    plan_task=new_plan_task,
                    price_list_item=plan_material.price_list_item,
                    accounting_category=plan_material.accounting_category,
                    description=plan_material.description,
                    quantity=plan_material.quantity,
                    unit_cost=plan_material.unit_cost,
                    sell_price=plan_material.sell_price,
                )

        return new_worksheet

    class Meta:
        db_table = 'worksheets'

    def __str__(self):
        return f"EstWorksheet {self.pk} v{self.version}"


class WorkOrderTemplate(models.Model):
    """Template for creating WorkOrders/EstWorksheets with product structure"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Pricing
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # is_active no longer used but kept in case we change our minds later and to avoid a migration
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wo_templates'

    def __str__(self):
        return self.template_name

    def generate_tasks_for_worksheet(self, worksheet, quantity=1):
        """Generate all plan tasks for a worksheet, with proper product grouping and bundling."""
        from apps.jobs.models import PlanBundle

        generated_tasks = []

        for instance in range(1, quantity + 1):
            bundle_identifier = f"{self.template_name}_{worksheet.est_worksheet_id}_{instance}"

            # Create PlanBundles from TemplateBundles
            template_to_instance_bundle = {}
            for template_bundle in self.bundles.all():
                plan_bundle = PlanBundle.objects.create(
                    est_worksheet=worksheet,
                    name=template_bundle.name,
                    accounting_category=template_bundle.accounting_category,
                    sort_order=template_bundle.sort_order,
                    source_template_bundle=template_bundle,
                )
                template_to_instance_bundle[template_bundle.pk] = plan_bundle

            # Get task template associations for this work order template
            associations = TemplateTaskAssociation.objects.filter(
                work_order_template=self,
                task_template__is_active=True
            ).select_related('bundle').order_by('sort_order', 'task_template__template_name')

            for association in associations:
                # Resolve instance-level bundle for this association
                instance_bundle = None
                if association.bundle_id:
                    instance_bundle = template_to_instance_bundle.get(association.bundle_id)

                task = association.task_template.generate_task(
                    worksheet,
                    est_qty=association.est_qty,
                    bundle_identifier=bundle_identifier,
                    product_instance=instance if quantity > 1 else None,
                    mapping_strategy=association.mapping_strategy,
                    bundle=instance_bundle,
                    sort_order=association.sort_order,
                )
                generated_tasks.append(task)

        return generated_tasks


class TemplateBundle(models.Model):
    """
    A named grouping within a WorkOrderTemplate that becomes one line item.

    TemplateTaskAssociations point to a bundle to indicate they should be
    combined into a single line item on the estimate.
    """
    work_order_template = models.ForeignKey(
        WorkOrderTemplate,
        on_delete=models.CASCADE,
        related_name='bundles'
    )
    name = models.CharField(max_length=100)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_bundles'
        unique_together = ['work_order_template', 'name']
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.work_order_template.template_name} - {self.name}"


class TemplateTaskAssociation(models.Model):
    """Association between WorkOrderTemplate and TaskTemplate with mapping configuration."""
    work_order_template = models.ForeignKey(WorkOrderTemplate, on_delete=models.CASCADE)
    task_template = models.ForeignKey('TaskTemplate', on_delete=models.CASCADE)

    # Quantity and ordering
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sort_order = models.IntegerField(default=0)

    # Mapping configuration
    MAPPING_CHOICES = [
        ('direct', 'Direct - becomes its own line item'),
        ('bundle', 'Bundle - part of a bundled line item'),
        ('exclude', 'Exclude - internal only, not on estimate'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(
        TemplateBundle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='associations'
    )

    class Meta:
        db_table = 'template_task_assoc'
        unique_together = ['work_order_template', 'task_template']
        ordering = ['sort_order']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.bundle and self.bundle.work_order_template != self.work_order_template:
            raise ValidationError("Bundle must belong to the same WorkOrderTemplate")

    def __str__(self):
        return f"{self.work_order_template.template_name} -> {self.task_template.template_name}"


class TaskTemplate(models.Model):
    """Template for creating Tasks with predefined settings"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    units = models.CharField(max_length=50, default='none')
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # AccountingCategory determines what type of line item this task produces when mapped directly
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        null=True,  # Temporarily nullable for migration
        blank=True,
        help_text="Type of line item this task produces when mapped directly"
    )

    # Relationships
    work_order_templates = models.ManyToManyField(WorkOrderTemplate, through='TemplateTaskAssociation', related_name='task_templates')

    created_date = models.DateTimeField(auto_now_add=True)
    # is_active no longer used but kept in case we change our minds later and to avoid a migration
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'task_templates'

    def __str__(self):
        return self.template_name

    def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                       assignee=None, mapping_strategy='direct', bundle=None, sort_order=None):
        """Generate a PlanTask or Task from this template with specified quantity and mapping config.

        The return type depends on the container: EstWorksheet -> PlanTask, WorkOrder -> Task.
        """
        from apps.jobs.models import WorkOrder, Task, PlanTask

        if isinstance(container, WorkOrder):
            return Task.objects.create(
                work_order=container,
                name=self.template_name,
                description=self.description,
                units=self.units,
                rate=self.rate,
                est_qty=est_qty,
                accounting_category=self.accounting_category,
                assignee=assignee,
                sort_order=sort_order,
            )
        else:  # EstWorksheet
            return PlanTask.objects.create(
                est_worksheet=container,
                name=self.template_name,
                description=self.description,
                units=self.units,
                rate=self.rate,
                est_qty=est_qty,
                accounting_category=self.accounting_category,
                mapping_strategy=mapping_strategy,
                bundle=bundle,
                sort_order=sort_order,
            )


class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)
    task = models.ForeignKey('jobs.PlanTask', on_delete=models.PROTECT, null=True, blank=True)
    material = models.ForeignKey(
        'inventory.PlanMaterial', on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        db_table = 'est_li'
        verbose_name = "Estimate Line Item"
        verbose_name_plural = "Estimate Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'estimate'

    def __str__(self):
        return f"Estimate Line Item {self.pk} for {self.estimate.estimate_number}"
