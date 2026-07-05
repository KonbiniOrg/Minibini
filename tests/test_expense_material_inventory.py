"""
Tests for receive_ad_hoc_purchase / reverse_ad_hoc_purchase (QOH only, no earmark).

Note: MaterialService.create_on_job already creates the earmark.
receive_ad_hoc_purchase is QOH-only — it does not touch earmarks.
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.inventory.models import Material, Earmark, InventoryItem
from apps.inventory.services import InventoryService, MaterialService
from apps.jobs.models import Job

User = get_user_model()


class AdHocPurchaseTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='JOB-AH-1',
            contact=self.contact,
        )

        self.cat = AccountingCategory.objects.create(code='CAT1', name='c')
        self.pli = InventoryItem.objects.create(
            code='I',
            accounting_category=self.cat,
            is_catalog=True,
            qty_on_hand=Decimal('10'),
        )

    def test_receive_ad_hoc_purchase_bumps_qoh_only(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('12'))

    def test_reverse_ad_hoc_purchase_drops_qoh(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
        )
        # Simulate a prior partial restock directly: quantity=5, released_qty=2.
        # Invariant: quantity + released_qty == original purchase (7).
        m.released_qty = Decimal('2')
        m.save(update_fields=['released_qty'])
        # PLI QOH starts at 10 per setUp. reverse should drop by full 7.
        InventoryService.reverse_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('3'))

    def test_receive_ad_hoc_purchase_lot_bumps_qoh(self):
        """Universal tracking: receive_ad_hoc_purchase bumps QOH for any
        item-backed material (catalog or non-catalog lot). Only a None-item
        material is a no-op (see test_receive_ad_hoc_purchase_no_pli_is_noop)."""
        cat = AccountingCategory.objects.create(code='CAT2', name='d')
        pli_lot = InventoryItem.objects.create(
            code='NI', accounting_category=cat, is_catalog=False,
            qty_on_hand=Decimal('5'),
        )
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='y',
            quantity=Decimal('3'), inventory_item=pli_lot,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        pli_lot.refresh_from_db()
        self.assertEqual(pli_lot.qty_on_hand, Decimal('8'))  # 5 + 3

    def test_receive_ad_hoc_purchase_no_pli_is_noop(self):
        """receive_ad_hoc_purchase on a material with no PLI does nothing."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='z',
            quantity=Decimal('1'), inventory_item=None,
            accounting_category=self.cat,
        )
        # Should not raise
        InventoryService.receive_ad_hoc_purchase(m)


class ExpenseSubmitPathTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='exptest@example.com', work_number='555-0200',
        )
        self.business = Business.objects.create(
            business_name='Expense Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.cat = AccountingCategory.objects.create(name='c', code='EXCAT1')
        self.user = User.objects.create(username='exp_user')
        self.job = Job.objects.create(job_number='JOB-EX-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='I-EX', accounting_category=self.cat, is_catalog=True,
            qty_on_hand=Decimal('10'),
        )

    def test_submit_inventoried_is_stock_receipt(self):
        exp = ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('25'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk,
                'description': 'bolts',
                'quantity': Decimal('5'),
                'price': Decimal('5'),
                'inventory_item_id': self.pli.pk,
            },
        )
        # Inventoried PLI → stock receipt: no consumable material, QOH bumped,
        # no earmark (cost flows at consumption via the job's own material).
        self.assertIsNone(exp.material_id)
        self.assertEqual(exp.stock_pli_id, self.pli.pk)
        self.assertEqual(exp.stock_qty, Decimal('5'))
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('15'))
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli, job=self.job).exists())

    def test_submit_does_not_create_placeholder_task(self):
        from apps.jobs.models import Task
        ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('25'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'x',
                'quantity': Decimal('1'), 'price': Decimal('25'),
            },
        )
        self.assertFalse(Task.objects.filter(job=self.job, name='Materials').exists())

    def test_any_item_backed_purchase_is_stock_receipt(self):
        """Spec §Drop is_catalog: pli present → stock receipt, uniformly.
        No `is_catalog` kwarg is passed here on purpose — classification no
        longer depends on the flag at all."""
        pli = InventoryItem.objects.create(
            code='LOT-X', accounting_category=self.cat, units='ea',
            qty_on_hand=Decimal('0'))
        exp = ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('40.00'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            description='sheet',
            new_material={
                'job_id': self.job.pk, 'inventory_item_id': pli.pk,
                'quantity': Decimal('2'),
            },
        )
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('2'))
        self.assertEqual(exp.stock_pli_id, pli.pk)
        self.assertIsNone(exp.material_id)


