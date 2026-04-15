from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task
from apps.inventory.models import Material

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
        self.assertEqual(exp.status, Expense.STATUS_SYNCED)
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
        self.assertEqual(exp.status, Expense.STATUS_SYNC_FAILED)
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
            status=Expense.STATUS_SYNCED,
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
            payment_account_id='57', status=Expense.STATUS_SYNCED, qbo_id='9001',
        )
        pk = exp.pk
        ExpenseService.delete(expense=exp, actor=self.user)
        self.assertFalse(Expense.objects.filter(pk=pk).exists())
        mock_void.assert_called_once()


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
            payment_account_id='57', status=Expense.STATUS_SYNCED,
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
            status=Expense.STATUS_SYNC_FAILED,
            qbo_sync_error='previous failure',
        )
        result = ExpenseService.retry_sync(expense=exp, actor=self.user)
        self.assertEqual(result.status, Expense.STATUS_SYNCED)
        self.assertEqual(result.qbo_sync_error, '')
        mock_push.assert_called_once()


class FindOrCreateMaterialsTaskTest(TestCase):
    def setUp(self):
        _seed_job_config()
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.contact = Contact.objects.create(
            first_name='A', last_name='B',
            email='a@b.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number='JOB-2026-0001', contact=self.contact,
        )

    def test_creates_task_in_complete_state_on_first_call(self):
        task = ExpenseService.find_or_create_materials_task(job=self.job)
        self.assertEqual(task.status, Task.STATUS_COMPLETE)
        self.assertEqual(task.job, self.job)

    def test_reuses_existing_task_on_second_call(self):
        first = ExpenseService.find_or_create_materials_task(job=self.job)
        second = ExpenseService.find_or_create_materials_task(job=self.job)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.job.tasks.filter(name='Materials').count(), 1)
