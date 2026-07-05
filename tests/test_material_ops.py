from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, Earmark, InventoryItem
from apps.inventory.services import InventoryService, MaterialService
from apps.core.models import AccountingCategory


class ConsumeTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-C-1', contact=self.contact,
                                      status=Job.STATUS_APPROVED)
        self.pli = InventoryItem.objects.create(
            code='I', accounting_category=cat,
            qty_on_hand=Decimal('10'),
        )

    def test_consume_inventoried_updates_qoh_sold_earmark_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4'),
            inventory_item=self.pli,
        )
        MaterialService.consume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(self.pli.qty_on_hand, Decimal('6'))
        self.assertEqual(self.pli.qty_sold, Decimal('4'))
        self.assertFalse(
            Earmark.objects.filter(inventory_item=self.pli, job=self.job).exists()
        )

    def test_consume_requires_pending(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('2'),
            inventory_item=self.pli,
        )
        MaterialService.consume(m)
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)

    def test_consume_uses_quantity(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('3'),
            inventory_item=self.pli,
        )
        qoh_before = self.pli.qty_on_hand
        sold_before = self.pli.qty_sold
        e_before = Earmark.objects.get(
            inventory_item=self.pli, job=self.job
        ).quantity
        MaterialService.consume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, qoh_before - Decimal('3'))
        self.assertEqual(self.pli.qty_sold, sold_before + Decimal('3'))
        self.assertFalse(
            Earmark.objects.filter(
                inventory_item=self.pli, job=self.job
            ).exists()
        )
        # earmark started at e_before=3 and dropped by 3 (to 0, then removed)
        self.assertEqual(e_before, Decimal('3'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_consume_after_partial_expense_bound_restock_uses_quantity(self):
        from apps.expenses.models import Expense
        from apps.core.models import User
        user, _ = User.objects.get_or_create(username='consume_expense_user')
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('5'),
            inventory_item=self.pli,
        )
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=m.accounting_category
                or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            purchased_by=user,
            material=m,
        )
        MaterialService.restock(m, Decimal('2'))
        m.refresh_from_db()
        # sanity: quantity=3, released_qty=2
        self.assertEqual(m.quantity, Decimal('3'))
        self.assertEqual(m.released_qty, Decimal('2'))
        qoh_before = self.pli.qty_on_hand
        sold_before = self.pli.qty_sold
        e_before = Earmark.objects.get(
            inventory_item=self.pli, job=self.job
        ).quantity
        MaterialService.consume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, qoh_before - Decimal('3'))
        self.assertEqual(self.pli.qty_sold, sold_before + Decimal('3'))
        self.assertEqual(e_before, Decimal('3'))
        self.assertFalse(
            Earmark.objects.filter(
                inventory_item=self.pli, job=self.job
            ).exists()
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)


class RestockTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='r@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-R-1', contact=self.contact,
                                      status=Job.STATUS_APPROVED)
        self.pli = InventoryItem.objects.create(
            code='I', accounting_category=cat,
            qty_on_hand=Decimal('10'),
        )

    def _make_expense_bound(self, material):
        from apps.expenses.models import Expense
        from apps.core.models import User
        user, _ = User.objects.get_or_create(username='restock_expense_user')
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=material.accounting_category
                or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            purchased_by=user,
            material=material,
        )

    def test_partial_restock_manual_add_shrinks_quantity_and_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
        )
        MaterialService.restock(m, Decimal('2'))
        m.refresh_from_db()
        self.assertEqual(m.quantity, Decimal('3'))
        # Restock tracks the return universally now (was expense-bound only):
        # quantity + released_qty always reconstructs the original plan.
        self.assertEqual(m.released_qty, Decimal('2'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(inventory_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())

    def test_full_restock_manual_add_deletes_row(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
        )
        mid = m.pk
        MaterialService.restock(m, Decimal('5'))
        self.assertFalse(Material.objects.filter(pk=mid).exists())
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli, job=self.job).exists())

    def test_partial_restock_expense_bound_shrinks_quantity_and_bumps_released_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
        )
        self._make_expense_bound(m)
        MaterialService.restock(m, Decimal('2'))
        m.refresh_from_db()
        self.assertEqual(m.quantity, Decimal('3'))
        self.assertEqual(m.released_qty, Decimal('2'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(inventory_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())

    def test_full_restock_expense_bound_releases_row(self):
        # An expense-bound material is referenced, so restock-to-zero lands it
        # in the released state (the old keep-pending-at-zero limbo, named).
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
        )
        self._make_expense_bound(m)
        MaterialService.restock(m, Decimal('5'))
        m.refresh_from_db()
        self.assertEqual(m.quantity, Decimal('0'))
        self.assertEqual(m.released_qty, Decimal('5'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli, job=self.job).exists())
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())

    def test_restock_validates_positive_and_leq_quantity(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('0'))
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('3'))


class DrawMoreTest(TestCase):
    def setUp(self):
        # match Job/contact setup used by RestockTest/ConsumeTest in this file
        cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='d@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-D-1', contact=self.contact,
                                      status=Job.STATUS_APPROVED)
        self.pli = InventoryItem.objects.create(
            code='I', accounting_category=cat,
            qty_on_hand=Decimal('10'),
        )

    def test_draw_more_increases_quantity_and_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        MaterialService.draw_more(m, Decimal('3'))
        m.refresh_from_db()
        self.assertEqual(m.quantity, Decimal('5'))
        e = Earmark.objects.get(inventory_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

    def test_draw_more_rejects_non_positive(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), inventory_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            MaterialService.draw_more(m, Decimal('0'))

    def test_draw_more_forbidden_on_expense_bound(self):
        from apps.expenses.models import Expense
        from apps.core.models import User
        user = User.objects.create(username='drawmore_user')
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), inventory_item=self.pli,
        )
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=m.accounting_category or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            purchased_by=user,
            material=m,
        )
        with self.assertRaises(ValidationError):
            MaterialService.draw_more(m, Decimal('1'))
