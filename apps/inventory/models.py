from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.history import history


class Earmark(models.Model):
    earmark_id = models.AutoField(primary_key=True)
    inventory_item = models.ForeignKey('InventoryItem', on_delete=models.CASCADE)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    created_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'earmarks'
        unique_together = [('inventory_item', 'job')]

    def __str__(self):
        return f"{self.inventory_item.code} earmarked {self.quantity} for {self.job.job_number}"


class InventoryItem(models.Model):
    inventory_item_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=50, unique=True)
    units = models.CharField(max_length=50, default='none')
    description = models.TextField(blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_on_hand = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_sold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_wasted = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)  # For soft-delete - use instead of hard deletion

    # AccountingCategory for categorization and taxability
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        related_name='inventory_items',
    )

    @property
    def qty_earmarked(self):
        """Total quantity earmarked across all jobs."""
        total = self.earmark_set.aggregate(
            total=models.Sum('quantity')
        )['total']
        return total or Decimal('0.00')

    @property
    def qty_available(self):
        """Quantity available (on hand minus earmarked)."""
        return self.qty_on_hand - self.qty_earmarked

    @property
    def qty_on_order(self):
        """Outstanding (un-received) quantity across this item's PO lines on
        non-cancelled POs: Σ max(qty − qty_received − qty_cancelled, 0). The
        same outstanding calc MaterialSerializer.get_qty_on_order does for a
        single PO-linked material, aggregated per item. Per-line floor so an
        over-received line can't eat another line's outstanding quantity."""
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
        total = Decimal('0.00')
        lines = PurchaseOrderLineItem.objects.filter(
            inventory_item=self,
        ).exclude(purchase_order__status=PurchaseOrder.STATUS_CANCELLED)
        for li in lines:
            outstanding = li.qty - li.qty_received - li.qty_cancelled
            if outstanding > Decimal('0.00'):
                total += outstanding
        return total

    class Meta:
        db_table = 'inventory_item'
        constraints = [
            models.CheckConstraint(
                check=models.Q(qty_on_hand__gte=0),
                name='price_list_qty_on_hand_non_negative',
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.description[:50]}"

    @property
    def can_be_deleted(self):
        """
        Check if this price list item can be safely deleted.
        Returns False if any line items reference it.
        """
        from apps.estimates.models import EstimateLineItem
        from apps.invoicing.models import InvoiceLineItem
        from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem

        return not (
            EstimateLineItem.objects.filter(inventory_item=self).exists() or
            InvoiceLineItem.objects.filter(inventory_item=self).exists() or
            PurchaseOrderLineItem.objects.filter(inventory_item=self).exists() or
            BillLineItem.objects.filter(inventory_item=self).exists() or
            self.earmark_set.exists()
        )


class MaterialBase(models.Model):
    """Abstract base for Material (actual)."""
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    units = models.CharField(max_length=50, default='none')
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    inventory_item = models.ForeignKey(
        'InventoryItem', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True

    def copy_fields(self):
        """Canonical MaterialBase field set for cloning to another container.

        Returns the FKs (inventory_item, accounting_category) as *objects* so
        the dict splats straight into ``MaterialService.create_on_job`` (whose
        params are the objects); raw ``.objects.create()`` accepts objects too.
        """
        return dict(
            description=self.description,
            quantity=self.quantity,
            units=self.units,
            unit_cost=self.unit_cost,
            sell_price=self.sell_price,
            inventory_item=self.inventory_item,
            accounting_category=self.accounting_category,
        )

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost

    @property
    def total_sell(self):
        return self.quantity * self.sell_price

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this material.

        Materials have no modifier concept; the parameter is accepted to match
        the BillableAtom interface shared with Task.
        """
        return self.quantity * self.sell_price

    def _populate_from_pli(self):
        """Copy description/units/unit_cost/sell_price/accounting_category from linked InventoryItem if not already set."""
        if self.inventory_item:
            if not self.description:
                self.description = self.inventory_item.description[:255]
            if self.units == 'none' or not self.units:
                self.units = self.inventory_item.units
            if self.unit_cost == Decimal('0.00'):
                self.unit_cost = self.inventory_item.purchase_price
            if self.sell_price == Decimal('0.00'):
                self.sell_price = self.inventory_item.selling_price
            if not self.accounting_category_id:
                self.accounting_category = self.inventory_item.accounting_category


class TemplateMaterialAssociation(models.Model):
    """A reusable InventoryItem associated with a WorkTemplate.

    Replaces the old TemplateMaterial model: PLI is already the catalog of
    reusable materials, so a TemplateMaterial-as-separate-catalog was
    redundant. This model just pins which PLI belongs to which WorkTemplate
    (with quantity), optionally pairing to a TemplateTaskAssociation so the
    generated Material attaches to the corresponding generated Task.

    Generation semantics: for `quantity` instances of the parent WorkTemplate,
    each instance gets one Material per association, attached
    to the same-instance Task when `template_task_association` is set.
    """
    template_material_association_id = models.AutoField(primary_key=True)
    work_template = models.ForeignKey(
        'estimates.WorkTemplate', on_delete=models.CASCADE,
        related_name='material_associations',
    )
    inventory_item = models.ForeignKey(
        'InventoryItem', on_delete=models.PROTECT,
    )
    template_task_association = models.ForeignKey(
        'estimates.TemplateTaskAssociation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='material_associations',
        help_text='If set, generated material attaches to the corresponding '
                  'generated Task.',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_material_assoc'
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.work_template.template_name} → {self.inventory_item.code} (qty {self.quantity})'

    def clean(self):
        super().clean()
        if (
            self.template_task_association_id is not None
            and self.template_task_association.work_template_id != self.work_template_id
        ):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                'template_task_association.work_template must match work_template'
            )


@history(exclude=['material_id'])
class Material(MaterialBase):
    """Actual material on a Job; optionally attached to a Task. Participates in earmark/QOH flows.

    Lifecycle (consumption_state): born `pending` (planned; earmarked on
    committed jobs) → `consumed` (task start drew the stock; reversible via
    unconsume) or `released` (a named event said the job planned it and didn't
    use it — full restock while referenced, job-completion loose release, PO
    sever, CO descope; terminal). A pending material that nothing references
    may instead be hard-deleted (mistake correction / scratch paper). Release
    moves quantity into released_qty, so released rows sum to zero in every
    aggregate consumer; quantity + released_qty = originally planned.
    """
    CONSUMPTION_STATE_PENDING = 'pending'
    CONSUMPTION_STATE_CONSUMED = 'consumed'
    CONSUMPTION_STATE_RELEASED = 'released'
    CONSUMPTION_STATE_CHOICES = [
        (CONSUMPTION_STATE_PENDING, 'Pending'),
        (CONSUMPTION_STATE_CONSUMED, 'Consumed'),
        (CONSUMPTION_STATE_RELEASED, 'Released'),
    ]

    # Provenance: where this material's cost/backing came from. NULL =
    # provisional (no lot, no meaningful pricing yet). One field answers both
    # "is this cost real?" and "who owns this thing?" (spec §cost_source).
    COST_SOURCE_ESTIMATED = 'estimated'          # reverse-markup placeholder — cost unconfirmed
    COST_SOURCE_ENTERED = 'entered'              # user-entered / catalog-attached pricing
    COST_SOURCE_PO = 'po'                        # real document cost from a PO line
    COST_SOURCE_EXPENSE = 'expense'              # real document cost from an attached expense
    COST_SOURCE_CUSTOMER = 'customer_supplied'   # $0, deliberate and locked
    COST_SOURCE_CHOICES = [
        (COST_SOURCE_ESTIMATED, 'Estimated'),
        (COST_SOURCE_ENTERED, 'Entered'),
        (COST_SOURCE_PO, 'PO'),
        (COST_SOURCE_EXPENSE, 'Expense'),
        (COST_SOURCE_CUSTOMER, 'Customer supplied'),
    ]

    material_id = models.AutoField(primary_key=True)
    task = models.ForeignKey(
        'jobs.Task', on_delete=models.SET_NULL, related_name='materials',
        null=True, blank=True,  # nullable; task-less materials attach directly to job
    )
    job = models.ForeignKey(
        'jobs.Job', on_delete=models.CASCADE, related_name='materials',
    )
    consumption_state = models.CharField(
        max_length=20, choices=CONSUMPTION_STATE_CHOICES,
        default=CONSUMPTION_STATE_PENDING,
    )
    released_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text=(
            'Quantity restocked/released back out of the plan. '
            'quantity + released_qty = originally planned.'
        ),
    )
    po_line_item = models.ForeignKey(
        'purchasing.PurchaseOrderLineItem',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    cost_source = models.CharField(
        max_length=20, choices=COST_SOURCE_CHOICES, null=True, blank=True,
        help_text='Cost provenance; NULL means provisional (unpriced).',
    )

    class Meta:
        db_table = 'materials'

    @property
    def is_expense_bound(self):
        return self.expenses.exists()

    @property
    def is_customer_supplied(self):
        return self.cost_source == self.COST_SOURCE_CUSTOMER

    def clean(self):
        super().clean()
        if self.task_id and self.job_id and self.task.job_id != self.job_id:
            raise ValidationError('Material.task.job must match Material.job')
        if self.released_qty < Decimal('0.00'):
            raise ValidationError('released_qty must be non-negative')

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        if not self.pk and not self.consumption_state:
            self.consumption_state = self.CONSUMPTION_STATE_PENDING
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # No estimate/CO source row may outlive its atom — purge on every
        # deletion path (restock-to-zero, PO sever, CO retirement, …).
        from apps.estimates.claims import purge_source_rows_for_atom
        pk = self.pk
        result = super().delete(*args, **kwargs)
        purge_source_rows_for_atom('material', pk)
        return result

    def __str__(self):
        if self.units and self.units != 'none':
            return f"{self.description} (qty: {self.quantity:.2f} {self.units})"
        return f"{self.description} (qty: {self.quantity:.2f})"
