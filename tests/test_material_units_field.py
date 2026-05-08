# tests/test_material_units_field.py
from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import Material, PlanMaterial, TemplateMaterial


class MaterialUnitsFieldTests(TestCase):
    """Phase 1: units field added to MaterialBase."""

    def test_material_has_units_field(self):
        f = Material._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

    def test_plan_material_has_units_field(self):
        f = PlanMaterial._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

    def test_template_material_has_units_field(self):
        f = TemplateMaterial._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')