class ExpenseRejectStockReceiptTest(TestCase):
    """Rejecting an inventoried (stock-receipt) expense reverses its QOH bump;
    rejecting a freeform consumable deletes the material; consumed → forbidden."""

    def setUp(self):
        contact = Contact.objects.create(
            first_name='Reject', last_name='User',
            email='rjtest@example.com', work_number='555-0300',
        )
        business = Business.objects.create(
            business_name='Reject Test Business', default_contact=contact,
        )
        contact.business = business
        contact.save()
        self.cat = AccountingCategory.objects.create(name='c', code='RJCAT1')
        self.user = User.objects.create(username='rj_user')
        self.job = Job.objects.create(job_number='JOB-RJ-1', contact=contact)
        self.pli = InventoryItem.objects.create(
            code='I-RJ', accounting_category=self.cat, is_catalog=True,
            qty_on_hand=Decimal('10'),
        )

    def _submit_stock(self, qty=Decimal('3')):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('10'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'x',
                'quantity': qty, 'inventory_item_id': self.pli.pk,
            },
        )

    def test_reject_reverses_stock_receipt_qoh(self):
        exp = self._submit_stock()
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('13'))  # 10 + 3
        ExpenseService.reject(expense=exp, actor=self.user)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))  # reversed
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_REJECTED)

    def test_reject_forbidden_when_freeform_material_consumed(self):
        from django.core.exceptions import ValidationError
        exp = ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('10'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'freeform',
                'quantity': Decimal('1'), 'price': Decimal('10')},
        )
        MaterialService.consume(exp.material)  # freeform: no QOH effect
        with self.assertRaises(ValidationError):
            ExpenseService.reject(expense=exp, actor=self.user)


class ExpenseRejectNonInventoriedTest(TestCase):
    """Gap 13: reject with a freeform (no PLI) expense material leaves QOH
    untouched — there's nothing to track. An item-backed purchase is a stock
    receipt uniformly now (catalog or not) — see
    test_reject_noninv_item_backed_purchase_is_stock_receipt below, which
    reverses the QOH bump exactly like the catalog case."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='NonInv', last_name='User',
            email='noninv@example.com', work_number='555-0400',
        )
        business = Business.objects.create(
            business_name='NonInv Business',
            default_contact=self.contact,
        )
        self.contact.business = business
        self.contact.save()

        self.cat = AccountingCategory.objects.create(name='ni', code='NICAT1')
        self.user = User.objects.create(username='ni_user')
        self.job = Job.objects.create(job_number='JOB-NI-1', contact=self.contact,
                                      status=Job.STATUS_APPROVED)
        self.pli_noninv = InventoryItem.objects.create(
            code='NI-PLI', accounting_category=self.cat, is_catalog=False,
            qty_on_hand=Decimal('5'),
        )

    def _submit_noninv(self):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('10'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'wrench',
                'quantity': Decimal('1'), 'price': Decimal('10'),
                'inventory_item_id': self.pli_noninv.pk,
            },
        )

    def _submit_freeform(self):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('8'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'miscellaneous',
                'quantity': Decimal('1'), 'price': Decimal('8'),
                # no inventory_item_id
            },
        )

    def test_reject_noninv_item_backed_purchase_is_stock_receipt(self):
        """Spec §Drop is_catalog: an item-backed purchase is a stock receipt
        regardless of is_catalog — no material/earmark created, and reject
        reverses the QOH bump exactly like the catalog case."""
        exp = self._submit_noninv()
        self.assertIsNone(exp.material_id)
        self.assertEqual(exp.stock_pli_id, self.pli_noninv.pk)
        self.assertFalse(Earmark.objects.filter(
            inventory_item=self.pli_noninv, job=self.job).exists())
        self.pli_noninv.refresh_from_db()
        self.assertEqual(self.pli_noninv.qty_on_hand, Decimal('6'))  # 5 + 1
        ExpenseService.reject(expense=exp, actor=self.user)
        self.pli_noninv.refresh_from_db()
        self.assertEqual(self.pli_noninv.qty_on_hand, Decimal('5'))  # reversed
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_REJECTED)

    def test_reject_freeform_material_deletes_without_qoh_change(self):
        exp = self._submit_freeform()
        mat_pk = exp.material.pk
        # Freeform has no PLI — no QOH to track
        ExpenseService.reject(expense=exp, actor=self.user)
        self.assertFalse(Material.objects.filter(pk=mat_pk).exists(),
                         'Freeform material should be deleted on reject')
