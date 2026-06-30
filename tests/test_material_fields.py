from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, InventoryItem, Earmark
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme


class MaterialFieldsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='labor')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(job_number='JOB-TEST-1', contact=self.contact)
        self.scheme = RateScheme.objects.create(
            name='S-mf', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.cat,
        )
        self.task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme)

    def test_material_has_job_consumption_state_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
            accounting_category=self.cat,
        )
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(m.restocked_qty, Decimal('0.00'))

    def test_non_inventoried_material_defaults_to_pending(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='no-pli', quantity=Decimal('1.00'),
            accounting_category=self.cat,
        )
        self.assertIsNone(m.inventory_item)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_material_rejects_mismatched_task_job(self):
        job_b = Job.objects.create(job_number='JOB-TEST-2', contact=self.contact)
        with self.assertRaises(ValidationError):
            Material.objects.create(
                task=self.task, job=job_b,
                description='x', quantity=Decimal('1.00'),
                accounting_category=self.cat,
            )

    def test_material_rejects_negative_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
            accounting_category=self.cat,
        )
        m.restocked_qty = Decimal('-1.00')
        with self.assertRaises(ValidationError):
            m.save()


class MaterialBaseBehaviorTest(TestCase):
    """MaterialBase behaviors on the actual Material model.

    Ported from the deleted test_material.py (which exercised these via the
    now-removed plan layer). Covers total_cost/total_sell, accounting-category
    auto-fill from a linked InventoryItem, the explicit-value-not-overwritten
    guard, and inventory_item SET_NULL on InventoryItem delete.
    """

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Base', last_name='Behavior',
            email='basebehavior@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-MBB-1', contact=self.contact)
        self.category = AccountingCategory.objects.create(name='MBB-Mat', code='MBB-MAT')
        self.inventory_item = InventoryItem.objects.create(
            code='MBB.OAK',
            description='Oak edge banding',
            purchase_price=Decimal('12.00'),
            selling_price=Decimal('24.00'),
            accounting_category=self.category,
        )

    def test_total_cost_property(self):
        m = Material.objects.create(
            job=self.job, description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'), sell_price=Decimal('0.20'),
            accounting_category=self.category,
        )
        self.assertEqual(m.total_cost, Decimal('10.00'))

    def test_total_sell_property(self):
        m = Material.objects.create(
            job=self.job, description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'), sell_price=Decimal('0.20'),
            accounting_category=self.category,
        )
        self.assertEqual(m.total_sell, Decimal('20.00'))

    def test_pli_auto_fills_accounting_category(self):
        """Material linked to an InventoryItem auto-fills accounting_category."""
        m = Material.objects.create(
            job=self.job, inventory_item=self.inventory_item,
            quantity=Decimal('2.00'),
        )
        self.assertEqual(m.accounting_category, self.category)
        self.assertEqual(m.description, 'Oak edge banding')
        self.assertEqual(m.unit_cost, Decimal('12.00'))
        self.assertEqual(m.sell_price, Decimal('24.00'))

    def test_explicit_accounting_category_not_overwritten_by_pli(self):
        other = AccountingCategory.objects.create(name='MBB-Labor', code='MBB-LBR')
        m = Material.objects.create(
            job=self.job, inventory_item=self.inventory_item,
            quantity=Decimal('2.00'),
            accounting_category=other,
        )
        self.assertEqual(m.accounting_category, other)

    def test_explicit_values_not_overwritten_by_pli(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.inventory_item,
            description='Custom description',
            quantity=Decimal('2.00'),
            unit_cost=Decimal('55.00'), sell_price=Decimal('110.00'),
            accounting_category=self.category,
        )
        self.assertEqual(m.description, 'Custom description')
        self.assertEqual(m.unit_cost, Decimal('55.00'))
        self.assertEqual(m.sell_price, Decimal('110.00'))

    def test_set_null_on_inventory_item_delete(self):
        """inventory_item FK set to null when the InventoryItem is deleted."""
        m = Material.objects.create(
            job=self.job, inventory_item=self.inventory_item,
            quantity=Decimal('1.00'),
        )
        self.inventory_item.delete()
        m.refresh_from_db()
        self.assertIsNone(m.inventory_item)


class MaterialTaskSetNullTest(TestCase):
    """Gap 1: Material.task on_delete=SET_NULL — deleting a Task must not destroy its Materials."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Null', last_name='Test',
            email='nulltest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-TSN-1', contact=self.contact)
        cat = AccountingCategory.objects.create(name='tsn-cat', code='TSN1')
        scheme = RateScheme.objects.create(
            name='S-tsn', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=cat,
        )
        self.task = Task.objects.create(job=self.job, name='deletable', rate_scheme=scheme)

    def test_delete_task_keeps_material_with_null_task_and_original_job(self):
        cat = AccountingCategory.objects.create(name='tsn-mat', code='TSN-MAT')
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='widget', quantity=Decimal('3.00'),
            accounting_category=cat,
        )
        task_pk = self.task.pk
        material_pk = m.pk
        original_job_pk = self.job.pk
        self.task.delete()
        self.assertTrue(Material.objects.filter(pk=material_pk).exists(),
                        'Material row should survive task deletion')
        m.refresh_from_db()
        self.assertIsNone(m.task_id, 'task_id should be NULL after task deleted')
        self.assertEqual(m.job_id, original_job_pk, 'job_id should be unchanged')


class MaterialJobCascadeTest(TestCase):
    """Gap 2: Material.job on_delete=CASCADE — deleting a Job destroys Materials and Earmarks."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cascade', code='CASC1')
        self.contact = Contact.objects.create(
            first_name='Cascade', last_name='Test',
            email='casctest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-CASC-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='CASC-I', accounting_category=self.cat, is_catalog=True,
        )

    def test_delete_job_removes_material_and_earmark(self):
        m = Material.objects.create(
            job=self.job, description='bolt', quantity=Decimal('5.00'),
            inventory_item=self.pli,
            # accounting_category is auto-filled from pli
        )
        Earmark.objects.create(
            inventory_item=self.pli, job=self.job, quantity=Decimal('5.00'),
        )
        material_pk = m.pk
        self.job.delete()
        self.assertFalse(Material.objects.filter(pk=material_pk).exists(),
                         'Material should be cascade-deleted with its Job')
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli).exists(),
            'Earmark should be cascade-deleted with its Job')


class MaterialPropertiesTest(TestCase):
    """Gap 3: is_expense_bound property reflects the expense reverse relation."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='props', code='PROP1')
        self.contact = Contact.objects.create(
            first_name='Prop', last_name='Test',
            email='proptest@example.com',
        )
        self.job = Job.objects.create(job_number='JOB-PROP-1', contact=self.contact)

    def test_is_expense_bound_reflects_expense_reverse_relation(self):
        from apps.expenses.models import Expense
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user('prop_user', password='p')
        m = Material.objects.create(
            job=self.job, description='x', quantity=Decimal('1.00'),
            accounting_category=self.cat,
        )
        self.assertFalse(m.is_expense_bound, 'No expenses yet — should be False')
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14', accounting_category=self.cat,
            payment_method='personal',
            material=m,
        )
        m.refresh_from_db()
        self.assertTrue(m.is_expense_bound, 'After creating Expense — should be True')
