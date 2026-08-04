"""Tests for TaskBase.copy_fields() and MaterialBase.copy_fields() — the single
home for the field set used when cloning atoms between containers."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.jobs.models import Task
from apps.inventory.models import Material, InventoryItem


class CopyActiveModifiersTest(TestCase):
    def test_copy_active_modifiers_always_returns_list(self):
        from apps.jobs.models import copy_active_modifiers
        self.assertEqual(copy_active_modifiers(None), [])
        # legacy dict shape collapses to empty list (price now lives on the service)
        self.assertEqual(copy_active_modifiers({'flat_fee_price': '5'}), [])
        # legacy list-of-keys shape (pre-Phase-1 snapshot) also collapses —
        # can't be resolved into {key,label,percent} dicts without a scheme.
        self.assertEqual(copy_active_modifiers(['a', 'b']), [])

    def test_copy_active_modifiers_deep_copies_dict_list(self):
        from apps.jobs.models import copy_active_modifiers
        mods = [{'key': 'rush', 'label': 'Rush', 'percent': 50}]
        result = copy_active_modifiers(mods)
        self.assertEqual(result, mods)
        self.assertIsNot(result, mods)
        self.assertIsNot(result[0], mods[0])


class TaskBaseCopyFieldsTest(TestCase):
    def test_copy_fields_returns_full_taskbase_field_set(self):
        ac = AccountingCategory.objects.create(code='CF-task', name='cf-task')
        mods = [{'key': 'rush', 'label': 'Rush', 'percent': 50}]
        t = Task(
            name='Cut', description='cut to length', sort_order=5,
            est_worker_time=timedelta(hours=2), est_qty=Decimal('3.00'),
            qty_source=Task.QTY_ENTERED, rate=Decimal('10.00'), unit_label='ea',
            accounting_category=ac, active_modifiers=mods,
        )
        self.assertEqual(t.copy_fields(), {
            'name': 'Cut',
            'description': 'cut to length',
            'sort_order': 5,
            'est_worker_time': timedelta(hours=2),
            'est_qty': Decimal('3.00'),
            'qty_source': Task.QTY_ENTERED,
            'rate': Decimal('10.00'),
            'unit_label': 'ea',
            'accounting_category_id': ac.pk,
            'service_item_id': None,
            'active_modifiers': mods,
            # final-review finding I1: qty_scales_with_parent is now
            # carried too — inert on a top-level task (this Task has no
            # parent_task) but load-bearing on a copied subtask.
            'qty_scales_with_parent': True,
        })

    def test_copy_fields_deep_copies_active_modifiers(self):
        ac = AccountingCategory.objects.create(code='CF-mods', name='cf-mods')
        mods = [{'key': 'rush', 'label': 'Rush', 'percent': 50}]
        t = Task(name='T', accounting_category=ac, active_modifiers=mods,
                 est_qty=Decimal('1'))
        self.assertIsNot(t.copy_fields()['active_modifiers'], mods)

    def test_copy_fields_works_on_task_subclass_too(self):
        ac = AccountingCategory.objects.create(code='CF-exec', name='cf-exec')
        t = Task(name='Weld', accounting_category=ac, rate=Decimal('20.00'),
                 est_qty=Decimal('2'))
        fields = t.copy_fields()
        self.assertEqual(fields['name'], 'Weld')
        self.assertEqual(fields['accounting_category_id'], ac.pk)


class MaterialBaseCopyFieldsTest(TestCase):
    def test_copy_fields_returns_full_materialbase_field_set(self):
        ac = AccountingCategory.objects.create(code='CF-MAT', name='cf-mat')
        pli = InventoryItem.objects.create(
            description='Steel', units='kg', accounting_category=ac,
        )
        m = Material(
            description='Steel bar', quantity=Decimal('10.00'), units='kg',
            unit_cost=Decimal('1.50'), sell_price=Decimal('3.00'),
            inventory_item=pli, accounting_category=ac,
        )
        self.assertEqual(m.copy_fields(), {
            'description': 'Steel bar',
            'quantity': Decimal('10.00'),
            'units': 'kg',
            'unit_cost': Decimal('1.50'),
            'sell_price': Decimal('3.00'),
            'inventory_item': pli,
            'accounting_category': ac,
            'cost_source': None,
        })

    def test_copy_fields_carries_cost_source_provenance(self):
        ac = AccountingCategory.objects.create(code='CF-MAT3', name='cf-mat3')
        m = Material(description='PO stock', units='ea', accounting_category=ac,
                     cost_source=Material.COST_SOURCE_PO)
        self.assertEqual(m.copy_fields()['cost_source'], Material.COST_SOURCE_PO)

    def test_copy_fields_works_on_material_subclass_too(self):
        ac = AccountingCategory.objects.create(code='CF-MAT2', name='cf-mat2')
        m = Material(description='Bolt', units='ea', accounting_category=ac)
        fields = m.copy_fields()
        self.assertEqual(fields['description'], 'Bolt')
        self.assertEqual(fields['units'], 'ea')
        self.assertEqual(fields['accounting_category'], ac)
