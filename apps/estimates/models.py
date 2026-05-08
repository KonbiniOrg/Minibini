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
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
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
        from apps.jobs.models import PlanTask
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

        # Copy all plan tasks to the new worksheet
        for plan_task in self.plan_tasks.all():
            new_plan_task = PlanTask.objects.create(
                est_worksheet=new_worksheet,
                name=plan_task.name,
                description=plan_task.description,
                rate_scheme=plan_task.rate_scheme,
                active_modifiers=list(plan_task.active_modifiers or []),
                est_qty=plan_task.est_qty,
            )

            # Copy plan materials to the new plan task
            for plan_material in plan_task.plan_materials.all():
                PlanMaterial.objects.create(
                    plan_task=new_plan_task,
                    est_worksheet=new_worksheet,
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


class WorkTemplate(models.Model):
    """Template for populating Jobs and EstWorksheets with product structure"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Pricing
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # is_active no longer used but kept in case we change our minds later and to avoid a migration
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'work_templates'

    def __str__(self):
        return self.template_name

    def generate_tasks_for_worksheet(self, worksheet, quantity=1):
        """Generate all plan tasks for a worksheet from this template."""
        generated_tasks = []

        for instance in range(1, quantity + 1):
            # Get task template associations for this work order template
            associations = TemplateTaskAssociation.objects.filter(
                work_template=self,
                task_template__is_active=True
            ).order_by('sort_order', 'task_template__template_name')

            for association in associations:
                task = association.task_template.generate_task(
                    worksheet,
                    est_qty=association.est_qty,
                    product_instance=instance if quantity > 1 else None,
                    sort_order=association.sort_order,
                )
                generated_tasks.append(task)

        return generated_tasks

    def generate_materials_for_worksheet(self, worksheet, quantity=1):
        from apps.inventory.models import PlanMaterial
        for tm in self.materials.all():
            for _ in range(quantity):
                if tm.price_list_item_id:
                    # PLI-linked: only carry quantity + PLI link.
                    # _populate_from_pli pulls description, units, pricing, and
                    # accounting_category from the *current* PLI on save.
                    PlanMaterial.objects.create(
                        est_worksheet=worksheet,
                        plan_task=None,
                        quantity=tm.quantity,
                        price_list_item=tm.price_list_item,
                    )
                else:
                    # Freeform: template carries the explicit values.
                    PlanMaterial.objects.create(
                        est_worksheet=worksheet,
                        plan_task=None,
                        description=tm.description,
                        quantity=tm.quantity,
                        units=tm.units,
                        unit_cost=tm.unit_cost,
                        sell_price=tm.sell_price,
                        accounting_category=tm.accounting_category,
                    )

    def generate_materials_for_job(self, job, quantity=1):
        from apps.inventory.services import MaterialService
        for tm in self.materials.all():
            for _ in range(quantity):
                if tm.price_list_item_id:
                    # PLI-linked: only carry quantity + PLI link.
                    # _populate_from_pli pulls description, units, pricing, and
                    # accounting_category from the *current* PLI on save.
                    MaterialService.create_on_job(
                        job=job, task=None,
                        quantity=tm.quantity,
                        price_list_item=tm.price_list_item,
                    )
                else:
                    # Freeform: template carries the explicit values.
                    MaterialService.create_on_job(
                        job=job, task=None,
                        description=tm.description,
                        quantity=tm.quantity,
                        units=tm.units,
                        unit_cost=tm.unit_cost,
                        sell_price=tm.sell_price,
                        accounting_category=tm.accounting_category,
                    )


class TemplateTaskAssociation(models.Model):
    """Association between WorkTemplate and TaskTemplate with ordering."""
    work_template = models.ForeignKey(WorkTemplate, on_delete=models.CASCADE)
    task_template = models.ForeignKey('TaskTemplate', on_delete=models.CASCADE)

    # Quantity and ordering
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_task_assoc'
        unique_together = ['work_template', 'task_template']
        ordering = ['sort_order']

    def __str__(self):
        return f"{self.work_template.template_name} -> {self.task_template.template_name}"


class TaskTemplate(models.Model):
    """Template for creating Tasks with predefined settings"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.PROTECT,
        help_text="Default billing scheme for tasks from this template"
    )
    default_active_modifiers = models.JSONField(
        default=list, blank=True,
        help_text="Pre-checked modifier keys from the scheme"
    )
    default_billable_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Typical estimated billable quantity"
    )

    # Relationships
    work_templates = models.ManyToManyField(WorkTemplate, through='TemplateTaskAssociation', related_name='task_templates')

    created_date = models.DateTimeField(auto_now_add=True)
    # is_active no longer used but kept in case we change our minds later and to avoid a migration
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'task_templates'

    def __str__(self):
        return self.template_name

    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category

    def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                       assignee=None, sort_order=None,
                       name=None, description=None,
                       active_modifiers=None, est_worker_time=None):
        """Generate a PlanTask or Task from this template with specified quantity.

        The return type depends on the container: EstWorksheet -> PlanTask, Job -> Task.

        Optional overrides:
          name            – if truthy, replaces template_name; empty string falls back to template default.
          description     – if not None, replaces template description (empty string is kept as-is).
          active_modifiers – list of modifier keys; falls back to template defaults when None.
          est_worker_time – ISO 8601 duration string or None.
        """
        from apps.jobs.models import Job, Task, PlanTask
        from apps.core.services import SchemeSupersededError
        from django.db import transaction

        if self.rate_scheme_id and self.rate_scheme.replaced_by_id is not None:
            raise SchemeSupersededError(
                f'Template "{self.template_name}" references a superseded '
                f'RateScheme. Update the template before adding tasks from it.'
            )

        resolved_name = name if name else self.template_name
        resolved_description = description if description is not None else self.description
        resolved_modifiers = list(active_modifiers if active_modifiers is not None else (self.default_active_modifiers or []))

        if isinstance(container, Job):
            with transaction.atomic():
                task = Task.objects.create(
                    job=container,
                    name=resolved_name,
                    description=resolved_description,
                    assignee=assignee,
                    sort_order=sort_order,
                    rate_scheme=self.rate_scheme,
                    active_modifiers=resolved_modifiers,
                    est_qty=est_qty,
                    est_worker_time=est_worker_time,
                )
            return task
        else:  # EstWorksheet
            return PlanTask.objects.create(
                est_worksheet=container,
                name=resolved_name,
                description=resolved_description,
                rate_scheme=self.rate_scheme,
                active_modifiers=resolved_modifiers,
                est_qty=est_qty,
                est_worker_time=est_worker_time,
                sort_order=sort_order,
            )


