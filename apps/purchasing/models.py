from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.core.models import BaseLineItem
from apps.core.history import history


@history(exclude=['po_id'])
class PurchaseOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ISSUED = 'issued'
    STATUS_PARTLY_RECEIVED = 'partly_received'
    STATUS_RECEIVED_IN_FULL = 'received_in_full'
    STATUS_CANCELLED = 'cancelled'

    PO_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_ISSUED, 'Issued'),
        (STATUS_PARTLY_RECEIVED, 'Partly Received'),
        (STATUS_RECEIVED_IN_FULL, 'Received in Full'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    po_id = models.AutoField(primary_key=True)
    # Business is required; Contact is optional but if provided, must have a Business
    business = models.ForeignKey('contacts.Business', on_delete=models.PROTECT)
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, null=True, blank=True)
    po_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=PO_STATUS_CHOICES, default=STATUS_DRAFT)

    # Date fields
    created_date = models.DateTimeField(default=timezone.now)
    requested_date = models.DateTimeField(null=True, blank=True)
    issued_date = models.DateTimeField(null=True, blank=True)
    received_date = models.DateTimeField(null=True, blank=True)
    cancel_date = models.DateTimeField(null=True, blank=True)

    def clean(self):
        """Validate PurchaseOrder state transitions and protect immutable date fields."""
        super().clean()

        # Validate that if contact is provided, it must have a business
        if self.contact and not self.contact.business:
            raise ValidationError(
                f'Contact "{self.contact}" does not have a Business associated. '
                'Please assign a Business to this Contact before using it in a Purchase Order.'
            )

        # Validate that if both contact and business are provided, they must match
        # Only check on creation (not on updates, since contact's business might change after PO creation)
        is_new = not self.pk
        if is_new and self.contact and self.contact.business and self.business_id:
            if self.business != self.contact.business:
                raise ValidationError(
                    f'Contact "{self.contact}" is associated with Business "{self.contact.business.business_name}", '
                    f'but Purchase Order is set to use Business "{self.business.business_name}". '
                    'The Business must match the Contact\'s Business.'
                )

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            PurchaseOrder.STATUS_DRAFT: [PurchaseOrder.STATUS_ISSUED],
            PurchaseOrder.STATUS_ISSUED: [PurchaseOrder.STATUS_PARTLY_RECEIVED, PurchaseOrder.STATUS_RECEIVED_IN_FULL, PurchaseOrder.STATUS_CANCELLED],
            PurchaseOrder.STATUS_PARTLY_RECEIVED: [PurchaseOrder.STATUS_RECEIVED_IN_FULL],
            PurchaseOrder.STATUS_RECEIVED_IN_FULL: [],  # Terminal state
            PurchaseOrder.STATUS_CANCELLED: [],  # Terminal state
        }

        # Check if this is an update
        if self.pk:
            try:
                old_po = PurchaseOrder.objects.get(pk=self.pk)
                old_status = old_po.status

                # Protect immutable date fields
                if old_po.created_date and self.created_date != old_po.created_date:
                    self.created_date = old_po.created_date

                if old_po.issued_date and self.issued_date != old_po.issued_date:
                    self.issued_date = old_po.issued_date

                if old_po.received_date and self.received_date != old_po.received_date:
                    self.received_date = old_po.received_date

                if old_po.cancel_date and self.cancel_date != old_po.cancel_date:
                    self.cancel_date = old_po.cancel_date

                # If status hasn't changed, no validation needed
                if old_status == self.status:
                    return

                # Check if the transition is valid
                valid_next_states = VALID_TRANSITIONS.get(old_status, [])
                if self.status not in valid_next_states:
                    raise ValidationError(
                        f'Cannot transition PurchaseOrder from {old_status} to {self.status}. '
                        f'Valid transitions from {old_status} are: {", ".join(valid_next_states) if valid_next_states else "none (terminal state)"}'
                    )

                # If transitioning out of draft, ensure at least one line item exists
                if old_status == PurchaseOrder.STATUS_DRAFT and self.status != PurchaseOrder.STATUS_DRAFT:
                    if not PurchaseOrderLineItem.objects.filter(purchase_order=self).exists():
                        raise ValidationError(
                            'Cannot change Purchase Order status from Draft without at least one line item.'
                        )

            except PurchaseOrder.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        """Override save to validate state transitions, set dates, auto-generate po_number, and auto-associate Business from Contact."""
        from apps.core.services import NumberGenerationService

        old_status = None
        is_new = not self.pk

        # Auto-generate po_number if not provided
        if not self.po_number:
            self.po_number = NumberGenerationService.generate_next_number('po')

        # If contact is provided and has a business, auto-associate the business
        # Only do this on creation and if business is not already explicitly set
        if is_new and self.contact and self.contact.business and not self.business_id:
            self.business = self.contact.business

        # Check if this is an update (not a new object)
        if self.pk:
            try:
                old_po = PurchaseOrder.objects.get(pk=self.pk)
                old_status = old_po.status

                # Handle state transition date setting
                if old_status != self.status:
                    # Transitioning to 'issued' - set issued_date
                    if self.status == PurchaseOrder.STATUS_ISSUED and not self.issued_date:
                        self.issued_date = timezone.now()

                    # Transitioning to 'received_in_full' - set received_date
                    if self.status == PurchaseOrder.STATUS_RECEIVED_IN_FULL and not self.received_date:
                        self.received_date = timezone.now()

                    # Transitioning to 'cancelled' - set cancel_date
                    if self.status == PurchaseOrder.STATUS_CANCELLED and not self.cancel_date:
                        self.cancel_date = timezone.now()

            except PurchaseOrder.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to enforce that only draft POs can be deleted."""
        if self.status != PurchaseOrder.STATUS_DRAFT:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(
                f'Cannot delete Purchase Order {self.po_number}. '
                'Only Purchase Orders in Draft status can be deleted.'
            )
        return super().delete(*args, **kwargs)

    class Meta:
        db_table = 'pos'

    def __str__(self):
        return f"PO {self.po_number}"


@history(exclude=['bill_id'])
class Bill(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_RECEIVED = 'received'
    STATUS_PARTLY_PAID = 'partly_paid'
    STATUS_PAID_IN_FULL = 'paid_in_full'
    STATUS_CANCELLED = 'cancelled'
    STATUS_REFUNDED = 'refunded'

    BILL_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_RECEIVED, 'Received'),
        (STATUS_PARTLY_PAID, 'Partly Paid'),
        (STATUS_PAID_IN_FULL, 'Paid in Full'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    bill_id = models.AutoField(primary_key=True)
    bill_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, null=True, blank=True)
    # Business is required; Contact is optional but if provided, must have a Business
    business = models.ForeignKey('contacts.Business', on_delete=models.PROTECT)
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, null=True, blank=True)
    vendor_invoice_number = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=BILL_STATUS_CHOICES, default=STATUS_DRAFT)

    # Date fields
    created_date = models.DateTimeField(default=timezone.now)
    due_date = models.DateTimeField(null=True, blank=True)
    received_date = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    cancelled_date = models.DateTimeField(null=True, blank=True)

    # QuickBooks Online sync
    qbo_id = models.CharField(max_length=50, null=True, blank=True)
    qbo_payment_status = models.CharField(max_length=50, blank=True, default='')

    def clean(self):
        """Validate Bill state transitions, protect immutable date fields, and enforce line item requirement."""
        super().clean()

        # Validate that if contact is provided, it must have a business
        if self.contact and not self.contact.business:
            raise ValidationError(
                f'Contact "{self.contact}" does not have a Business associated. '
                'Please assign a Business to this Contact before using it in a Bill.'
            )

        # Validate that if both contact and business are provided, they must match
        # Only check on creation (not on updates, since contact's business might change after Bill creation)
        is_new = not self.pk
        if is_new and self.contact and self.contact.business and self.business_id:
            if self.business != self.contact.business:
                raise ValidationError(
                    f'Contact "{self.contact}" is associated with Business "{self.contact.business.business_name}", '
                    f'but Bill is set to use Business "{self.business.business_name}". '
                    'The Business must match the Contact\'s Business.'
                )

        # Validate that PO is in issued or later status (not draft)
        if self.purchase_order and self.purchase_order.status == PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Bills can only be created from Purchase Orders that are in Issued or later status. '
                f'Purchase Order {self.purchase_order.po_number} is currently in Draft status.'
            )

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            Bill.STATUS_DRAFT: [Bill.STATUS_RECEIVED],
            Bill.STATUS_RECEIVED: [Bill.STATUS_PARTLY_PAID, Bill.STATUS_PAID_IN_FULL, Bill.STATUS_CANCELLED],
            Bill.STATUS_PARTLY_PAID: [Bill.STATUS_PAID_IN_FULL],
            Bill.STATUS_PAID_IN_FULL: [Bill.STATUS_REFUNDED],
            Bill.STATUS_CANCELLED: [],  # Terminal state
            Bill.STATUS_REFUNDED: [],  # Terminal state
        }

        # Check if this is an update
        if self.pk:
            try:
                old_bill = Bill.objects.get(pk=self.pk)
                old_status = old_bill.status

                # Protect immutable date fields
                if old_bill.created_date and self.created_date != old_bill.created_date:
                    self.created_date = old_bill.created_date

                if old_bill.received_date and self.received_date != old_bill.received_date:
                    self.received_date = old_bill.received_date

                if old_bill.paid_date and self.paid_date != old_bill.paid_date:
                    self.paid_date = old_bill.paid_date

                if old_bill.cancelled_date and self.cancelled_date != old_bill.cancelled_date:
                    self.cancelled_date = old_bill.cancelled_date

                # If status hasn't changed, no validation needed
                if old_status == self.status:
                    return

                # Check if the transition is valid
                valid_next_states = VALID_TRANSITIONS.get(old_status, [])
                if self.status not in valid_next_states:
                    raise ValidationError(
                        f'Cannot transition Bill from {old_status} to {self.status}. '
                        f'Valid transitions from {old_status} are: {", ".join(valid_next_states) if valid_next_states else "none (terminal state)"}'
                    )

                # If transitioning out of draft, ensure at least one line item exists
                if old_status == Bill.STATUS_DRAFT and self.status != Bill.STATUS_DRAFT:
                    line_item_count = BillLineItem.objects.filter(bill=self).count()
                    if line_item_count == 0:
                        raise ValidationError(
                            'Cannot change Bill status from Draft without at least one line item. '
                            'Please add at least one line item before changing the status.'
                        )

            except Bill.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        """Override save to validate state transitions, set dates, auto-generate bill_number, and auto-associate Business from Contact."""
        from apps.core.services import NumberGenerationService

        old_status = None
        is_new = not self.pk

        # Auto-generate bill_number if not provided
        if not self.bill_number:
            self.bill_number = NumberGenerationService.generate_next_number('bill')

        # If contact is provided and has a business, auto-associate the business
        # Only do this on creation and if business is not already explicitly set
        if is_new and self.contact and self.contact.business and not self.business_id:
            self.business = self.contact.business

        # Check if this is an update (not a new object)
        if self.pk:
            try:
                old_bill = Bill.objects.get(pk=self.pk)
                old_status = old_bill.status

                # Handle state transition date setting
                if old_status != self.status:
                    # Transitioning to 'received' - set received_date
                    if self.status == Bill.STATUS_RECEIVED and not self.received_date:
                        self.received_date = timezone.now()

                    # Transitioning to 'paid_in_full' - set paid_date
                    if self.status == Bill.STATUS_PAID_IN_FULL and not self.paid_date:
                        self.paid_date = timezone.now()

                    # Transitioning to 'cancelled' - set cancelled_date
                    if self.status == Bill.STATUS_CANCELLED and not self.cancelled_date:
                        self.cancelled_date = timezone.now()

            except Bill.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to enforce that only draft Bills can be deleted."""
        if self.status != Bill.STATUS_DRAFT:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(
                f'Cannot delete Bill {self.bill_number}. '
                'Only Bills in Draft status can be deleted.'
            )
        return super().delete(*args, **kwargs)

    class Meta:
        db_table = 'bills'

    def __str__(self):
        return f"Bill {self.bill_number}"


class PurchaseOrderLineItem(BaseLineItem):
    """Line item for purchase orders - inherits shared functionality from BaseLineItem."""

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE)
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT, null=True, blank=True)
    job = models.ForeignKey(
        'jobs.Job', on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    # Receiving fields
    qty_received = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    received_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='received_po_line_items',
    )
    received_date = models.DateTimeField(null=True, blank=True)
    receipt_note = models.TextField(blank=True, default='')
    qty_cancelled = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        db_table = 'po_li'
        verbose_name = "Purchase Order Line Item"
        verbose_name_plural = "Purchase Order Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'purchase_order'

    def __str__(self):
        return f"PO Line Item {self.pk} for {self.purchase_order.po_number}"


class BillLineItem(BaseLineItem):
    """Line item for bills - inherits shared functionality from BaseLineItem."""

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE)
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        db_table = 'bill_li'
        verbose_name = "Bill Line Item"
        verbose_name_plural = "Bill Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'bill'

    def __str__(self):
        return f"Bill Line Item {self.pk} for Bill {self.bill.bill_number}"