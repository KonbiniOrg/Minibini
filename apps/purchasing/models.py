from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.core.models import BaseLineItem


# Status choices for PurchaseOrder
PO_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('issued', 'Issued'),
    ('partly_received', 'Partly Received'),
    ('received_in_full', 'Received in Full'),
    ('cancelled', 'Cancelled'),
]

# Status choices for Bill
BILL_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('received', 'Received'),
    ('partly_paid', 'Partly Paid'),
    ('paid_in_full', 'Paid in Full'),
    ('cancelled', 'Cancelled'),
    ('refunded', 'Refunded'),
]


class PurchaseOrder(models.Model):
    po_id = models.AutoField(primary_key=True)
    # Business is required; Contact is optional but if provided, must have a Business
    business = models.ForeignKey('contacts.Business', on_delete=models.PROTECT)
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, null=True, blank=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.SET_NULL, null=True, blank=True)
    po_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=PO_STATUS_CHOICES, default='draft')

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
            'draft': ['issued'],
            'issued': ['partly_received', 'received_in_full', 'cancelled'],
            'partly_received': ['received_in_full'],
            'received_in_full': [],  # Terminal state
            'cancelled': [],  # Terminal state
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
                    if self.status == 'issued' and not self.issued_date:
                        self.issued_date = timezone.now()

                    # Transitioning to 'received_in_full' - set received_date
                    if self.status == 'received_in_full' and not self.received_date:
                        self.received_date = timezone.now()

                    # Transitioning to 'cancelled' - set cancel_date
                    if self.status == 'cancelled' and not self.cancel_date:
                        self.cancel_date = timezone.now()

            except PurchaseOrder.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to enforce that only draft POs can be deleted."""
        if self.status != 'draft':
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(
                f'Cannot delete Purchase Order {self.po_number}. '
                'Only Purchase Orders in Draft status can be deleted.'
            )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"PO {self.po_number}"


class Bill(models.Model):
    bill_id = models.AutoField(primary_key=True)
    bill_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, null=True, blank=True)
    # Business is required; Contact is optional but if provided, must have a Business
    business = models.ForeignKey('contacts.Business', on_delete=models.PROTECT)
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, null=True, blank=True)
    vendor_invoice_number = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=BILL_STATUS_CHOICES, default='draft')

    # Date fields
    created_date = models.DateTimeField(default=timezone.now)
    due_date = models.DateTimeField(null=True, blank=True)
    received_date = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    cancelled_date = models.DateTimeField(null=True, blank=True)

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
        if self.purchase_order and self.purchase_order.status == 'draft':
            raise ValidationError(
                'Bills can only be created from Purchase Orders that are in Issued or later status. '
                f'Purchase Order {self.purchase_order.po_number} is currently in Draft status.'
            )

        # Define valid transitions for each state
        VALID_TRANSITIONS = {
            'draft': ['received'],
            'received': ['partly_paid', 'paid_in_full', 'cancelled'],
            'partly_paid': ['paid_in_full'],
            'paid_in_full': ['refunded'],
            'cancelled': [],  # Terminal state
            'refunded': [],  # Terminal state
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
                if old_status == 'draft' and self.status != 'draft':
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
                    if self.status == 'received' and not self.received_date:
                        self.received_date = timezone.now()

                    # Transitioning to 'paid_in_full' - set paid_date
                    if self.status == 'paid_in_full' and not self.paid_date:
                        self.paid_date = timezone.now()

                    # Transitioning to 'cancelled' - set cancelled_date
                    if self.status == 'cancelled' and not self.cancelled_date:
                        self.cancelled_date = timezone.now()

            except Bill.DoesNotExist:
                pass

        # Run validation
        self.full_clean()

        # Call parent save
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to enforce that only draft Bills can be deleted."""
        if self.status != 'draft':
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(
                f'Cannot delete Bill {self.bill_number}. '
                'Only Bills in Draft status can be deleted.'
            )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Bill {self.bill_number}"


class PurchaseOrderLineItem(BaseLineItem):
    """Line item for purchase orders - inherits shared functionality from BaseLineItem."""

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE)

    class Meta:
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

    class Meta:
        verbose_name = "Bill Line Item"
        verbose_name_plural = "Bill Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'bill'

    def __str__(self):
        return f"Bill Line Item {self.pk} for Bill {self.bill.bill_number}"