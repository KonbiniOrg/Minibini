from decimal import Decimal
from django.test import TestCase
from apps.estimates.models import WorkTemplate
from apps.inventory.models import TemplateMaterial


class TemplateMaterialTest(TestCase):
    def test_create_template_material(self):
        wt = WorkTemplate.objects.create(
            template_name='widget', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10.00'),
        )
        self.assertEqual(list(wt.materials.all()), [tm])
        self.assertEqual(tm.sort_order, 0)

    def test_template_material_all_material_fields_optional(self):
        wt = WorkTemplate.objects.create(
            template_name='blank', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(work_template=wt)
        self.assertEqual(tm.quantity, Decimal('0.00'))
