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
        permissions = [
            ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks, contacts'),
            ('can_manage_financials', 'Can manage invoices, POs, bills, price list'),
            ('can_manage_time', "Can edit/delete anyone's time entries"),
            ('can_manage_config', 'Can manage settings, templates, user admin'),
        ]



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

#    email_retention_days = models.IntegerField(
#        default=90,
#        help_text='Number of days to retain temporary email data before deletion'
#    )
#    latest_email_date = models.DateTimeField(
#        null=True,
#        blank=True,
#        help_text='Most recent email date fetched from IMAP server'
#    )
#    email_display_limit = models.IntegerField(
#        default=30,
#        help_text='Number of emails to display in inbox'
#    )
#

    def __str__(self):
        return f"{self.key}: {self.value}"

    class Meta:
        db_table = 'config'
        verbose_name = "Configuration"
        verbose_name_plural = "Configurations"


class EmailRecord(models.Model):
    """
    Permanent record of an email's association with a job.
    Contains only the minimum data needed to link and retrieve the email.
    This record is never automatically deleted.
    """
    email_record_id = models.AutoField(primary_key=True)

    # IMAP identifier - required for fetching from server
    message_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text='RFC 2822 Message-ID header'
    )

    # Job association
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_records',
        help_text='Associated job for this email'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_record'
        verbose_name = 'Email Record'
        verbose_name_plural = 'Email Records'
        ordering = ['-created_at']

    def __str__(self):
        return f"Email {self.message_id[:50]}"


class TempEmail(models.Model):
    """
    Temporary cache of email metadata fetched from IMAP server.
    This data duplicates what's on the email server and can be deleted
    after a configurable retention period.
    """
    temp_email_id = models.AutoField(primary_key=True)

    # Link to permanent record
    email_record = models.OneToOneField(
        EmailRecord,
        on_delete=models.CASCADE,
        related_name='temp_data'
    )

    # IMAP UID (server-specific identifier for fetching)
    uid = models.CharField(
        max_length=100,
        db_index=True,
        help_text='IMAP UID for fetching message content'
    )

    # Email metadata (duplicated from server for display)
    subject = models.CharField(max_length=500, blank=True)
    from_email = models.EmailField()
    to_email = models.TextField(help_text='Comma-separated email addresses')
    cc_email = models.TextField(blank=True, help_text='Comma-separated email addresses')
    date_sent = models.DateTimeField()

    # Flags
    is_read = models.BooleanField(default=False)
    is_starred = models.BooleanField(default=False)
    has_attachments = models.BooleanField(default=False)

    # Housekeeping
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'temp_email'
        verbose_name = 'Temporary Email'
        verbose_name_plural = 'Temporary Emails'
        ordering = ['-date_sent']
        indexes = [
            models.Index(fields=['-date_sent']),
            models.Index(fields=['uid']),
        ]

    def __str__(self):
        return f"{self.from_email}: {self.subject[:50]}"
class AccountingCategory(models.Model):
    """
    Defines categories of line items with default taxability.
    Examples: Service, Material, Product, Freight, Overhead
    """
    code = models.CharField(max_length=20, unique=True)  # e.g., "SVC", "MAT", "PRD"
    name = models.CharField(max_length=100)  # e.g., "Service", "Material", "Product"
    taxable = models.BooleanField(default=True)  # Default taxability for this type
    default_description = models.TextField(blank=True)  # Template for descriptions
    is_active = models.BooleanField(default=True)  # Soft delete support

    # QBO account mappings (populated after connecting to QBO)
    qbo_item_id = models.CharField(max_length=50, blank=True, default='')
    qbo_expense_account_id = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        db_table = 'accounting_categories'
        ordering = ['name']
        verbose_name_plural = 'accounting categories'

    def __str__(self):
        return self.name



class AbstractWorkContainer(models.Model):
    """Abstract base class for work containers (Job, EstWorksheet) containing common fields."""
    template = models.ForeignKey('estimates.WorkTemplate', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        abstract = True

    def populate_from_template(self, template):
        """Populate this container's tasks from a WorkTemplate.

        Subclasses implement by reading the template's TemplateTaskAssociations
        and creating the appropriate task type
        (PlanTask on EstWorksheet, Task on Job).
        """
        raise NotImplementedError


class BaseLineItem(models.Model):
    """
    Abstract base class for all line item types.
    Provides shared functionality for EstimateLineItem, InvoiceLineItem,
    PurchaseOrderLineItem, and BillLineItem.
    """
    line_item_id = models.AutoField(primary_key=True)
    # NOTE: `task` FK is defined on each concrete subclass because it targets
    # different models depending on the line item type (EstimateLineItem -> PlanTask,
    # everything else -> Task).
    price_list_item = models.ForeignKey('inventory.PriceListItem', on_delete=models.PROTECT, null=True, blank=True)  # Changed from CASCADE - protect historical documents
    line_number = models.PositiveIntegerField(blank=True, null=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    units = models.CharField(max_length=50, default='none')
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Tax-related fields
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
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
        """Validate that line item cannot have both task and price_list_item.

        Only applies to subclasses that still carry a task FK (e.g. PurchaseOrderLineItem,
        BillLineItem). EstimateLineItem dropped its task FK in favour of EstimateLineItemSource.
        """
        super().clean()
        try:
            task_fk = self._meta.get_field('task')
        except Exception:
            task_fk = None

        if task_fk is not None:
            has_task = self.task is not None
            has_price_item = self.price_list_item is not None

            if has_task and has_price_item:
                raise ValidationError("LineItem cannot have both task and price_list_item")

    def _populate_from_pli(self):
        """Copy description/units/accounting_category from linked PriceListItem if not already set.

        Price is NOT populated here because purchase vs selling price is a
        business decision — services set the correct price for each entity type.
        """
        if self.price_list_item:
            if not self.description:
                self.description = self.price_list_item.description
            if self.units == 'none' or not self.units:
                self.units = self.price_list_item.units
            if not self.accounting_category and self.price_list_item.accounting_category:
                self.accounting_category = self.price_list_item.accounting_category

    def save(self, *args, **kwargs):
        """Override save to ensure validation is always run and handle automatic line numbering."""
        from django.db import transaction

        self._populate_from_pli()

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
        return self.qty * self.price

    @property
    def source_name(self):
        """Get the name of the source (task name or price list item description)."""
        if self.task:
            return self.task.name
        elif self.price_list_item:
            return self.price_list_item.description
        return "No source"


class HistoryEntry(models.Model):
    """Tracks changes, actions, and notes on objects.

    Entry types:
        audit  — automatic field change tracking (via @history decorator)
        action — system-generated status transitions (e.g., from signals)
        note   — user-written notes

    Fields:
        changes — JSON diff of field values. May also contain underscore-prefixed
                  metadata keys: _created (bool, object was created),
                  _action (str, system-generated description of what happened).
                  These are not field diffs and should be filtered out when
                  displaying field changes.
        text    — Reserved for human-entered text only (notes, reasons for status
                  changes). NEVER use for system-generated descriptions; put those
                  in changes['_action'] instead.
    """
    ENTRY_TYPES = [
        ('audit', 'Audit'),
        ('action', 'Action'),
        ('note', 'Note'),
    ]

    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPES)
    object_type = models.CharField(max_length=50)
    object_id = models.IntegerField()
    user = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='history_entries',
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(null=True, blank=True)
    text = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'history'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.entry_type}: {self.object_type} #{self.object_id}"