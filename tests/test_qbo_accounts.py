from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.qbo.services import QBOAccountsService

User = get_user_model()


class QBOAccountsServiceTest(TestCase):
    """Test pulling chart of accounts from QBO."""

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_income_items(self, mock_get_client):
        """Returns Service and NonInventory Items from QBO."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_item_1 = MagicMock()
        mock_item_1.Id = '1'
        mock_item_1.Name = 'CNC Machining'
        mock_item_1.Type = 'Service'

        mock_item_2 = MagicMock()
        mock_item_2.Id = '2'
        mock_item_2.Name = 'Materials Sales'
        mock_item_2.Type = 'NonInventory'

        with patch('quickbooks.objects.item.Item.filter',
                   return_value=[mock_item_1, mock_item_2]):
            items = QBOAccountsService.get_income_items()

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], '1')
        self.assertEqual(items[0]['name'], 'CNC Machining')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_expense_accounts(self, mock_get_client):
        """Returns expense and COGS accounts from QBO."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_account = MagicMock()
        mock_account.Id = '10'
        mock_account.Name = 'Shop Supplies'
        mock_account.AccountType = 'Expense'
        mock_account.AccountSubType = 'SuppliesMaterials'

        with patch('quickbooks.objects.account.Account.filter',
                   return_value=[mock_account]):
            accounts = QBOAccountsService.get_expense_accounts()

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['name'], 'Shop Supplies')

    def test_raises_without_connection(self):
        """Raises ValueError if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOAccountsService.get_income_items()


class QBOAccountsEndpointTest(TestCase):
    """Test the /api/qbo/accounts/ endpoint."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    @patch('apps.qbo.views.QBOAccountsService')
    def test_accounts_endpoint_returns_both_types(self, mock_service):
        """Endpoint returns income and expense accounts."""
        mock_service.get_income_items.return_value = [
            {'id': '1', 'name': 'CNC Machining', 'type': 'Service'}
        ]
        mock_service.get_expense_accounts.return_value = [
            {'id': '10', 'name': 'Supplies', 'type': 'Expense', 'sub_type': 'SuppliesMaterials'}
        ]

        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/accounts/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('income_items', data)
        self.assertIn('expense_accounts', data)

    def test_accounts_endpoint_requires_permission(self):
        """Endpoint requires can_manage_config."""
        worker = User.objects.create_user(username='worker', password='testpass')
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/api/qbo/accounts/')
        self.assertEqual(response.status_code, 403)
