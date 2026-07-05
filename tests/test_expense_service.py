from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService

User = get_user_model()


def _seed_job_config():
    Configuration.objects.update_or_create(
        key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'},
    )
    Configuration.objects.update_or_create(
        key='job_counter', defaults={'value': '0'},
    )


class ExpenseSubmitPersonalTest(TestCase):
    def setUp(self):
        _seed_job_config()
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )

    def test_submit_personal_stays_submitted(self):
        exp = ExpenseService.submit(
            entered_by=self.user,
            purchased_by=self.user,
            amount=Decimal('47.50'),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)
        self.assertEqual(exp.qbo_id, '')

    def test_submit_personal_requires_purchased_by(self):
        with self.assertRaises(ValidationError):
            ExpenseService.submit(
                entered_by=self.user,
                purchased_by=None,
                amount=Decimal('10.00'),
                purchased_on=date(2026, 4, 5),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            )


class ExpenseSubmitCompanyTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        _seed_job_config()
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_submit_company_pushes_and_flips_to_synced(self, mock_push):
        mock_push.return_value = '9001'
        exp = ExpenseService.submit(
            entered_by=self.user,
            amount=Decimal('218.45'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
        )
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_SYNCED)
        mock_push.assert_called_once()

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_submit_company_sync_failure_leaves_sync_failed(self, mock_push):
        mock_push.side_effect = RuntimeError('qbo down')
        exp = ExpenseService.submit(
            entered_by=self.user,
            amount=Decimal('218.45'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
        )
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_FAILED)
        self.assertIn('qbo down', exp.qbo_sync_error)

    def test_submit_company_requires_payment_account(self):
        with self.assertRaises(ValidationError):
            ExpenseService.submit(
                entered_by=self.user,
                amount=Decimal('10.00'),
                purchased_on=date(2026, 4, 5),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_COMPANY,
                payment_account_id='',
            )


class ExpenseUpdateTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.update_expense')
    def test_update_synced_expense_triggers_resync(self, mock_update):
        exp = Expense.objects.create(
            entered_by=self.user,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_sync_status=Expense.SYNC_SYNCED,
            qbo_id='9001',
        )
        ExpenseService.update(expense=exp, actor=self.user, amount=Decimal('110.00'))
        exp.refresh_from_db()
        self.assertEqual(exp.amount, Decimal('110.00'))
        mock_update.assert_called_once()

    @patch('apps.qbo.services.QBOExpenseSyncService.update_expense')
    def test_update_unsynced_personal_expense_no_qbo_call(self, mock_update):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        exp = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('47.50'),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        ExpenseService.update(expense=exp, actor=self.user, amount=Decimal('50.00'))
        exp.refresh_from_db()
        self.assertEqual(exp.amount, Decimal('50.00'))
        mock_update.assert_not_called()


class ExpenseDeleteTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.void_expense')
    def test_delete_synced_expense_voids_and_deletes(self, mock_void):
        exp = Expense.objects.create(
            entered_by=self.user, amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57', qbo_sync_status=Expense.SYNC_SYNCED, qbo_id='9001',
        )
        pk = exp.pk
        ExpenseService.delete(expense=exp, actor=self.user)
        self.assertFalse(Expense.objects.filter(pk=pk).exists())
        mock_void.assert_called_once()

    @patch('apps.qbo.services.QBOExpenseSyncService.void_expense')
    def test_delete_void_failure_raises_validation_error_and_retains_expense(self, mock_void):
        """When void raises, delete raises ValidationError and the expense row survives."""
        from django.core.exceptions import ValidationError
        mock_void.side_effect = RuntimeError('qbo down')
        exp = Expense.objects.create(
            entered_by=self.user, amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57', qbo_sync_status=Expense.SYNC_SYNCED, qbo_id='9001',
        )
        pk = exp.pk
        with self.assertRaises(ValidationError):
            ExpenseService.delete(expense=exp, actor=self.user)
        self.assertTrue(Expense.objects.filter(pk=pk).exists())
        exp.refresh_from_db()
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_FAILED)

    @patch('apps.qbo.services.QBOExpenseSyncService.void_expense')
    def test_delete_void_failure_does_not_reverse_stock(self, mock_void):
        """When void fails, QOH is unchanged (stock reversal was never reached)."""
        from apps.inventory.models import InventoryItem
        mock_void.side_effect = RuntimeError('qbo down')
        pli = InventoryItem.objects.create(
            code='VF1', description='plywood', accounting_category=self.cat,
            qty_on_hand=Decimal('10.00'),
        )
        exp = Expense.objects.create(
            entered_by=self.user, amount=Decimal('50.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57', qbo_sync_status=Expense.SYNC_SYNCED, qbo_id='9001',
            stock_pli=pli, stock_qty=Decimal('3.00'),
        )
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ExpenseService.delete(expense=exp, actor=self.user)
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('10.00'))  # unchanged

    def test_delete_no_qbo_id_deletes_locally_no_qbo_call(self):
        """Expense without qbo_id deletes locally without any QBO call."""
        exp = Expense.objects.create(
            entered_by=self.user, purchased_by=self.user,
            amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        pk = exp.pk
        with patch('apps.qbo.services.QBOExpenseSyncService.void_expense') as mock_void:
            ExpenseService.delete(expense=exp, actor=self.user)
            mock_void.assert_not_called()
        self.assertFalse(Expense.objects.filter(pk=pk).exists())

    def test_delete_reimbursed_expense_raises_upfront(self):
        """Reimbursed expense raises ValidationError before any QBO call."""
        from django.core.exceptions import ValidationError
        from apps.expenses.models import Reimbursement
        batch = Reimbursement.objects.create(
            purchased_by=self.user, paid_on=date(2026, 4, 2),
            payment_account_id='ACC', created_by=self.user,
        )
        exp = Expense.objects.create(
            entered_by=self.user, purchased_by=self.user,
            amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            reimbursement=batch,
        )
        with patch('apps.qbo.services.QBOExpenseSyncService.void_expense') as mock_void:
            with self.assertRaises(ValidationError):
                ExpenseService.delete(expense=exp, actor=self.user)
            mock_void.assert_not_called()


class ExpenseRejectTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')

    def _personal(self):
        return Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('47.50'),
            purchased_on=date(2026, 4, 5), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )

    def test_reject_personal_flips_to_rejected(self):
        exp = self._personal()
        result = ExpenseService.reject(expense=exp, actor=self.admin)
        self.assertEqual(result.status, Expense.STATUS_REJECTED)

    def test_reject_company_raises(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        exp = Expense.objects.create(
            entered_by=self.admin, amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57', qbo_sync_status=Expense.SYNC_SYNCED,
        )
        with self.assertRaises(ValidationError):
            ExpenseService.reject(expense=exp, actor=self.admin)


class ExpenseRetrySyncTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_retry_sync_on_sync_failed_calls_push_and_flips_to_synced(self, mock_push):
        mock_push.return_value = '9001'
        exp = Expense.objects.create(
            entered_by=self.user, amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 9), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_sync_status=Expense.SYNC_FAILED,
            qbo_sync_error='previous failure',
        )
        result = ExpenseService.retry_sync(expense=exp, actor=self.user)
        self.assertEqual(result.qbo_sync_status, Expense.SYNC_SYNCED)
        self.assertEqual(result.qbo_sync_error, '')
        mock_push.assert_called_once()




class ExpenseJobLinkTest(TestCase):
    """Job anchor, own-material creation, stock receipts, freeze, move-between-jobs."""

    def setUp(self):
        _seed_job_config()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='c@test.com',
        )
        self.job = Job.objects.create(job_number='JOB-L1', contact=self.contact)
        self.other_job = Job.objects.create(job_number='JOB-L2', contact=self.contact)

    def _expense(self, *, amount=Decimal('10.00'), job=None, new_material=None):
        return ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user, amount=amount,
            purchased_on=date(2026, 4, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            job=job, new_material=new_material,
        )

    def test_submit_accepts_job(self):
        exp = self._expense(job=self.job)
        self.assertEqual(exp.job_id, self.job.pk)

    def test_update_changes_job_material_less(self):
        exp = self._expense(job=self.job)
        ExpenseService.update(expense=exp, actor=self.user, job=self.other_job)
        exp.refresh_from_db()
        self.assertEqual(exp.job_id, self.other_job.pk)

    def test_freeform_new_material_uses_entered_cost_no_division(self):
        # The created material's unit_cost is what the user entered (price),
        # NOT amount/quantity. Goods = 2 × $30 = $60; amount $66 (incl $6 tax) —
        # the amount exceeds goods, and unit_cost stays $30 (not $33 = 66/2).
        exp = self._expense(amount=Decimal('66.00'), new_material={
            'job_id': self.job.pk, 'description': 'Steel',
            'quantity': 2, 'price': Decimal('30.00')})
        self.assertEqual(exp.job_id, self.job.pk)
        self.assertIsNotNone(exp.material_id)
        exp.material.refresh_from_db()
        self.assertEqual(exp.material.unit_cost, Decimal('30.00'))

    def test_inventoried_pli_becomes_stock_receipt(self):
        from apps.inventory.models import InventoryItem
        pli = InventoryItem.objects.create(
            code='PLY', description='plywood', accounting_category=self.cat,
            qty_on_hand=Decimal('7.00'))
        exp = self._expense(amount=Decimal('73.33'), new_material={
            'job_id': self.job.pk, 'inventory_item_id': pli.pk, 'quantity': 3})
        self.assertIsNone(exp.material_id)             # no consumable
        self.assertEqual(exp.stock_pli_id, pli.pk)
        self.assertEqual(exp.stock_qty, Decimal('3.00'))
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('10.00'))  # 7 + 3

    def test_stock_receipt_delete_reverses_qoh(self):
        from apps.inventory.models import InventoryItem
        pli = InventoryItem.objects.create(
            code='PLY2', description='p', accounting_category=self.cat,
            qty_on_hand=Decimal('7.00'))
        exp = self._expense(amount=Decimal('73.33'), new_material={
            'job_id': self.job.pk, 'inventory_item_id': pli.pk, 'quantity': 3})
        ExpenseService.delete(expense=exp, actor=self.user)
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('7.00'))  # back to 7

    def test_frozen_when_material_on_invoice(self):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        exp = self._expense(amount=Decimal('15.00'), new_material={
            'job_id': self.job.pk, 'description': 'm', 'quantity': 1, 'price': Decimal('15.00')})
        inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-FREEZE-1', status=Invoice.STATUS_OPEN,
        )
        li = InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, description='x',
            qty=Decimal('1.00'), price=Decimal('15.00'), accounting_category=self.cat,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL, source_pk=exp.material_id,
        )
        with self.assertRaises(ValidationError):
            ExpenseService.update(expense=exp, actor=self.user, amount=Decimal('99.00'))

    def test_move_material_linked_expense_moves_material_job(self):
        from apps.inventory.models import Material
        exp = self._expense(amount=Decimal('15.00'), new_material={
            'job_id': self.job.pk, 'description': 'm', 'quantity': 1, 'price': Decimal('15.00')})
        ExpenseService.update(expense=exp, actor=self.user, job=self.other_job)
        exp.refresh_from_db()
        exp.material.refresh_from_db()
        self.assertEqual(exp.job_id, self.other_job.pk)
        self.assertEqual(exp.material.job_id, self.other_job.pk)


