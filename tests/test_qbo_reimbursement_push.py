"""
Tests for QBOExpenseSyncService.push_reimbursement.

These tests characterize the reimbursement QBO push path in isolation using
mocked QBO clients and Purchase.save — no real QBO connection required.

Branch conclusion tracked here: expected ENV-ONLY (no QBO sandbox in dev), but
confirmed by the characterization test passing on first run.
"""
import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense, Reimbursement
from apps.expenses.services import ReimbursementService
from apps.qbo.services import QBOExpenseSyncService

User = get_user_model()


def _seed_payment_accounts():
    Configuration.objects.update_or_create(
        key='qbo_payment_accounts',
        defaults={'value': json.dumps([
            {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
        ])},
    )


class ReimbursementPushCharacterizationTest(TestCase):
    """Characterization: does the push succeed with a valid batch and mocked client?"""

    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )
        # Build a reimbursement batch via direct model creation (batch already committed;
        # expenses are already flipped to reimbursed) so push_reimbursement can be called
        # directly without going through create_batch.
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='35',
            reference_number='1234',
            notes='',
            created_by=self.admin,
        )
        for amt in ('47.50', '62.00', '28.75'):
            Expense.objects.create(
                entered_by=self.worker,
                purchased_by=self.worker,
                amount=Decimal(amt),
                purchased_on=date(2026, 4, 5),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_PERSONAL,
                status=Expense.STATUS_REIMBURSED,
                reimbursement=self.batch,
            )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_succeeds_with_valid_data(self, mock_get_client, mock_log_sync):
        """Characterization: valid batch + mocked client → returns qbo_id."""
        client = MagicMock()
        mock_get_client.return_value = client

        with patch('quickbooks.objects.purchase.Purchase.save', autospec=True) as mock_save:
            def _save(self, qb=None):
                self.Id = 'qbo-purch-1'
            mock_save.side_effect = _save

            qbo_id = QBOExpenseSyncService.push_reimbursement(self.batch)

        self.assertEqual(qbo_id, 'qbo-purch-1')


class ReimbursementPushNoConnectionTest(TestCase):
    """When get_client returns None (no sandbox wired), push raises ValueError."""

    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker2', password='testpass')
        self.admin = User.objects.create_user(username='admin2', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP2', name='Shop Supplies 2', qbo_expense_account_id='501',
        )
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='35',
            reference_number='',
            notes='',
            created_by=self.admin,
        )
        Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=self.batch,
        )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_push_reimbursement_raises_when_no_connection(self, mock_get_client, mock_log_sync):
        """No QBO connection → raises ValueError('No active QBO connection')."""
        with self.assertRaises(ValueError) as ctx:
            QBOExpenseSyncService.push_reimbursement(self.batch)
        self.assertIn('No active QBO connection', str(ctx.exception))


class ReimbursementCreateBatchSyncFailedTest(TestCase):
    """When get_client returns None, create_batch records sync_failed but commits the batch."""

    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker3', password='testpass')
        self.admin = User.objects.create_user(username='admin3', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP3', name='Shop Supplies 3', qbo_expense_account_id='502',
        )

    def _expense(self, amt='25.00'):
        return Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal(amt),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_SUBMITTED,
        )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_create_batch_records_sync_failed_when_no_connection(
        self, mock_get_client, mock_log_sync
    ):
        """No QBO connection → batch is committed but qbo_sync_status=sync_failed."""
        e1 = self._expense('25.00')
        e2 = self._expense('15.00')

        batch = ReimbursementService.create_batch(
            purchased_by=self.worker,
            expense_ids=[e1.pk, e2.pk],
            paid_on=date(2026, 4, 11),
            payment_account_id='35',
            reference_number='',
            notes='',
            created_by=self.admin,
        )

        # Batch is committed in the DB
        self.assertIsNotNone(batch.pk)
        # Expenses flipped to reimbursed (local commit stands)
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.status, Expense.STATUS_REIMBURSED)
        self.assertEqual(e2.status, Expense.STATUS_REIMBURSED)
        # QBO push failed → sync_failed
        batch.refresh_from_db()
        self.assertEqual(batch.qbo_sync_status, Reimbursement.SYNC_FAILED)
        self.assertIn('No active QBO connection', batch.qbo_sync_error)


class ReimbursementRetrySyncTest(TestCase):
    """retry_sync succeeds when client is available."""

    def setUp(self):
        _seed_payment_accounts()
        self.worker = User.objects.create_user(username='worker4', password='testpass')
        self.admin = User.objects.create_user(username='admin4', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='SUP4', name='Shop Supplies 4', qbo_expense_account_id='503',
        )
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='35',
            reference_number='',
            notes='',
            created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_sync_error='No active QBO connection',
        )
        Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal('30.00'),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=self.batch,
        )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_retry_sync_succeeds_when_connection_available(
        self, mock_get_client, mock_log_sync
    ):
        """retry_sync with a valid client transitions batch to synced."""
        client = MagicMock()
        mock_get_client.return_value = client

        with patch('quickbooks.objects.purchase.Purchase.save', autospec=True) as mock_save:
            def _save(self, qb=None):
                self.Id = 'qbo-purch-retry-1'
            mock_save.side_effect = _save

            result = ReimbursementService.retry_sync(batch=self.batch, actor=self.admin)

        self.assertEqual(result.qbo_sync_status, Reimbursement.SYNC_SYNCED)
        self.assertEqual(result.qbo_sync_error, '')
        self.assertEqual(result.qbo_id, 'qbo-purch-retry-1')
