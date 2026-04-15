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
from apps.inventory.models import Material, Earmark, PriceListItem
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

        cat = AccountingCategory.objects.create(code='CAT1', name='c')
        self.pli = PriceListItem.objects.create(
            code='I',
            accounting_category=cat,
            is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_receive_ad_hoc_purchase_bumps_qoh_only(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('12'))

    def test_reverse_ad_hoc_purchase_drops_qoh(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        InventoryService.reverse_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))

    def test_receive_ad_hoc_purchase_non_inventoried_is_noop(self):
        """receive_ad_hoc_purchase on a non-inventoried PLI does nothing."""
        cat = AccountingCategory.objects.create(code='CAT2', name='d')
        pli_noninv = PriceListItem.objects.create(
            code='NI', accounting_category=cat, is_inventoried=False,
            qty_on_hand=Decimal('5'),
        )
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='y',
            quantity=Decimal('3'), price_list_item=pli_noninv,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        pli_noninv.refresh_from_db()
        self.assertEqual(pli_noninv.qty_on_hand, Decimal('5'))

    def test_receive_ad_hoc_purchase_no_pli_is_noop(self):
        """receive_ad_hoc_purchase on a material with no PLI does nothing."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='z',
            quantity=Decimal('1'), price_list_item=None,
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
        self.pli = PriceListItem.objects.create(
            code='I-EX', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_submit_inventoried_creates_taskless_material_and_bumps_qoh(self):
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
                'price_list_item_id': self.pli.pk,
            },
        )
        self.assertEqual(exp.material.job_id, self.job.pk)
        self.assertIsNone(exp.material.task_id)
        self.assertEqual(exp.material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('15'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

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


class ExpenseRejectCascadeTest(TestCase):
    def setUp(self):
        contact = Contact.objects.create(
            first_name='Reject', last_name='User',
            email='rjtest@example.com', work_number='555-0300',
        )
        business = Business.objects.create(
            business_name='Reject Test Business',
            default_contact=contact,
        )
        contact.business = business
        contact.save()

        self.cat = AccountingCategory.objects.create(name='c', code='RJCAT1')
        self.user = User.objects.create(username='rj_user')
        self.job = Job.objects.create(job_number='JOB-RJ-1', contact=contact)
        self.pli = PriceListItem.objects.create(
            code='I-RJ', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def _submit(self, qty=Decimal('3')):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('10'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'x',
                'quantity': qty, 'price': Decimal('10'),
                'price_list_item_id': self.pli.pk,
            },
        )

    def test_reject_pending_reverses_earmark_qoh_and_deletes_material(self):
        exp = self._submit()
        mid = exp.material.pk
        ExpenseService.reject(expense=exp, actor=self.user)
        self.assertFalse(Material.objects.filter(pk=mid).exists())
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
        self.assertFalse(Earmark.objects.filter(
            price_list_item=self.pli, job=self.job).exists())

    def test_reject_forbidden_when_material_consumed(self):
        from django.core.exceptions import ValidationError
        exp = self._submit()
        MaterialService.consume(exp.material)
        with self.assertRaises(ValidationError):
            ExpenseService.reject(expense=exp, actor=self.user)

    def test_reject_after_full_restock_expense_bound_survives_until_reject(self):
        exp = self._submit(qty=Decimal('2'))
        MaterialService.restock(exp.material, Decimal('2'))
        exp.material.refresh_from_db()
        self.assertTrue(Material.objects.filter(pk=exp.material.pk).exists())
        self.assertEqual(exp.material.effective_qty, Decimal('0'))
        ExpenseService.reject(expense=exp, actor=self.user)
        self.assertFalse(Material.objects.filter(pk=exp.material.pk).exists())
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
