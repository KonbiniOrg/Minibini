from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models


class Expense(models.Model):
    PAYMENT_METHOD_COMPANY = 'company'
    PAYMENT_METHOD_PERSONAL = 'personal'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_COMPANY, 'Company'),
        (PAYMENT_METHOD_PERSONAL, 'Personal (reimbursement)'),
    ]

    STATUS_SUBMITTED = 'submitted'
    STATUS_REIMBURSED = 'reimbursed'
    STATUS_REJECTED = 'rejected'
    STATUS_SYNCED = 'synced'
    STATUS_SYNC_FAILED = 'sync_failed'
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_REIMBURSED, 'Reimbursed'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_SYNCED, 'Synced to QBO'),
        (STATUS_SYNC_FAILED, 'QBO sync failed'),
    ]

    entered_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT,
        related_name='entered_expenses',
    )
    purchased_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='purchased_expenses',
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purchased_on = models.DateField()
    description = models.TextField(blank=True, default='')
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT,
    )

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_account_id = models.CharField(max_length=50, blank=True, default='')
    reference_number = models.CharField(max_length=50, blank=True, default='')

    job = models.ForeignKey(
        'jobs.Job', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='expenses',
    )

    material = models.ForeignKey(
        'inventory.Material', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='expenses',
    )

    # Stock-receipt mode: an inventoried-PLI purchase. QOH goes up by stock_qty;
    # the amount is NOT job-costed (cost flows at consumption). Mutually exclusive
    # with `material` (the cost-expense mode).
    stock_pli = models.ForeignKey(
        'inventory.InventoryItem', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    stock_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED,
    )
    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_sync_error = models.TextField(blank=True, default='')

    reimbursement = models.ForeignKey(
        'expenses.Reimbursement', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='expenses',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['-purchased_on', '-created_at']

    def clean(self):
        super().clean()
        errors = {}
        if self.payment_method == self.PAYMENT_METHOD_PERSONAL:
            if not self.purchased_by_id:
                errors['purchased_by'] = 'Required for personal (reimbursement) expenses.'
            if self.payment_account_id:
                errors['payment_account_id'] = 'Not allowed for personal expenses.'
        elif self.payment_method == self.PAYMENT_METHOD_COMPANY:
            if not self.payment_account_id:
                errors['payment_account_id'] = 'Required for company-paid expenses.'
        if self.material_id and self.job_id and self.material.job_id != self.job_id:
            errors['job'] = 'Expense job must match the linked material’s job.'
        if self.stock_pli_id:
            if self.material_id:
                errors['stock_pli'] = (
                    'A stock-receipt expense cannot also create a consumable '
                    'material — record the stock purchase separately.'
                )
            if not self.stock_qty or self.stock_qty <= Decimal('0.00'):
                errors['stock_qty'] = 'Stock quantity must be positive.'
            if self.stock_pli and not self.stock_pli.is_catalog:
                errors['stock_pli'] = (
                    'Stock receipts are only for inventoried price-list items.'
                )
        if errors:
            raise ValidationError(errors)

    def compute_amount(self, active_modifiers=None):
        """Uniform billable-atom interface (shared with Material/Task): a
        material-less expense bills at pass-through cost. The parameter is
        accepted to match the atom interface and is ignored."""
        return self.amount

    def __str__(self):
        return f"Expense {self.pk}: ${self.amount} ({self.status})"


class Reimbursement(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SYNCED = 'synced'
    STATUS_SYNC_FAILED = 'sync_failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SYNCED, 'Synced to QBO'),
        (STATUS_SYNC_FAILED, 'QBO sync failed'),
    ]

    purchased_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT,
        related_name='reimbursements',
    )
    paid_on = models.DateField()
    payment_account_id = models.CharField(max_length=50)
    reference_number = models.CharField(max_length=50, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT,
        related_name='created_reimbursements',
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_sync_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reimbursements'
        ordering = ['-paid_on', '-created_at']

    @property
    def total(self):
        return sum(
            (e.amount for e in self.expenses.all()),
            Decimal('0'),
        )

    def __str__(self):
        return f"Reimbursement {self.pk}: {self.purchased_by.username} on {self.paid_on}"
