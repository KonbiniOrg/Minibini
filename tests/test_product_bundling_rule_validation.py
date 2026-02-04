from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import BundlingRule, WorkOrderTemplate


class BundlingRuleValidationTest(TestCase):
    """Test validation rules for BundlingRule"""
    
    def setUp(self):
        """Set up test data"""
        # Create WorkOrderTemplate with base price
        self.template_with_price = WorkOrderTemplate.objects.create(
            template_name="Premium Table Template",
            description="High-end dining table template",
            template_type="product",
            product_type="furniture",
            base_price=Decimal('2500.00')
        )
        
        # Create WorkOrderTemplate without base price
        self.template_without_price = WorkOrderTemplate.objects.create(
            template_name="Basic Table Template", 
            description="Basic table template",
            template_type="product",
            product_type="furniture",
            base_price=None
        )
    
    def test_template_base_pricing_requires_template(self):
        """BundlingRule with template_base pricing must have a work_order_template"""
        with self.assertRaises(ValidationError) as context:
            rule = BundlingRule(
                rule_name="Invalid Template Base Rule",
                product_type="furniture",
                work_order_template=None,  # Missing template
                pricing_method="template_base"
            )
            rule.full_clean()
        
        self.assertIn("template_base pricing requires", str(context.exception))
    
    def test_template_base_pricing_requires_base_price(self):
        """BundlingRule with template_base pricing must reference template with base_price"""
        with self.assertRaises(ValidationError) as context:
            rule = BundlingRule(
                rule_name="Invalid Base Price Rule",
                product_type="furniture", 
                work_order_template=self.template_without_price,  # Template has no base_price
                pricing_method="template_base"
            )
            rule.full_clean()
        
        self.assertIn("base_price", str(context.exception))
    
    def test_valid_template_base_pricing(self):
        """BundlingRule with template_base pricing should be valid when properly configured"""
        rule = BundlingRule(
            rule_name="Valid Template Base Rule",
            product_type="furniture",
            work_order_template=self.template_with_price,  # Template has base_price
            pricing_method="template_base"
        )
        
        # Should not raise ValidationError
        try:
            rule.full_clean()
            rule.save()
            self.assertTrue(True, "Valid template_base rule should save successfully")
        except ValidationError:
            self.fail("Valid template_base rule should not raise ValidationError")
    
    def test_sum_components_pricing_without_template(self):
        """BundlingRule with sum_components pricing should work without template"""
        rule = BundlingRule(
            rule_name="Sum Components Rule",
            product_type="furniture",
            work_order_template=None,  # No template needed for sum_components
            pricing_method="sum_components"
        )
        
        # Should not raise ValidationError
        try:
            rule.full_clean()
            rule.save()
            self.assertTrue(True, "sum_components rule without template should save successfully")
        except ValidationError:
            self.fail("sum_components rule without template should not raise ValidationError")
    
    def test_sum_components_pricing_with_template(self):
        """BundlingRule with sum_components pricing should work with template"""
        rule = BundlingRule(
            rule_name="Sum Components with Template Rule",
            product_type="furniture",
            work_order_template=self.template_with_price,  # Template allowed but not required
            pricing_method="sum_components"
        )
        
        # Should not raise ValidationError
        try:
            rule.full_clean()
            rule.save()
            self.assertTrue(True, "sum_components rule with template should save successfully")
        except ValidationError:
            self.fail("sum_components rule with template should not raise ValidationError")
    
    def test_custom_calculation_pricing(self):
        """BundlingRule with custom_calculation pricing should work"""
        rule = BundlingRule(
            rule_name="Custom Calculation Rule",
            product_type="furniture",
            work_order_template=None,
            pricing_method="custom_calculation"
        )
        
        # Should not raise ValidationError
        try:
            rule.full_clean()
            rule.save()
            self.assertTrue(True, "custom_calculation rule should save successfully")
        except ValidationError:
            self.fail("custom_calculation rule should not raise ValidationError")