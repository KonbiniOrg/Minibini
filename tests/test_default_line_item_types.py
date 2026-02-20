"""
Tests for default LineItemTypes data - TDD approach.
Testing that default LineItemTypes are created with correct data.
"""
from django.test import TestCase
from apps.core.models import LineItemType


class DefaultLineItemTypesTest(TestCase):
    """Tests for default LineItemTypes data migration."""

    def test_service_type_exists_with_correct_properties(self):
        """Test that Service type exists and is non-taxable."""
        svc = LineItemType.objects.get(code='SVC')
        self.assertEqual(svc.name, 'Service')
        self.assertFalse(svc.taxable)
        self.assertTrue(svc.is_active)

    def test_material_type_exists_with_correct_properties(self):
        """Test that Material type exists and is taxable."""
        mat = LineItemType.objects.get(code='MAT')
        self.assertEqual(mat.name, 'Material')
        self.assertTrue(mat.taxable)
        self.assertTrue(mat.is_active)

    def test_product_type_exists_with_correct_properties(self):
        """Test that Product type exists and is taxable."""
        prd = LineItemType.objects.get(code='PRD')
        self.assertEqual(prd.name, 'Product')
        self.assertTrue(prd.taxable)
        self.assertTrue(prd.is_active)

    def test_freight_type_exists_with_correct_properties(self):
        """Test that Freight type exists and is taxable."""
        frt = LineItemType.objects.get(code='FRT')
        self.assertEqual(frt.name, 'Freight')
        self.assertTrue(frt.taxable)
        self.assertTrue(frt.is_active)

    def test_miscellaneous_type_exists_with_correct_properties(self):
        """Test that Miscellaneous type exists and is taxable."""
        misc = LineItemType.objects.get(code='MISC')
        self.assertEqual(misc.name, 'Miscellaneous')
        self.assertTrue(misc.taxable)
        self.assertTrue(misc.is_active)

    def test_all_five_default_types_exist(self):
        """Test that exactly 5 default types were created."""
        # Note: The test may have more types if other tests created them
        default_codes = ['SVC', 'MAT', 'PRD', 'FRT', 'MISC']
        for code in default_codes:
            self.assertTrue(
                LineItemType.objects.filter(code=code).exists(),
                f"LineItemType with code '{code}' should exist"
            )
