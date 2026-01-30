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