class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)
    source_template = models.ForeignKey(
        'estimates.TaskTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text='TaskTemplate this line item was created from (preserves catalog ref for direct-estimate carry-over).',
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


class EstimateLineItemSource(models.Model):
    """Polymorphic join between an EstimateLineItem and its source atom (PlanTask or PlanMaterial).

    The unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level: an atom can be referenced by at most one estimate line item.

    Note: unlike InvoiceLineItemSource, this constraint is NOT scoped by Estimate status
    on the plan side. Worksheet revisions copy atoms (creating new instances), so the
    constraint never needs to fire across revisions in practice.
    """
    SOURCE_PLAN_TASK = 'plan_task'
    SOURCE_PLAN_MATERIAL = 'plan_material'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_PLAN_TASK, 'PlanTask'),
        (SOURCE_PLAN_MATERIAL, 'PlanMaterial'),
    ]

    source_id = models.AutoField(primary_key=True)
    estimate_line_item = models.ForeignKey(
        EstimateLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'estimate_line_item_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        """Return the concrete atom instance (PlanTask or PlanMaterial) referenced by this source."""
        if self.source_type == self.SOURCE_PLAN_TASK:
            from apps.jobs.models import PlanTask
            return PlanTask.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_PLAN_MATERIAL:
            from apps.inventory.models import PlanMaterial
            return PlanMaterial.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return f'Source {self.source_id}: {self.source_type}:{self.source_pk} → EstLineItem {self.estimate_line_item_id}'
