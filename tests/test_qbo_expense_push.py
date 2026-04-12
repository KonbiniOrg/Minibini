from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.qbo.services import QBOExpenseSyncService

User = get_user_model()


class GetPaymentAccountsTest(TestCase):
    """QBOExpenseSyncService.get_payment_accounts pulls Bank/CC/OCA accounts."""

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_payment_accounts_returns_enabled_bank_cc_and_oca(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def make_account(id_, name, acct_type):
            a = MagicMock()
            a.Id = id_
            a.Name = name
            a.AccountType = acct_type
            return a

        fake_bank = [
            make_account('42', 'BoA Business Checking', 'Bank'),
            make_account('43', 'BoA Savings', 'Bank'),
        ]
        fake_cc = [make_account('57', 'Amex Business', 'Credit Card')]
        fake_oca = [make_account('89', 'Petty Cash', 'Other Current Asset')]

        with patch('quickbooks.objects.account.Account.filter') as mock_filter:
            mock_filter.side_effect = lambda AccountType, Active, qb: {
                'Bank': fake_bank,
                'Credit Card': fake_cc,
                'Other Current Asset': fake_oca,
            }[AccountType]
            result = QBOExpenseSyncService.get_payment_accounts()

        ids = {a['qbo_account_id'] for a in result}
        self.assertEqual(ids, {'42', '43', '57', '89'})
        by_id = {a['qbo_account_id']: a for a in result}
        self.assertEqual(by_id['42']['account_type'], 'Bank')
        self.assertEqual(by_id['42']['display_name'], 'BoA Business Checking')
        self.assertEqual(by_id['57']['account_type'], 'Credit Card')
        self.assertEqual(by_id['89']['account_type'], 'Other Current Asset')

    def test_get_payment_accounts_raises_without_connection(self):
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.get_payment_accounts()


class PaymentAccountsEndpointTest(TestCase):
    """GET /api/qbo/payment-accounts/ — wraps QBOExpenseSyncService."""

    def setUp(self):
        self.client_http = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_config', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    def test_requires_authentication(self):
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertIn(r.status_code, (401, 403))

    def test_requires_can_manage_config(self):
        unpriv = User.objects.create_user(username='worker', password='testpass')
        self.client_http.force_login(unpriv)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 403)

    @patch('apps.qbo.services.QBOExpenseSyncService.get_payment_accounts')
    def test_returns_service_payload(self, mock_get):
        mock_get.return_value = [
            {'qbo_account_id': '42', 'display_name': 'BoA Checking', 'account_type': 'Bank'},
        ]
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {
            'payment_accounts': [
                {'qbo_account_id': '42', 'display_name': 'BoA Checking', 'account_type': 'Bank'},
            ]
        })

    @patch('apps.qbo.services.QBOExpenseSyncService.get_payment_accounts')
    def test_returns_400_when_not_connected(self, mock_get):
        mock_get.side_effect = ValueError('No active QBO connection')
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {'error': 'No active QBO connection'})
