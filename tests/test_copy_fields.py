"""Tests for TaskBase.copy_fields() and MaterialBase.copy_fields() — the single
home for the field set used when cloning atoms between containers."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.jobs.models import PlanTask, Task, RateScheme
from apps.inventory.models import PlanMaterial, Material, InventoryItem


def _make_scheme(suffix):
    ac = AccountingCategory.objects.create(code=f'CF-{suffix}', name=f'cf-{suffix}')
    return RateScheme.objects.create(
        name=f'S-cf-{suffix}', algorithm=RateScheme.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class TaskBaseCopyFieldsTest(TestCase):
    def test_copy_fields_returns_full_taskbase_field_set(self):
        scheme = _make_scheme('task')
        mods = ['mod_a', 'mod_b']
        pt = PlanTask(
            name='Cut', description='cut to length', sort_order=5,
            est_worker_time=timedelta(hours=2), est_qty=Decimal('3.00'),
            rate_scheme=scheme, active_modifiers=mods,
        )
        self.assertEqual(pt.copy_fields(), {
            'name': 'Cut',
            'description': 'cut to length',
            'sort_order': 5,
            'est_worker_time': timedelta(hours=2),
            'est_qty': Decimal('3.00'),
            'rate_scheme_id': scheme.pk,
            'active_modifiers': mods,
        })

    def test_copy_fields_deep_copies_active_modifiers(self):
        scheme = _make_scheme('mods')
        mods = ['x']
        pt = PlanTask(name='T', rate_scheme=scheme, active_modifiers=mods,
                      est_qty=Decimal('1'))
        self.assertIsNot(pt.copy_fields()['active_modifiers'], mods)

    def test_copy_fields_works_on_task_subclass_too(self):
        scheme = _make_scheme('exec')
        t = Task(name='Weld', rate_scheme=scheme, est_qty=Decimal('2'))
        fields = t.copy_fields()
        self.assertEqual(fields['name'], 'Weld')
        self.assertEqual(fields['rate_scheme_id'], scheme.pk)


class MaterialBaseCopyFieldsTest(TestCase):
    def test_copy_fields_returns_full_materialbase_field_set(self):
        ac = AccountingCategory.objects.create(code='CF-MAT', name='cf-mat')
        pli = InventoryItem.objects.create(
            description='Steel', units='kg', accounting_category=ac,
        )
        pm = PlanMaterial(
            description='Steel bar', quantity=Decimal('10.00'), units='kg',
            unit_cost=Decimal('1.50'), sell_price=Decimal('3.00'),
            inventory_item=pli, accounting_category=ac,
        )
        self.assertEqual(pm.copy_fields(), {
            'description': 'Steel bar',
            'quantity': Decimal('10.00'),
            'units': 'kg',
            'unit_cost': Decimal('1.50'),
            'sell_price': Decimal('3.00'),
            'inventory_item': pli,
            'accounting_category': ac,
        })

    def test_copy_fields_works_on_material_subclass_too(self):
        ac = AccountingCategory.objects.create(code='CF-MAT2', name='cf-mat2')
        m = Material(description='Bolt', units='ea', accounting_category=ac)
        fields = m.copy_fields()
        self.assertEqual(fields['description'], 'Bolt')
        self.assertEqual(fields['units'], 'ea')
        self.assertEqual(fields['accounting_category'], ac)
