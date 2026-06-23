import json
from django.test import TestCase
from apps.core.models import Configuration
from apps.qbo.services import QBOPaymentAccountService


class QBOPaymentAccountServiceTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
                {'qbo_account_id': '42', 'display_name': 'Visa', 'account_type': 'Credit Card'},
            ])},
        )

    def test_load_accounts_returns_parsed_list(self):
        accounts = QBOPaymentAccountService.load_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]['qbo_account_id'], '35')

    def test_load_accounts_empty_when_unset(self):
        Configuration.objects.filter(key='qbo_payment_accounts').delete()
        self.assertEqual(QBOPaymentAccountService.load_accounts(), [])

    def test_lookup_returns_matching_dict(self):
        acct = QBOPaymentAccountService.lookup('42')
        self.assertEqual(acct['account_type'], 'Credit Card')

    def test_lookup_unknown_raises(self):
        with self.assertRaises(ValueError):
            QBOPaymentAccountService.lookup('999')
