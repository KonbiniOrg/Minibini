"""
Config admins may read and retry QBO sync failures (RM 2026-10-17): the
Settings → Accounting tab is config-gated, so the sync-failures panel and
its Retry / Retry all buttons must work for a config-only user. The widening
is scoped to the retry surface — other financials writes stay financials-only.
"""
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense, Reimbursement

User = get_user_model()


def _user_with(username, codename):
    user = User.objects.create_user(username=username, password='testpass')
    perm = Permission.objects.get(codename=codename, content_type__app_label='core')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


class ConfigUserSyncFailureAccessTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '57', 'display_name': 'Amex', 'account_type': 'Credit Card'},
            ])},
        )
        self.http = Client()
        self.cat = AccountingCategory.objects.create(code='CFG', name='Cfg', qbo_expense_account_id='500')
        self.worker = User.objects.create_user(username='worker_cfg', password='testpass')
        self.config_user = _user_with('config_only', 'can_manage_config')
        self.http.force_login(self.config_user)

    def _failed_company_expense(self):
        return Expense.objects.create(
            entered_by=self.worker, amount=Decimal('100.00'), purchased_on=date(2026, 4, 1),
            description='Paint', accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY, payment_account_id='57',
            qbo_sync_status=Expense.SYNC_FAILED, qbo_pending_op=Expense.OP_CREATE,
            qbo_sync_error='QBO timeout',
        )

    def _failed_batch(self):
        batch = Reimbursement.objects.create(
            purchased_by=self.worker, paid_on=date(2026, 4, 3), payment_account_id='57',
            created_by=self.worker, qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_pending_op=Reimbursement.OP_CREATE, qbo_sync_error='Network error',
        )
        Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker, amount=Decimal('50.00'),
            purchased_on=date(2026, 4, 2), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED, reimbursement=batch,
        )
        return batch

    # --- the panel's list + Retry all ---

    def test_config_user_can_list_sync_failures(self):
        self._failed_company_expense()
        r = self.http.get('/api/qbo/sync-failures/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['failures']), 1)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense', return_value='9001')
    def test_config_user_can_retry_all(self, _mock_push):
        self._failed_company_expense()
        r = self.http.post('/api/qbo/sync-failures/retry-all/', content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['retried'], 1)

    # --- the panel's per-row Retry (expense/reimbursement retry-sync) ---

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense', return_value='9001')
    def test_config_user_can_retry_someone_elses_expense(self, _mock_push):
        exp = self._failed_company_expense()  # entered by worker, not the config user
        r = self.http.post(f'/api/expenses/{exp.pk}/retry-sync/')
        self.assertEqual(r.status_code, 200, r.content)
        exp.refresh_from_db()
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_SYNCED)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement', return_value='9100')
    def test_config_user_can_retry_reimbursement(self, _mock_push):
        batch = self._failed_batch()
        r = self.http.post(f'/api/reimbursements/{batch.pk}/retry-sync/')
        self.assertEqual(r.status_code, 200, r.content)
        batch.refresh_from_db()
        self.assertEqual(batch.qbo_sync_status, Reimbursement.SYNC_SYNCED)

    # --- the widening stops at the retry surface ---

    def test_config_user_still_cannot_edit_expense(self):
        exp = self._failed_company_expense()
        r = self.http.patch(f'/api/expenses/{exp.pk}/', data=json.dumps({'description': 'x'}),
                            content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_config_user_still_cannot_list_reimbursements(self):
        self._failed_batch()
        self.assertEqual(self.http.get('/api/reimbursements/').status_code, 403)

    def test_config_user_list_scoping_unchanged_for_expenses(self):
        """Config alone does not widen the expense list — still own-only."""
        self._failed_company_expense()
        r = self.http.get('/api/expenses/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual((data.get('results') if isinstance(data, dict) else data), [])


class NoAtomStillForbiddenTest(TestCase):
    def test_worker_forbidden_from_sync_failures(self):
        http = Client()
        http.force_login(User.objects.create_user(username='nobody', password='testpass'))
        self.assertEqual(http.get('/api/qbo/sync-failures/').status_code, 403)
        self.assertEqual(
            http.post('/api/qbo/sync-failures/retry-all/', content_type='application/json').status_code,
            403,
        )
