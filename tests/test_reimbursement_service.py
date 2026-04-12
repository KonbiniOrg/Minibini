from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense, Reimbursement
from apps.expenses.services import ReimbursementService

User = get_user_model()


def _seed_payment_accounts():
    Configuration.objects.update_or_create(
        key='qbo_payment_accounts',
        defaults={'value': (
            '[{"qbo_account_id": "42", "display_name": "BoA Checking", "account_type": "Bank"}]'
        )},
    )


def _mock_push_sets_qbo_id(batch):
    """Side-effect that mimics the real push_reimbursement setting qbo_id."""
    batch.qbo_id = '9100'
    batch.save(update_fields=['qbo_id'])
    return '9100'


class ReimbursementCreateBatchTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )

    def _expense(self, amt='47.50', status=Expense.STATUS_SUBMITTED,
                 purchased_by=None, method=Expense.PAYMENT_METHOD_PERSONAL,
                 payment_account_id=''):
        return Expense.objects.create(
            entered_by=self.worker,
            purchased_by=purchased_by or self.worker,
            amount=Decimal(amt),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=method,
            payment_account_id=payment_account_id,
            status=status,
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_create_batch_flips_expenses_and_pushes(self, mock_push):
        mock_push.side_effect = _mock_push_sets_qbo_id
        e1 = self._expense('47.50')
        e2 = self._expense('62.00')
        e3 = self._expense('28.75')

        batch = ReimbursementService.create_batch(
            purchased_by=self.worker,
            expense_ids=[e1.pk, e2.pk, e3.pk],
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            reference_number='1234',
            notes='',
            created_by=self.admin,
        )
        self.assertEqual(batch.status, Reimbursement.STATUS_SYNCED)
        self.assertEqual(batch.qbo_id, '9100')
        self.assertEqual(batch.total, Decimal('138.25'))
        for e in (e1, e2, e3):
            e.refresh_from_db()
            self.assertEqual(e.status, Expense.STATUS_REIMBURSED)
            self.assertEqual(e.reimbursement, batch)
        mock_push.assert_called_once()

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_create_batch_sync_failure_flips_batch_status(self, mock_push):
        mock_push.side_effect = RuntimeError('qbo down')
        e1 = self._expense('10.00')
        batch = ReimbursementService.create_batch(
            purchased_by=self.worker,
            expense_ids=[e1.pk],
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            reference_number='',
            notes='',
            created_by=self.admin,
        )
        # Expenses are still flipped to reimbursed — real-world check was cut.
        e1.refresh_from_db()
        self.assertEqual(e1.status, Expense.STATUS_REIMBURSED)
        self.assertEqual(batch.status, Reimbursement.STATUS_SYNC_FAILED)
        self.assertIn('qbo down', batch.qbo_sync_error)

    def test_create_batch_rejects_mixed_user_expenses(self):
        _seed_payment_accounts()
        other = User.objects.create_user(username='other', password='testpass')
        mine = self._expense('10.00')
        theirs = self._expense('20.00', purchased_by=other)
        with self.assertRaises(ValidationError) as ctx:
            ReimbursementService.create_batch(
                purchased_by=self.worker,
                expense_ids=[mine.pk, theirs.pk],
                paid_on=date(2026, 4, 11),
                payment_account_id='42',
                reference_number='',
                notes='',
                created_by=self.admin,
            )
        self.assertIn('expense_ids', ctx.exception.message_dict)

    def test_create_batch_rejects_non_submitted_expenses(self):
        reimbursed = self._expense('10.00', status=Expense.STATUS_REIMBURSED)
        with self.assertRaises(ValidationError):
            ReimbursementService.create_batch(
                purchased_by=self.worker,
                expense_ids=[reimbursed.pk],
                paid_on=date(2026, 4, 11),
                payment_account_id='42',
                reference_number='',
                notes='',
                created_by=self.admin,
            )

    def test_create_batch_rejects_company_paid_expenses(self):
        company = self._expense(
            '10.00',
            method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='42',
            purchased_by=None,
        )
        with self.assertRaises(ValidationError):
            ReimbursementService.create_batch(
                purchased_by=self.worker,
                expense_ids=[company.pk],
                paid_on=date(2026, 4, 11),
                payment_account_id='42',
                reference_number='',
                notes='',
                created_by=self.admin,
            )

    def test_create_batch_requires_nonempty_expense_ids(self):
        with self.assertRaises(ValidationError):
            ReimbursementService.create_batch(
                purchased_by=self.worker,
                expense_ids=[],
                paid_on=date(2026, 4, 11),
                payment_account_id='42',
                reference_number='',
                notes='',
                created_by=self.admin,
            )


class ReimbursementRetrySyncTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            status=Reimbursement.STATUS_SYNC_FAILED,
            qbo_sync_error='previous fail',
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_retry_sync_calls_push_and_flips_to_synced(self, mock_push):
        mock_push.return_value = '9100'
        result = ReimbursementService.retry_sync(batch=self.batch, actor=self.admin)
        self.assertEqual(result.status, Reimbursement.STATUS_SYNCED)
        self.assertEqual(result.qbo_sync_error, '')


class ReimbursementDeleteTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            status=Reimbursement.STATUS_SYNCED,
            qbo_id='9100',
        )
        self.e1 = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('47.50'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=self.batch,
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.void_reimbursement')
    def test_delete_batch_voids_qbo_and_flips_expenses_back(self, mock_void):
        batch_pk = self.batch.pk
        ReimbursementService.delete(batch=self.batch, actor=self.admin)
        self.assertFalse(Reimbursement.objects.filter(pk=batch_pk).exists())
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.status, Expense.STATUS_SUBMITTED)
        self.assertIsNone(self.e1.reimbursement)
        mock_void.assert_called_once()