class ExpenseInvoiceFreezeTest(TestCase):
    """A material-less expense is frozen while it is itself on an invoice (B2)."""

    def setUp(self):
        _seed_job_config()
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        self.user = User.objects.create_user(username='frz', password='x')
        self.cat = AccountingCategory.objects.create(code='FRZ', name='frz')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='f@t.com')
        self.job = Job.objects.create(job_number='JOB-FRZ-1', contact=self.contact)

    def test_frozen_when_expense_on_invoice(self):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        exp = ExpenseService.submit(
            entered_by=self.user, purchased_by=self.user, amount=Decimal('40.00'),
            purchased_on=date(2026, 4, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL, job=self.job)
        inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-FRZ-1', status=Invoice.STATUS_OPEN)
        li = InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, description='shipping',
            qty=Decimal('1.00'), price=Decimal('40.00'), accounting_category=self.cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_EXPENSE, source_pk=exp.pk)
        with self.assertRaises(ValidationError):
            ExpenseService.update(expense=exp, actor=self.user, amount=Decimal('99.00'))


class ExpenseReimbursedFreezeTest(TestCase):
    """A reimbursed expense's money fields are locked; it can't be deleted."""

    def setUp(self):
        from apps.expenses.models import Reimbursement
        self.user = User.objects.create_user(username='rb', password='x')
        self.other = User.objects.create_user(username='rb2', password='x')
        self.cat = AccountingCategory.objects.create(code='RB', name='rb')
        self.exp = Expense.objects.create(
            entered_by=self.user, purchased_by=self.user, amount=Decimal('40.00'),
            purchased_on=date(2026, 4, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL)
        self.batch = Reimbursement.objects.create(
            purchased_by=self.user, paid_on=date(2026, 4, 2),
            payment_account_id='ACC', created_by=self.user)
        self.exp.reimbursement = self.batch
        self.exp.status = Expense.STATUS_REIMBURSED
        self.exp.save(update_fields=['reimbursement', 'status'])

    def test_amount_locked(self):
        with self.assertRaises(ValidationError):
            ExpenseService.update(expense=self.exp, actor=self.user, amount=Decimal('99.00'))

    def test_purchased_by_locked(self):
        with self.assertRaises(ValidationError):
            ExpenseService.update(expense=self.exp, actor=self.user, purchased_by=self.other)

    def test_nonmoney_field_editable(self):
        ExpenseService.update(expense=self.exp, actor=self.user, description='clarified')
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.description, 'clarified')

    def test_unchanged_money_field_ok(self):
        # Re-sending the same amount (e.g. full-payload PATCH) is not a change.
        ExpenseService.update(expense=self.exp, actor=self.user,
                              amount=Decimal('40.00'), description='note')
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.description, 'note')

    def test_delete_blocked(self):
        with self.assertRaises(ValidationError):
            ExpenseService.delete(expense=self.exp, actor=self.user)
