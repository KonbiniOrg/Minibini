"""
Tests for QBOSyncFailureService.list_failures(), GET /api/qbo/sync-failures/,
and POST /api/qbo/sync-failures/retry-all/.
"""
from decimal import Decimal
from datetime import date
import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import Permission

from apps.core.models import Configuration, AccountingCategory
from apps.expenses.models import Expense, Reimbursement
from apps.qbo.services import QBOSyncFailureService

from django.contrib.auth import get_user_model
User = get_user_model()


def _make_financials_user(username):
    user = User.objects.create_user(username=username, password='testpass')
    perm = Permission.objects.get(
        codename='can_manage_financials', content_type__app_label='core',
    )
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)  # re-fetch to clear perm cache


class QBOSyncFailureServiceTest(TestCase):
    """Unit-tests for QBOSyncFailureService.list_failures()."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '57', 'display_name': 'Amex', 'account_type': 'Credit Card'},
            ])},
        )
        self.cat = AccountingCategory.objects.create(
            code='TST', name='Test Category', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')

    def _failed_company_expense(self, pending_op=Expense.OP_CREATE):
        return Expense.objects.create(
            entered_by=self.worker,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 1),
            description='Paint supplies',
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_sync_status=Expense.SYNC_FAILED,
            qbo_pending_op=pending_op,
            qbo_sync_error='QBO timeout',
        )

    def _failed_personal_expense(self):
        """Personal expense — must NOT appear in list_failures()."""
        return Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal('25.00'),
            purchased_on=date(2026, 4, 2),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            qbo_sync_status=Expense.SYNC_FAILED,
            qbo_pending_op=Expense.OP_CREATE,
        )

    def _failed_reimbursement(self, pending_op=Reimbursement.OP_CREATE):
        batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 3),
            payment_account_id='57',
            created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_pending_op=pending_op,
            qbo_sync_error='Network error',
        )
        Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal('50.00'),
            purchased_on=date(2026, 4, 2),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=batch,
        )
        return batch

    def test_list_failures_includes_company_expense(self):
        exp = self._failed_company_expense()
        failures = QBOSyncFailureService.list_failures()
        entity_types = [f['entity_type'] for f in failures]
        self.assertIn('expense', entity_types)
        match = next(f for f in failures if f['entity_type'] == 'expense')
        self.assertEqual(match['id'], exp.pk)
        self.assertEqual(match['qbo_pending_op'], Expense.OP_CREATE)
        self.assertEqual(match['qbo_sync_error'], 'QBO timeout')
        self.assertIn('amount', match)
        self.assertIn('label', match)

    def test_list_failures_excludes_personal_expense(self):
        self._failed_personal_expense()
        failures = QBOSyncFailureService.list_failures()
        self.assertEqual(failures, [])

    def test_list_failures_includes_reimbursement(self):
        batch = self._failed_reimbursement()
        failures = QBOSyncFailureService.list_failures()
        entity_types = [f['entity_type'] for f in failures]
        self.assertIn('reimbursement', entity_types)
        match = next(f for f in failures if f['entity_type'] == 'reimbursement')
        self.assertEqual(match['id'], batch.pk)
        self.assertEqual(match['qbo_pending_op'], Reimbursement.OP_CREATE)

    def test_list_failures_both_types(self):
        self._failed_company_expense()
        self._failed_reimbursement()
        failures = QBOSyncFailureService.list_failures()
        entity_types = {f['entity_type'] for f in failures}
        self.assertEqual(entity_types, {'expense', 'reimbursement'})
        self.assertEqual(len(failures), 2)

    def test_list_failures_dict_shape(self):
        self._failed_company_expense()
        failures = QBOSyncFailureService.list_failures()
        self.assertEqual(len(failures), 1)
        f = failures[0]
        required_keys = {'entity_type', 'id', 'label', 'amount', 'qbo_pending_op', 'qbo_sync_error', 'retry_url'}
        self.assertEqual(set(f.keys()), required_keys)

    def test_retry_url_expense(self):
        exp = self._failed_company_expense()
        failures = QBOSyncFailureService.list_failures()
        match = next(f for f in failures if f['entity_type'] == 'expense')
        self.assertEqual(match['retry_url'], f'/api/expenses/{exp.pk}/retry-sync/')

    def test_retry_url_reimbursement(self):
        batch = self._failed_reimbursement()
        failures = QBOSyncFailureService.list_failures()
        match = next(f for f in failures if f['entity_type'] == 'reimbursement')
        self.assertEqual(match['retry_url'], f'/api/reimbursements/{batch.pk}/retry-sync/')

    def test_list_failures_empty_when_none(self):
        failures = QBOSyncFailureService.list_failures()
        self.assertEqual(failures, [])

    def test_list_failures_ignores_non_failed_records(self):
        """Synced/pending records must not appear."""
        Expense.objects.create(
            entered_by=self.worker,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_sync_status=Expense.SYNC_SYNCED,
        )
        Expense.objects.create(
            entered_by=self.worker,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_sync_status=Expense.SYNC_PENDING,
        )
        failures = QBOSyncFailureService.list_failures()
        self.assertEqual(failures, [])


class SyncFailuresEndpointTest(TestCase):
    """GET /api/qbo/sync-failures/ — list endpoint."""

    def setUp(self):
        self.client_http = Client()
        self.fin_user = _make_financials_user('fin_user')
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '57', 'display_name': 'Amex', 'account_type': 'Credit Card'},
            ])},
        )
        self.cat = AccountingCategory.objects.create(
            code='EP2', name='EP Test Cat', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='ep2_worker', password='testpass')
        self.admin = User.objects.create_user(username='ep2_admin', password='testpass')

    def _make_both(self):
        exp = Expense.objects.create(
            entered_by=self.worker, amount=Decimal('10.00'),
            purchased_on=date(2026, 5, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY, payment_account_id='57',
            qbo_sync_status=Expense.SYNC_FAILED, qbo_pending_op=Expense.OP_CREATE,
        )
        batch = Reimbursement.objects.create(
            purchased_by=self.worker, paid_on=date(2026, 5, 2),
            payment_account_id='57', created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_pending_op=Reimbursement.OP_UPDATE,
        )
        Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('20.00'), purchased_on=date(2026, 5, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED, reimbursement=batch,
        )
        return exp, batch

    def test_requires_authentication(self):
        r = self.client_http.get('/api/qbo/sync-failures/')
        self.assertIn(r.status_code, (401, 403))

    def test_requires_can_manage_financials(self):
        unpriv = User.objects.create_user(username='unpriv_sf', password='testpass')
        self.client_http.force_login(unpriv)
        r = self.client_http.get('/api/qbo/sync-failures/')
        self.assertEqual(r.status_code, 403)

    def test_returns_both_failure_types(self):
        self._make_both()
        self.client_http.force_login(self.fin_user)
        r = self.client_http.get('/api/qbo/sync-failures/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('failures', data)
        entity_types = {f['entity_type'] for f in data['failures']}
        self.assertEqual(entity_types, {'expense', 'reimbursement'})

    def test_each_failure_has_required_fields(self):
        self._make_both()
        self.client_http.force_login(self.fin_user)
        r = self.client_http.get('/api/qbo/sync-failures/')
        for f in r.json()['failures']:
            self.assertIn('entity_type', f)
            self.assertIn('id', f)
            self.assertIn('label', f)
            self.assertIn('amount', f)
            self.assertIn('qbo_pending_op', f)
            self.assertIn('qbo_sync_error', f)
            self.assertIn('retry_url', f)

    def test_personal_expense_not_included(self):
        personal = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('9.00'), purchased_on=date(2026, 5, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            qbo_sync_status=Expense.SYNC_FAILED,
            qbo_pending_op=Expense.OP_CREATE,
        )
        self.client_http.force_login(self.fin_user)
        r = self.client_http.get('/api/qbo/sync-failures/')
        self.assertEqual(r.status_code, 200)
        pks = [f['id'] for f in r.json()['failures'] if f['entity_type'] == 'expense']
        self.assertNotIn(personal.pk, pks)

    def test_qbo_pending_op_included(self):
        self._make_both()
        self.client_http.force_login(self.fin_user)
        r = self.client_http.get('/api/qbo/sync-failures/')
        ops = {f['entity_type']: f['qbo_pending_op'] for f in r.json()['failures']}
        self.assertEqual(ops['expense'], Expense.OP_CREATE)
        self.assertEqual(ops['reimbursement'], Reimbursement.OP_UPDATE)


class RetryAllEndpointTest(TestCase):
    """POST /api/qbo/sync-failures/retry-all/ — retry endpoint."""

    def setUp(self):
        self.client_http = Client()
        self.fin_user = _make_financials_user('fin_retry')
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '57', 'display_name': 'Amex', 'account_type': 'Credit Card'},
            ])},
        )
        self.cat = AccountingCategory.objects.create(
            code='RAT', name='Retry All Test', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='rat_worker', password='testpass')
        self.admin = User.objects.create_user(username='rat_admin', password='testpass')

    def _make_both_failed(self):
        exp = Expense.objects.create(
            entered_by=self.worker, amount=Decimal('11.00'),
            purchased_on=date(2026, 6, 1), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY, payment_account_id='57',
            qbo_sync_status=Expense.SYNC_FAILED, qbo_pending_op=Expense.OP_CREATE,
        )
        batch = Reimbursement.objects.create(
            purchased_by=self.worker, paid_on=date(2026, 6, 2),
            payment_account_id='57', created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_pending_op=Reimbursement.OP_CREATE,
        )
        Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('22.00'), purchased_on=date(2026, 6, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED, reimbursement=batch,
        )
        return exp, batch

    def test_requires_authentication(self):
        r = self.client_http.post('/api/qbo/sync-failures/retry-all/',
                                  content_type='application/json')
        self.assertIn(r.status_code, (401, 403))

    def test_requires_can_manage_financials(self):
        unpriv = User.objects.create_user(username='unpriv_ra', password='testpass')
        self.client_http.force_login(unpriv)
        r = self.client_http.post('/api/qbo/sync-failures/retry-all/',
                                  content_type='application/json')
        self.assertEqual(r.status_code, 403)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_retry_all_reports_retried_2(self, mock_reimb, mock_exp):
        """With mocked QBO pushes succeeding: retried=2, still_failing=0.

        push_expense and push_reimbursement are used by QBOSyncService.run_create,
        which calls record.mark_synced() on success.
        """
        mock_exp.return_value = 'qbo-e-1'
        mock_reimb.return_value = 'qbo-r-1'

        self._make_both_failed()

        self.client_http.force_login(self.fin_user)
        r = self.client_http.post('/api/qbo/sync-failures/retry-all/',
                                  content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['retried'], 2)
        self.assertEqual(data['still_failing'], 0)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_retry_all_one_failure_doesnt_abort_rest(self, mock_reimb, mock_exp):
        """One push raising must not abort the retry loop; the others complete.

        The expense push raises → QBOSyncService.run_create catches it and calls
        mark_failed (keeps it sync_failed). The reimbursement succeeds so only
        1 is still_failing.
        """
        mock_exp.side_effect = Exception('QBO down')
        mock_reimb.return_value = 'qbo-r-1'

        self._make_both_failed()

        self.client_http.force_login(self.fin_user)
        r = self.client_http.post('/api/qbo/sync-failures/retry-all/',
                                  content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['retried'], 2)
        # Expense push failed so it is still_failing
        self.assertEqual(data['still_failing'], 1)

    def test_retry_all_empty_is_ok(self):
        """No failures → retried=0, still_failing=0."""
        self.client_http.force_login(self.fin_user)
        r = self.client_http.post('/api/qbo/sync-failures/retry-all/',
                                  content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['retried'], 0)
        self.assertEqual(data['still_failing'], 0)
