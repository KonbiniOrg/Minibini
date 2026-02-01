"""
Tests for LineItemType model - TDD approach.
Testing the categorization of line items by type with default taxability.
"""
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from apps.core.models import LineItemType


class LineItemTypeModelTest(TestCase):
    """Tests for the LineItemType model."""

    def test_line_item_type_creation(self):
        """Test basic LineItemType creation with all fields."""
        line_item_type = LineItemType.objects.create(
            code='TST1',  # Use unique code to avoid conflict with migration data
            name='Test Service',
            taxable=False,
            default_units='hours',
            default_description='Professional service',
            is_active=True
        )

        self.assertEqual(line_item_type.code, 'TST1')
        self.assertEqual(line_item_type.name, 'Test Service')
        self.assertFalse(line_item_type.taxable)
        self.assertEqual(line_item_type.default_units, 'hours')
        self.assertEqual(line_item_type.default_description, 'Professional service')
        self.assertTrue(line_item_type.is_active)

    def test_line_item_type_str_method(self):
        """Test __str__ returns the name."""
        line_item_type = LineItemType.objects.create(
            code='TST2',  # Use unique code
            name='Test Material'
        )
        self.assertEqual(str(line_item_type), 'Test Material')

    def test_code_unique_constraint(self):
        """Test that code must be unique."""
        LineItemType.objects.create(code='UNIQ1', name='Unique Product')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LineItemType.objects.create(code='UNIQ1', name='Another Product')

    def test_taxable_defaults_to_true(self):
        """Test that taxable defaults to True."""
        line_item_type = LineItemType.objects.create(
            code='TAX1',  # Use unique code
            name='Taxable Test'
        )
        self.assertTrue(line_item_type.taxable)

    def test_is_active_defaults_to_true(self):
        """Test that is_active defaults to True."""
        line_item_type = LineItemType.objects.create(
            code='ACT1',  # Use unique code
            name='Active Test'
        )
        self.assertTrue(line_item_type.is_active)

    def test_default_units_can_be_blank(self):
        """Test that default_units can be blank."""
        line_item_type = LineItemType.objects.create(
            code='BLK1',  # Use unique code
            name='Blank Units Test',
            default_units=''
        )
        self.assertEqual(line_item_type.default_units, '')

    def test_default_description_can_be_blank(self):
        """Test that default_description can be blank."""
        line_item_type = LineItemType.objects.create(
            code='DESC1',  # Use unique code
            name='Description Test',
            default_description=''
        )
        self.assertEqual(line_item_type.default_description, '')

    def test_ordering_by_name(self):
        """Test that LineItemTypes are ordered by name."""
        # Clear any existing types first to test ordering in isolation
        LineItemType.objects.all().delete()

        LineItemType.objects.create(code='Z', name='Zebra')
        LineItemType.objects.create(code='A', name='Apple')
        LineItemType.objects.create(code='M', name='Mango')

        types = list(LineItemType.objects.all())
        names = [t.name for t in types]
        self.assertEqual(names, ['Apple', 'Mango', 'Zebra'])

    def test_code_max_length(self):
        """Test that code respects max_length of 20."""
        # 20 characters should work
        line_item_type = LineItemType.objects.create(
            code='MAXLEN12345678901234',  # 20 chars, unique
            name='Max Length Test'
        )
        self.assertEqual(len(line_item_type.code), 20)

    def test_name_max_length(self):
        """Test that name respects max_length of 100."""
        # 100 characters should work
        line_item_type = LineItemType.objects.create(
            code='NAMETST',  # Use unique code
            name='A' * 100
        )
        self.assertEqual(len(line_item_type.name), 100)

    def test_soft_delete_via_is_active(self):
        """Test soft delete by setting is_active to False."""
        line_item_type = LineItemType.objects.create(
            code='SOFTDEL',  # Use unique code
            name='To Delete',
            is_active=True
        )
        self.assertTrue(line_item_type.is_active)

        line_item_type.is_active = False
        line_item_type.save()

        line_item_type.refresh_from_db()
        self.assertFalse(line_item_type.is_active)
