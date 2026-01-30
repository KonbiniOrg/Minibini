from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator


class Contact(models.Model):
    contact_id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=100)
    middle_initial = models.CharField(max_length=10, blank=True)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(validators=[EmailValidator()])
    addr1 = models.CharField(max_length=255, blank=True)
    addr2 = models.CharField(max_length=255, blank=True)
    addr3 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(max_length=3, blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    work_number = models.CharField(max_length=20, blank=True)
    home_number = models.CharField(max_length=20, blank=True)
    business = models.ForeignKey('Business', on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')

    def __str__(self):
        return self.name

    @property
    def name(self):
        """Combine name parts with proper spacing"""
        parts = [self.first_name]
        if self.middle_initial:
            parts.append(self.middle_initial)
        if self.last_name:
            parts.append(self.last_name)
        return ' '.join(parts)

    def clean(self):
        """Validate that email and at least one phone number is provided"""
        # Validate email is not empty
        if not self.email or not self.email.strip():
            raise ValidationError('Email address is required.')

        # Validate at least one phone number is provided
        if not any([self.work_number, self.mobile_number, self.home_number]):
            raise ValidationError('At least one phone number (work, mobile, or home) is required.')

    def save(self, *args, **kwargs):
        """Override save to update business default contact"""
        # Track old business reference before saving
        old_business = None
        if self.pk:
            try:
                old_contact = Contact.objects.get(pk=self.pk)
                old_business = old_contact.business
            except Contact.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        # Validate and fix default contact for affected businesses
        if self.business:
            self.business.validate_and_fix_default_contact()
        if old_business and old_business != self.business:
            old_business.validate_and_fix_default_contact()

    def delete(self, *args, **kwargs):
        """Override delete to update business default contact.

        Raises PermissionDenied if this is the sole contact for a business,
        since Business.default_contact is required.
        """
        from django.core.exceptions import PermissionDenied

        business = self.business

        # Check if this contact is the default_contact for its business
        if business and business.default_contact == self:
            other_contacts = business.contacts.exclude(pk=self.pk)
            if not other_contacts.exists():
                raise PermissionDenied(
                    f'Cannot delete the only contact for business "{business}". '
                    'Delete the business or add another contact as the default first.'
                )
            # Reassign default_contact to another contact before deleting
            business.default_contact = other_contacts.first()
            business.save(update_fields=['default_contact'])

        super().delete(*args, **kwargs)

        # Validate and fix default contact for the business (handles edge cases)
        if business:
            business.validate_and_fix_default_contact()

    def phone(self):
        # Return highest priority phone number: work > mobile > home
        if self.work_number:
            return self.work_number
        elif self.mobile_number:
            return self.mobile_number
        elif self.home_number:
            return self.home_number
        return ""

    def address(self):
        # Return complete address if all components available
        if (self.addr1 and self.city and self.postal_code):
            municipality_part = f", {self.municipality}" if self.municipality else ""
            return f"{self.addr1}, {self.city}{municipality_part} {self.postal_code}"
        # Return just addr1 if that's all we have
        elif self.addr1:
            return self.addr1
        return ""


class Business(models.Model):
    business_id = models.AutoField(primary_key=True)
    our_reference_code = models.CharField(max_length=50, blank=True, unique=True)
    business_name = models.CharField(max_length=255)
    business_address = models.TextField(blank=True)
    business_phone = models.CharField(max_length=20, blank=True)
    tax_exemption_number = models.CharField(max_length=50, blank=True)
    website = models.URLField(max_length=200, blank=True)
    terms = models.ForeignKey('PaymentTerms', on_delete=models.SET_NULL, null=True, blank=True)
    default_contact = models.ForeignKey('Contact', on_delete=models.PROTECT, null=False, blank=True, related_name='default_for_business')

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        from django.db import IntegrityError, transaction

        # If reference code is provided, just save normally
        if self.our_reference_code:
            super().save(*args, **kwargs)
            return

        # Auto-generate reference code with retry logic for race conditions
        max_attempts = 10
        for attempt in range(max_attempts):
            # Get the latest business to determine the next number
            last_business = Business.objects.order_by('-business_id').first()
            if last_business and last_business.business_id:
                next_id = last_business.business_id + 1 + attempt
            else:
                next_id = 1 + attempt

            # Generate reference code in format BUS-0001, BUS-0002, etc.
            self.our_reference_code = f"BUS-{next_id:04d}"

            # Check if this reference code already exists
            while Business.objects.filter(our_reference_code=self.our_reference_code).exists():
                next_id += 1
                self.our_reference_code = f"BUS-{next_id:04d}"

            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return  # Success
            except IntegrityError as e:
                if 'our_reference_code' in str(e) and attempt < max_attempts - 1:
                    # Race condition - another request got the same code, retry
                    continue
                raise  # Re-raise if not a reference code issue or max attempts reached

        raise ValueError("Could not generate unique reference code after maximum attempts")

    def validate_and_fix_default_contact(self):
        """
        Validate that the default contact exists in the business's contacts.
        If not, set it to the contact with the lowest primary key.

        This ensures data integrity when:
        - A default contact is moved to another business
        - A default contact becomes invalid
        - Data integrity issues occur
        """
        contacts = self.contacts.all()

        # If there are no contacts, we cannot fix this (business requires a default contact)
        if not contacts.exists():
            return

        # Check if current default contact is in the business's contacts
        if self.default_contact and self.default_contact in contacts:
            # Default contact is valid, do nothing
            return

        # Default contact is invalid or missing, set to contact with lowest primary key
        lowest_pk_contact = contacts.order_by('contact_id').first()
        self.default_contact = lowest_pk_contact
        self.save(update_fields=['default_contact'])

    def update_default_contact(self):
        """Update default contact based on business rules"""
        contacts = self.contacts.all()
        contact_count = contacts.count()

        # First check if current default is invalid (not associated with this business)
        if self.default_contact and self.default_contact.business != self:
            # Default contact is no longer associated with this business, clear it
            self.default_contact = None
            self.save(update_fields=['default_contact'])
            return

        if contact_count == 0:
            # No contacts, clear default
            if self.default_contact is not None:
                self.default_contact = None
                self.save(update_fields=['default_contact'])
        elif contact_count == 1:
            # Only one contact, set as default automatically
            single_contact = contacts.first()
            if self.default_contact != single_contact:
                self.default_contact = single_contact
                self.save(update_fields=['default_contact'])
        # If multiple contacts and no default, user must manually select
        # If multiple contacts and default is removed, user must manually select new default


class PaymentTerms(models.Model):
    term_id = models.AutoField(primary_key=True)
    # Additional fields not visible in diagram

    class Meta:
        verbose_name = "Payment Terms"
        verbose_name_plural = "Payment Terms"