from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from decimal import Decimal


class User(AbstractUser):
    """Custom user model extending Django's AbstractUser with business-specific fields."""
    
    # Business-specific fields
    contact = models.OneToOneField(
        'contacts.Contact', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text='Associated contact record for this user'
    )
    
    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'



class Configuration(models.Model):
    """
    Simple key-value configuration storage.

    Examples:
        - key="job_number_sequence", value="JOB-{year}-{counter:04d}"
        - key="job_counter", value="0"
        - key="estimate_number_sequence", value="EST-{year}-{counter:04d}"
        - key="estimate_counter", value="0"
    """
    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return f"{self.key}: {self.value}"

    class Meta:
        verbose_name = "Configuration"
        verbose_name_plural = "Configurations"


class LineItemType(models.Model):
    """
    Defines categories of line items with default taxability.
    Examples: Service, Material, Product, Freight, Overhead
    """
    code = models.CharField(max_length=20, unique=True)  # e.g., "SVC", "MAT", "PRD"
    name = models.CharField(max_length=100)  # e.g., "Service", "Material", "Product"
    taxable = models.BooleanField(default=True)  # Default taxability for this type
    default_units = models.CharField(max_length=50, blank=True)  # e.g., "hours", "each"
    default_description = models.TextField(blank=True)  # Template for descriptions
    is_active = models.BooleanField(default=True)  # Soft delete support

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class BaseLineItem(models.Model):
    """
    Abstract base class for all line item types.
    Provides shared functionality for EstimateLineItem, InvoiceLineItem,
    PurchaseOrderLineItem, and BillLineItem.
    """
    line_item_id = models.AutoField(primary_key=True)
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT, null=True, blank=True)  # Changed from CASCADE - protect document integrity
    price_list_item = models.ForeignKey('invoicing.PriceListItem', on_delete=models.PROTECT, null=True, blank=True)  # Changed from CASCADE - protect historical documents
    line_number = models.PositiveIntegerField(blank=True, null=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    units = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    price_currency = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Tax-related fields
    line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT,
        related_name='%(class)s_items',
        null=True,  # Nullable initially for migration; will be made required after data migration
        blank=True
    )
    taxable_override = models.BooleanField(null=True, blank=True)  # null = use type default
    tax_rate_override = models.DecimalField(
        max_digits=5,
        decimal_places=4,  # Supports rates like 0.0825 (8.25%)
        null=True,
        blank=True
    )  # null = use app default

    class Meta:
        abstract = True

    def clean(self):
        """Validate that line item cannot have both task and price_list_item."""
        super().clean()
        has_task = self.task is not None
        has_price_item = self.price_list_item is not None

        if has_task and has_price_item:
            raise ValidationError("LineItem cannot have both task and price_list_item")

    def save(self, *args, **kwargs):
        """Override save to ensure validation is always run and handle automatic line numbering."""
        from django.db import transaction

        if self.line_number is None:
            with transaction.atomic():
                # Get the parent field name from the concrete model
                parent_field_name = self.get_parent_field_name()
                parent_obj = getattr(self, parent_field_name)

                if parent_obj:
                    # Use select_for_update to prevent race conditions
                    max_line = self.__class__.objects.filter(
                        **{parent_field_name: parent_obj}
                    ).select_for_update().aggregate(
                        max_line=models.Max('line_number')
                    )['max_line']
                    self.line_number = (max_line or 0) + 1
                else:
                    self.line_number = 1

        self.full_clean()
        super().save(*args, **kwargs)

    def get_parent_field_name(self):
        """Override in subclasses to specify the parent field name."""
        raise NotImplementedError("Subclasses must implement get_parent_field_name")

    def __str__(self):
        return f"Line Item {self.pk}: {self.description[:50]}"

    @property
    def total_amount(self):
        """Calculate total amount (quantity * price)."""
        return self.qty * self.price_currency

    @property
    def source_name(self):
        """Get the name of the source (task name or price list item description)."""
        if self.task:
            return self.task.name
        elif self.price_list_item:
            return self.price_list_item.description
        return "No source"