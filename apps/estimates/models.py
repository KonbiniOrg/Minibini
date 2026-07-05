import secrets
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import BaseLineItem
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

    # Unguessable token backing the customer-facing portal link. Minted at
    # creation (see save()); per-row, so each revision gets its own.
    public_token = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
    )

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

        # Mint the customer-portal token once, at creation.
        if not self.pk and not self.public_token:
            self.public_token = secrets.token_urlsafe(32)

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

        # Check if status changed and handle updates. (Wizard editability is
        # derived from the live estimate's status at read time.)
        if old_status and old_status != self.status:
            self._maybe_update_job_status(old_status)

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

        # Signal when an open estimate dies (declined or expired): reject the job.
        if (old_status == Estimate.STATUS_OPEN and
                self.status in (Estimate.STATUS_REJECTED, Estimate.STATUS_EXPIRED)):
            from apps.jobs.models import Job
            estimate_status_changed_for_job.send(
                sender=self.__class__,
                estimate=self,
                new_job_status=Job.STATUS_REJECTED,
            )

    @classmethod
    def with_amended_flag(cls, qs):
        """Annotate `_is_amended_anno` (Exists of an accepted CO) so
        is_amended() answers query-free per row on list paths."""
        from django.db.models import Exists, OuterRef
        return qs.annotate(
            _is_amended_anno=Exists(
                ChangeOrder.objects.filter(
                    estimate=OuterRef('pk'),
                    status=ChangeOrder.STATUS_ACCEPTED,
                )
            )
        )

    def is_amended(self):
        """True when this estimate is the accepted agreement-of-record AND at
        least one ACCEPTED change order amends it. Purely derived — the stored
        `status` stays `accepted`; the UI renders "amended" off this flag. Only
        accepted COs count (they're the only ones in the agreement-of-record),
        and the accepted-status short-circuit keeps non-accepted estimates
        query-free. Single source of truth for the EstimateSerializer and the
        board pipeline payload. Rows from a `with_amended_flag` queryset
        answer from the annotation without a query."""
        if self.status != Estimate.STATUS_ACCEPTED:
            return False
        anno = getattr(self, '_is_amended_anno', None)
        if anno is not None:
            return anno
        return self.change_orders.filter(
            status=ChangeOrder.STATUS_ACCEPTED,
        ).exists()

    def __str__(self):
        return f"Estimate {self.estimate_number}"

    class Meta:
        db_table = 'estimates'
        unique_together = ['estimate_number', 'version']


