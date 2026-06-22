from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense, Reimbursement

User = get_user_model()


def _seed_payment_accounts():
    Configuration.objects.update_or_create(
        key='qbo_payment_accounts',
        defaults={'value': (
            '[{"qbo_account_id": "42", "display_name": "BoA Checking", "account_type": "Bank"}]'
        )},
    )


class ReimbursementCreateEndpointTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.e1 = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('47.50'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )

    def test_worker_cannot_create_batch(self):
        self.client_http.force_login(self.worker)
        r = self.client_http.post(
            '/api/reimbursements/',
            {
                'purchased_by': self.worker.pk,
                'expense_ids': [self.e1.pk],
                'paid_on': '2026-04-11',
                'payment_account_id': '42',
                'reference_number': '',
                'notes': '',
            },
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_admin_creates_batch(self, mock_push):
        mock_push.return_value = '9100'
        self.client_http.force_login(self.admin)
        r = self.client_http.post(
            '/api/reimbursements/',
            {
                'purchased_by': self.worker.pk,
                'expense_ids': [self.e1.pk],
                'paid_on': '2026-04-11',
                'payment_account_id': '42',
                'reference_number': '1234',
                'notes': '',
            },
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        batch = Reimbursement.objects.get()
        self.assertEqual(batch.qbo_sync_status, Reimbursement.SYNC_SYNCED)
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.status, Expense.STATUS_REIMBURSED)


class ReimbursementListFilterTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.client_http = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.worker_a = User.objects.create_user(username='a', password='testpass')
        self.worker_b = User.objects.create_user(username='b', password='testpass')
        self.b_a = Reimbursement.objects.create(
            purchased_by=self.worker_a,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )
        self.b_b = Reimbursement.objects.create(
            purchased_by=self.worker_b,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )

    def test_filter_by_purchased_by(self):
        self.client_http.force_login(self.admin)
        r = self.client_http.get(f'/api/reimbursements/?purchased_by={self.worker_a.pk}')
        self.assertEqual(r.status_code, 200)
        ids = {row['id'] for row in r.json()['results']}
        self.assertEqual(ids, {self.b_a.pk})


class ReimbursementRetrySyncEndpointTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.client_http = Client()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_FAILED,
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
    def test_retry_sync_flips_to_synced(self, mock_push):
        mock_push.return_value = '9100'
        self.client_http.force_login(self.admin)
        r = self.client_http.post(f'/api/reimbursements/{self.batch.pk}/retry-sync/')
        self.assertEqual(r.status_code, 200, r.content)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qbo_sync_status, Reimbursement.SYNC_SYNCED)


class ReimbursementDeleteTwoPhaseTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            qbo_sync_status=Reimbursement.SYNC_SYNCED,
            qbo_id='9100',
        )
        Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('50.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=self.batch,
        )

    def test_first_delete_returns_impact_counts(self):
        self.client_http.force_login(self.admin)
        r = self.client_http.delete(f'/api/reimbursements/{self.batch.pk}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get('confirm_required'), True)
        self.assertEqual(body.get('impact', {}).get('expense_count'), 1)
        self.assertTrue(Reimbursement.objects.filter(pk=self.batch.pk).exists())

    @patch('apps.qbo.services.QBOExpenseSyncService.void_reimbursement')
    def test_confirmed_delete_unwinds(self, mock_void):
        self.client_http.force_login(self.admin)
        r = self.client_http.delete(
            f'/api/reimbursements/{self.batch.pk}/?confirm=true'
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('message', r.json())
        self.assertFalse(Reimbursement.objects.filter(pk=self.batch.pk).exists())
        mock_void.assert_called_once()


class OutstandingSummaryEndpointTest(TestCase):
    def setUp(self):
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.dana = User.objects.create_user(username='dana', password='testpass')
        self.carlos = User.objects.create_user(username='carlos', password='testpass')

        for amt in ('47.50', '62.00', '28.75'):
            Expense.objects.create(
                entered_by=self.dana, purchased_by=self.dana,
                amount=Decimal(amt), purchased_on=date(2026, 4, 5),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            )
        Expense.objects.create(
            entered_by=self.carlos, purchased_by=self.carlos,
            amount=Decimal('22.00'), purchased_on=date(2026, 4, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )

    def test_summary_returns_per_user_rollup(self):
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/reimbursements/outstanding-summary/')
        self.assertEqual(r.status_code, 200)
        rows = {row['purchased_by']: row for row in r.json()['users']}
        self.assertEqual(rows[self.dana.pk]['count'], 3)
        self.assertEqual(rows[self.dana.pk]['total'], '138.25')
        self.assertEqual(rows[self.carlos.pk]['count'], 1)
        self.assertEqual(rows[self.carlos.pk]['total'], '22.00')

    def test_summary_excludes_reimbursed_and_rejected(self):
        self.client_http.force_login(self.admin)
        # Flip one dana expense to reimbursed
        dana_exp = Expense.objects.filter(purchased_by=self.dana).first()
        dana_exp.status = Expense.STATUS_REIMBURSED
        dana_exp.save()
        r = self.client_http.get('/api/reimbursements/outstanding-summary/')
        rows = {row['purchased_by']: row for row in r.json()['users']}
        self.assertEqual(rows[self.dana.pk]['count'], 2)
