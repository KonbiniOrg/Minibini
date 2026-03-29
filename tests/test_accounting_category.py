"""
Tests for AccountingCategory model - TDD approach.
Testing the categorization of line items by type with default taxability.
"""
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from apps.core.models import AccountingCategory


class AccountingCategoryModelTest(TestCase):
    """Tests for the AccountingCategory model."""

    def test_accounting_category_creation(self):
        """Test basic AccountingCategory creation with all fields."""
        accounting_category = AccountingCategory.objects.create(
            code='TST1',  # Use unique code to avoid conflict with migration data
            name='Test Service',
            taxable=False,
            default_description='Professional service',
            is_active=True
        )

        self.assertEqual(accounting_category.code, 'TST1')
        self.assertEqual(accounting_category.name, 'Test Service')
        self.assertFalse(accounting_category.taxable)
        self.assertEqual(accounting_category.default_description, 'Professional service')
        self.assertTrue(accounting_category.is_active)

    def test_accounting_category_str_method(self):
        """Test __str__ returns the name."""
        accounting_category = AccountingCategory.objects.create(
            code='TST2',  # Use unique code
            name='Test Material'
        )
        self.assertEqual(str(accounting_category), 'Test Material')

    def test_code_unique_constraint(self):
        """Test that code must be unique."""
        AccountingCategory.objects.create(code='UNIQ1', name='Unique Product')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountingCategory.objects.create(code='UNIQ1', name='Another Product')

    def test_taxable_defaults_to_true(self):
        """Test that taxable defaults to True."""
        accounting_category = AccountingCategory.objects.create(
            code='TAX1',  # Use unique code
            name='Taxable Test'
        )
        self.assertTrue(accounting_category.taxable)

    def test_is_active_defaults_to_true(self):
        """Test that is_active defaults to True."""
        accounting_category = AccountingCategory.objects.create(
            code='ACT1',  # Use unique code
            name='Active Test'
        )
        self.assertTrue(accounting_category.is_active)

    def test_default_description_can_be_blank(self):
        """Test that default_description can be blank."""
        accounting_category = AccountingCategory.objects.create(
            code='DESC1',  # Use unique code
            name='Description Test',
            default_description=''
        )
        self.assertEqual(accounting_category.default_description, '')

    def test_ordering_by_name(self):
        """Test that AccountingCategorys are ordered by name."""
        # Clear any existing types first to test ordering in isolation
        AccountingCategory.objects.all().delete()

        AccountingCategory.objects.create(code='Z', name='Zebra')
        AccountingCategory.objects.create(code='A', name='Apple')
        AccountingCategory.objects.create(code='M', name='Mango')

        types = list(AccountingCategory.objects.all())
        names = [t.name for t in types]
        self.assertEqual(names, ['Apple', 'Mango', 'Zebra'])

    def test_code_max_length(self):
        """Test that code respects max_length of 20."""
        # 20 characters should work
        accounting_category = AccountingCategory.objects.create(
            code='MAXLEN12345678901234',  # 20 chars, unique
            name='Max Length Test'
        )
        self.assertEqual(len(accounting_category.code), 20)

    def test_name_max_length(self):
        """Test that name respects max_length of 100."""
        # 100 characters should work
        accounting_category = AccountingCategory.objects.create(
            code='NAMETST',  # Use unique code
            name='A' * 100
        )
        self.assertEqual(len(accounting_category.name), 100)

    def test_soft_delete_via_is_active(self):
        """Test soft delete by setting is_active to False."""
        accounting_category = AccountingCategory.objects.create(
            code='SOFTDEL',  # Use unique code
            name='To Delete',
            is_active=True
        )
        self.assertTrue(accounting_category.is_active)

        accounting_category.is_active = False
        accounting_category.save()

        accounting_category.refresh_from_db()
        self.assertFalse(accounting_category.is_active)