@history(exclude=['change_order_id'])
class ChangeOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_OPEN = 'open'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_EXPIRED = 'expired'
    STATUS_SUPERSEDED = 'superseded'

    CO_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_OPEN, 'Open'), (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_REJECTED, 'Rejected'), (STATUS_EXPIRED, 'Expired'), (STATUS_SUPERSEDED, 'Superseded'),
    ]

    change_order_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='change_orders')
    estimate = models.ForeignKey(Estimate, on_delete=models.PROTECT, related_name='change_orders')
    change_order_number = models.CharField(max_length=80, unique=True, blank=True)
    version = models.IntegerField(default=1)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    status = models.CharField(max_length=20, choices=CO_STATUS_CHOICES, default=STATUS_DRAFT)
    created_date = models.DateTimeField(default=timezone.now)
    sent_date = models.DateTimeField(null=True, blank=True)
    closed_date = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    # Unguessable token backing the customer-facing portal link. Minted at
    # creation (see save()); per-row, so each seed_new revision gets its own.
    public_token = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
    )

    VALID_TRANSITIONS = {
        STATUS_DRAFT: [STATUS_OPEN, STATUS_REJECTED],
        STATUS_OPEN: [STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SUPERSEDED, STATUS_EXPIRED],
        STATUS_ACCEPTED: [], STATUS_REJECTED: [], STATUS_EXPIRED: [], STATUS_SUPERSEDED: [],
    }

    class Meta:
        db_table = 'change_orders'

    def clean(self):
        super().clean()
        if self.pk:
            old = ChangeOrder.objects.get(pk=self.pk)
            for f in ('created_date', 'sent_date', 'closed_date'):
                if getattr(old, f) and getattr(self, f) != getattr(old, f):
                    setattr(self, f, getattr(old, f))
            if old.status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old.status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        f'Cannot transition ChangeOrder from {old.status} to {self.status}.'
                    )
                if old.status == self.STATUS_DRAFT:
                    if not ChangeOrderLineItem.objects.filter(change_order=self).exists():
                        raise ValidationError('Cannot send a change order with no line items.')
                    # Mirror the estimate send guard: a bare add line (no
                    # service/inventory descriptor) crystallizes into a Fee or a
                    # provisional Material at acceptance, and both need an
                    # accounting category. Catch it at send so acceptance —
                    # after the customer has said yes — can never fail on it.
                    missing = [
                        li.description or f'line {li.line_number}'
                        for li in ChangeOrderLineItem.objects.filter(
                            change_order=self,
                            action=ChangeOrderLineItem.ACTION_ADD,
                            service_item__isnull=True,
                            inventory_item__isnull=True,
                            accounting_category__isnull=True,
                        )
                    ]
                    if missing:
                        raise ValidationError(
                            'Cannot send: every added line item needs an '
                            'accounting category first. Missing on: '
                            + ', '.join(missing) + '.'
                        )

    def save(self, *args, **kwargs):
        from apps.core.models import Configuration
        from datetime import timedelta

        # Mint the customer-portal token once, at creation.
        if not self.pk and not self.public_token:
            self.public_token = secrets.token_urlsafe(32)

        old_status = None
        if self.pk:
            old_status = ChangeOrder.objects.get(pk=self.pk).status
            if old_status != self.status:
                if self.status == self.STATUS_OPEN and not self.sent_date:
                    self.sent_date = timezone.now()
                    if not self.expiration_date:
                        try:
                            days = int(Configuration.objects.get(key='est_expire_days').value)
                        except (Configuration.DoesNotExist, ValueError):
                            days = 30
                        self.expiration_date = timezone.now() + timedelta(days=days)
                if self.status in (self.STATUS_ACCEPTED, self.STATUS_REJECTED,
                                   self.STATUS_SUPERSEDED, self.STATUS_EXPIRED) and not self.closed_date:
                    self.closed_date = timezone.now()
        if not self.change_order_number:
            n = ChangeOrder.objects.filter(estimate=self.estimate).count() + 1
            self.change_order_number = f'{self.estimate.estimate_number}-CO{n}'
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.change_order_number or f'ChangeOrder {self.pk}'


class WorkTemplate(models.Model):
    """Template for populating Jobs with product structure"""

    template_id = models.AutoField(primary_key=True)
    template_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Pricing
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'work_templates'

    def __str__(self):
        return self.template_name

    def generate_tasks_for_job(self, job, quantity=1):
        """Generate Tasks on a Job from this template's ServiceItems.

        Returns a list of (TemplateTaskAssociation, instance_index, Task) tuples
        so generate_materials_for_job can pair generated Materials with their
        matching Tasks.
        """
        generated = []

        for instance in range(1, quantity + 1):
            associations = TemplateTaskAssociation.objects.filter(
                work_template=self,
                service_item__is_active=True,
            ).order_by('sort_order', 'service_item__template_name')

            for association in associations:
                task = association.service_item.generate_task(
                    job,
                    est_qty=association.est_qty,
                    product_instance=instance if quantity > 1 else None,
                    sort_order=association.sort_order,
                )
                generated.append((association, instance, task))

        return generated

    def generate_materials_for_job(self, job, quantity=1, task_pairing=None):
        """Generate Materials for a job from this template's material associations.

        Pairs each association's generated Material with the matching generated
        Task via task_pairing (a list of (TemplateTaskAssociation, instance_index,
        Task) tuples returned by generate_tasks_for_job).

        If task_pairing is None, all generated materials are task-less.
        """
        from apps.inventory.services import MaterialService

        pairing = {}
        if task_pairing:
            for tta, instance, t in task_pairing:
                pairing[(tta.pk, instance)] = t

        associations = self.material_associations.all()
        for instance in range(1, quantity + 1):
            for assoc in associations:
                paired_t = None
                if assoc.template_task_association_id is not None:
                    paired_t = pairing.get((assoc.template_task_association_id, instance))
                MaterialService.create_on_job(
                    job=job, task=paired_t,
                    quantity=assoc.quantity,
                    inventory_item=assoc.inventory_item,
                )


