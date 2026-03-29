"""Tests for core app service methods (service-mediated saves)."""
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration, EmailRecord
from apps.core.services import (
    ConfigurationService, EmailService,
    NotFoundError,
)
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class AccountingCategoryConfigTest(TestCase):
    """Tests for ConfigurationService line item type methods."""

    def test_create_type(self):
        """Create a new AccountingCategory via service."""
        lit = ConfigurationService.create_accounting_category(
            code='SVC', name='Service', taxable=True
        )
        self.assertEqual(lit.code, 'SVC')
        self.assertEqual(lit.name, 'Service')
        self.assertTrue(lit.taxable)
        self.assertTrue(lit.is_active)
        self.assertIsNotNone(lit.pk)

    def test_create_type_with_defaults(self):
        """Create with minimal args — defaults should apply."""
        lit = ConfigurationService.create_accounting_category(code='FRT', name='Freight')
        self.assertTrue(lit.taxable)  # model default
        self.assertTrue(lit.is_active)  # model default
        self.assertEqual(lit.default_description, '')

    def test_create_type_with_optional_fields(self):
        """Create with all optional fields."""
        lit = ConfigurationService.create_accounting_category(
            code='MSC', name='Misc', taxable=False,
            default_description='Miscellaneous charge', is_active=False
        )
        self.assertFalse(lit.taxable)
        self.assertEqual(lit.default_description, 'Miscellaneous charge')
        self.assertFalse(lit.is_active)

    def test_create_type_duplicate_code_raises(self):
        """Duplicate code should raise ValidationError."""
        ConfigurationService.create_accounting_category(code='SVC', name='Service')
        with self.assertRaises(Exception):
            ConfigurationService.create_accounting_category(code='SVC', name='Service 2')

    def test_update_type(self):
        """Update an existing AccountingCategory by PK."""
        lit = AccountingCategory.objects.create(code='SVC', name='Service', taxable=True)
        updated = ConfigurationService.update_accounting_category(lit.pk, name='Labor', taxable=False)
        self.assertEqual(updated.name, 'Labor')
        self.assertFalse(updated.taxable)
        self.assertEqual(updated.code, 'SVC')

    def test_update_type_persists(self):
        """Update should be persisted to database."""
        lit = AccountingCategory.objects.create(code='SVC', name='Service', taxable=True)
        ConfigurationService.update_accounting_category(lit.pk, name='Labor')
        refreshed = AccountingCategory.objects.get(pk=lit.pk)
        self.assertEqual(refreshed.name, 'Labor')

    def test_update_type_not_found(self):
        """Updating a nonexistent PK raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            ConfigurationService.update_accounting_category(99999, name='Nope')


class ConfigurationServiceTest(TestCase):
    """Tests for ConfigurationService."""

    def test_update_tax_config_creates_new(self):
        """Should create config entries when they don't exist."""
        ConfigurationService.update_tax_config(
            default_tax_rate='0.0825',
            org_tax_multiplier='1.0'
        )
        self.assertEqual(
            Configuration.objects.get(key='default_tax_rate').value,
            '0.0825'
        )
        self.assertEqual(
            Configuration.objects.get(key='org_tax_multiplier').value,
            '1.0'
        )

    def test_update_tax_config_updates_existing(self):
        """Should update existing config entries."""
        Configuration.objects.create(key='default_tax_rate', value='0.05')
        ConfigurationService.update_tax_config(default_tax_rate='0.0825')
        self.assertEqual(
            Configuration.objects.get(key='default_tax_rate').value,
            '0.0825'
        )

    def test_update_tax_config_skips_none(self):
        """Should not create entries for None values."""
        ConfigurationService.update_tax_config(
            default_tax_rate='0.05',
            org_tax_multiplier=None
        )
        self.assertTrue(
            Configuration.objects.filter(key='default_tax_rate').exists()
        )
        self.assertFalse(
            Configuration.objects.filter(key='org_tax_multiplier').exists()
        )


class EmailAssociationServiceTest(TestCase):
    """Tests for EmailService associate/disassociate methods."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', business_phone='555-1234',
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            name='Test Job', job_number='J2026-0001',
            contact=self.contact, status='draft'
        )
        self.email_record = EmailRecord.objects.create(
            message_id='<test@example.com>',
        )

    def test_associate_with_job(self):
        """Associate an email record with a job by IDs."""
        result = EmailService.associate_with_job(
            self.email_record.pk, self.job.pk
        )
        self.assertEqual(result.job, self.job)
        refreshed = EmailRecord.objects.get(pk=self.email_record.pk)
        self.assertEqual(refreshed.job, self.job)

    def test_associate_with_job_bad_email(self):
        """Nonexistent email_record_id raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            EmailService.associate_with_job(99999, self.job.pk)

    def test_associate_with_job_bad_job(self):
        """Nonexistent job_id raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            EmailService.associate_with_job(self.email_record.pk, 99999)

    def test_disassociate_from_job(self):
        """Remove job association by email_record ID."""
        self.email_record.job = self.job
        self.email_record.save()

        result = EmailService.disassociate_from_job(self.email_record.pk)
        self.assertIsNone(result.job)
        refreshed = EmailRecord.objects.get(pk=self.email_record.pk)
        self.assertIsNone(refreshed.job)

    def test_disassociate_not_found(self):
        """Nonexistent email_record_id raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            EmailService.disassociate_from_job(99999)