class TemplateTaskAssociation(models.Model):
    """Association between WorkTemplate and ServiceItem with ordering."""
    work_template = models.ForeignKey(WorkTemplate, on_delete=models.CASCADE)
    service_item = models.ForeignKey('ServiceItem', on_delete=models.CASCADE)

    # Quantity and ordering
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_task_assoc'
        unique_together = ['work_template', 'service_item']
        ordering = ['sort_order']

    def __str__(self):
        return f"{self.work_template.template_name} -> {self.service_item.template_name}"


class ServiceItem(models.Model):
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

    # Relationships
    work_templates = models.ManyToManyField(WorkTemplate, through='TemplateTaskAssociation', related_name='service_items')

    created_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'service_items'

    def __str__(self):
        return self.template_name

    def clean(self):
        super().clean()

    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category

    def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                       assignee=None, sort_order=None,
                       name=None, description=None,
                       active_modifiers=None, est_worker_time=None,
                       allow_superseded_scheme=False):
        """Generate a Task on a Job from this template with specified quantity.

        Optional overrides:
          name            – if truthy, replaces template_name; empty string falls back to template default.
          description     – if not None, replaces template description (empty string is kept as-is).
          active_modifiers – list of modifier keys; falls back to template defaults when None.
          est_worker_time – ISO 8601 duration string or None.
          allow_superseded_scheme – if True, bypasses SchemeSupersededError so acceptance can
                                    crystallize a line whose scheme was superseded after the estimate
                                    was created. Default False preserves current behavior.
        """
        from apps.jobs.models import Job, Task, copy_active_modifiers
        from apps.core.services import SchemeSupersededError
        from django.db import transaction

        if (self.rate_scheme_id and self.rate_scheme.replaced_by_id is not None
                and not allow_superseded_scheme):
            raise SchemeSupersededError(
                f'Template "{self.template_name}" references a superseded '
                f'RateScheme. Update the template before adding tasks from it.'
            )

        resolved_name = name if name else self.template_name
        resolved_description = description if description is not None else self.description
        resolved_modifiers = copy_active_modifiers(
            active_modifiers if active_modifiers is not None
            else self.default_active_modifiers
        )

        if not isinstance(container, Job):
            raise ValueError(
                'generate_task only supports a Job container (job-owns-atoms refactor).'
            )
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
            from apps.jobs.services import JobService
            JobService.mark_work_reopened(container)
        return task


class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)
    adjustment_service = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+',
        help_text='Set when this line is a percentage adjustment (rush/discount).',
    )
    adjustment_target_categories = models.ManyToManyField(
        'core.AccountingCategory', blank=True, related_name='+',
        help_text='Categories the adjustment applies to; empty = all non-adjustment lines.',
    )
    is_material = models.BooleanField(
        default=False,
        help_text=(
            'Marks a bare (no inventory_item, non-adjustment) freeform line as a '
            'material: at acceptance it crystallizes into a provisional Material '
            '(sell price only, no lot) instead of a Fee.'
        ),
    )
    service_item = models.ForeignKey(
        'estimates.ServiceItem',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        help_text='Deferred service descriptor: crystallizes to a Task at acceptance.',
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
    """Polymorphic join between an EstimateLineItem and its source atom (Task, Material, or Fee).

    The unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level: an atom can be referenced by at most one estimate line item.
    """
    SOURCE_TASK = 'task'
    SOURCE_MATERIAL = 'material'
    SOURCE_FEE = 'fee'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_TASK, 'Task'),
        (SOURCE_MATERIAL, 'Material'),
        (SOURCE_FEE, 'Fee'),
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
        """Return the concrete atom instance referenced by this source."""
        if self.source_type == self.SOURCE_TASK:
            from apps.jobs.models import Task
            return Task.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_MATERIAL:
            from apps.inventory.models import Material
            return Material.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_FEE:
            from apps.jobs.models import Fee
            return Fee.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return f'Source {self.source_id}: {self.source_type}:{self.source_pk} → EstLineItem {self.estimate_line_item_id}'


class ChangeOrderLineItem(BaseLineItem):
    """Line item for change orders - carries add/remove/replace deltas against EstimateLineItems."""

    ACTION_ADD = 'add'
    ACTION_REMOVE = 'remove'
    ACTION_REPLACE = 'replace'

    CO_ACTION_CHOICES = [
        (ACTION_ADD, 'Add'),
        (ACTION_REMOVE, 'Remove'),
        (ACTION_REPLACE, 'Replace'),
    ]

    change_order = models.ForeignKey(ChangeOrder, on_delete=models.CASCADE)
    action = models.CharField(max_length=10, choices=CO_ACTION_CHOICES)
    target_line_item = models.ForeignKey(
        'estimates.EstimateLineItem',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='co_amendments',
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    is_material = models.BooleanField(
        default=False,
        help_text=(
            'Marks a bare (no inventory_item) freeform line as a material: at '
            'CO acceptance it crystallizes into a provisional Material '
            '(sell price only, no lot) instead of a Fee. Mirrors '
            'EstimateLineItem.is_material.'
        ),
    )
    service_item = models.ForeignKey(
        'estimates.ServiceItem',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        help_text='Deferred service descriptor: crystallizes to a Task at CO acceptance.',
    )

    class Meta:
        db_table = 'co_li'

    @property
    def task(self):
        """ChangeOrderLineItem has no task FK. Kept as None for BaseLineItem.source_name compatibility."""
        return None

    def get_parent_field_name(self):
        return 'change_order'

    def clean(self):
        super().clean()
        if self.action in (self.ACTION_REMOVE, self.ACTION_REPLACE):
            if not self.target_line_item_id:
                raise ValidationError(
                    f'action="{self.action}" requires target_line_item to be set.'
                )
        elif self.action == self.ACTION_ADD:
            if self.target_line_item_id:
                raise ValidationError(
                    'action="add" must not have a target_line_item.'
                )
        if self.action == self.ACTION_REMOVE:
            # A remove line's own fields are display-only; it never crystallizes
            # a new atom, so crystallization descriptors are meaningless on it.
            if self.service_item_id is not None or self.is_material:
                raise ValidationError(
                    'action="remove" cannot carry a service item or material marker.'
                )

    def __str__(self):
        return f'CO Line Item {self.pk}: {self.action} — {self.description[:50]}'


class ChangeOrderLineItemSource(models.Model):
    """Polymorphic join between a ChangeOrderLineItem and the atom it crystallized.

    The CO analog of EstimateLineItemSource: created at CO acceptance for each
    add/replace line, pointing at the Task/Material/Fee the line produced. It is
    both the provenance record (compose_agreement traces crystallized CO fees so
    the invoice claims them once) and the idempotency marker (a line with a
    source row is already crystallized and is skipped on re-run). The
    unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level within the CO lens.
    """
    SOURCE_TASK = 'task'
    SOURCE_MATERIAL = 'material'
    SOURCE_FEE = 'fee'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_TASK, 'Task'),
        (SOURCE_MATERIAL, 'Material'),
        (SOURCE_FEE, 'Fee'),
    ]

    source_id = models.AutoField(primary_key=True)
    change_order_line_item = models.ForeignKey(
        ChangeOrderLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'co_li_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        """Return the concrete atom instance referenced by this source."""
        if self.source_type == self.SOURCE_TASK:
            from apps.jobs.models import Task
            return Task.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_MATERIAL:
            from apps.inventory.models import Material
            return Material.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_FEE:
            from apps.jobs.models import Fee
            return Fee.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return (f'CO Source {self.source_id}: {self.source_type}:{self.source_pk} '
                f'→ COLineItem {self.change_order_line_item_id}')
