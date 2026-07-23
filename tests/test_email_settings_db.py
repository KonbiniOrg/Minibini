"""Per-tenant email settings: Configuration-first, env-settings fallback."""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.email_account import email_account, email_configured
from apps.core.models import Configuration, User
from apps.core.services import EmailService


DB_KEYS = {
    'email_imap_server': 'imap.tenant.com',
    'email_address': 'shop@tenant.com',
    'email_password': 'hunter2',
    'email_smtp_host': 'smtp.tenant.com',
    'email_smtp_port': '465',
}


class EmailAccountResolutionTest(TestCase):
    def _seed_db_keys(self):
        for k, v in DB_KEYS.items():
            Configuration.objects.create(key=k, value=v)

    def test_db_rows_win(self):
        self._seed_db_keys()
        acct = email_account()
        self.assertEqual(acct['imap_server'], 'imap.tenant.com')
        self.assertEqual(acct['address'], 'shop@tenant.com')
        self.assertEqual(acct['password'], 'hunter2')
        self.assertEqual(acct['smtp_host'], 'smtp.tenant.com')
        self.assertEqual(acct['smtp_port'], '465')

    @override_settings(EMAIL_IMAP_SERVER='imap.env.com',
                       EMAIL_HOST_USER='env@env.com',
                       EMAIL_HOST_PASSWORD='envpass',
                       EMAIL_HOST='smtp.env.com', EMAIL_PORT=587)
    def test_env_fallback_per_key(self):
        Configuration.objects.create(key='email_address', value='shop@tenant.com')
        acct = email_account()
        self.assertEqual(acct['address'], 'shop@tenant.com')   # DB
        self.assertEqual(acct['imap_server'], 'imap.env.com')  # env
        self.assertEqual(acct['password'], 'envpass')          # env
        self.assertEqual(acct['smtp_host'], 'smtp.env.com')
        self.assertEqual(acct['smtp_port'], '587')

    @override_settings(EMAIL_IMAP_SERVER=None, EMAIL_HOST_USER=None,
                       EMAIL_HOST_PASSWORD=None)
    def test_blank_when_neither(self):
        acct = email_account()
        self.assertEqual(acct['imap_server'], '')
        self.assertEqual(acct['address'], '')

    def test_email_configured_truth_table(self):
        with override_settings(EMAIL_IMAP_SERVER=None, EMAIL_HOST_USER=None,
                               EMAIL_HOST_PASSWORD=None):
            self.assertFalse(email_configured())
            Configuration.objects.create(key='email_imap_server', value='i')
            Configuration.objects.create(key='email_address', value='a@b.c')
            self.assertFalse(email_configured())  # password still missing
            Configuration.objects.create(key='email_password', value='p')
            self.assertTrue(email_configured())

    def test_email_service_reads_db_rows(self):
        self._seed_db_keys()
        svc = EmailService()
        self.assertEqual(svc.imap_server, 'imap.tenant.com')
        self.assertEqual(svc.email, 'shop@tenant.com')
        self.assertTrue(svc._validate_config())


class EmailVerifyEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='cfg', password='x', is_superuser=True)
        self.client.force_authenticate(user=self.user)
        for k, v in DB_KEYS.items():
            Configuration.objects.create(key=k, value=v)

    @patch('apps.api.templates_config.views.get_connection')
    @patch('apps.api.templates_config.views.MailBox')
    def test_verify_both_ok(self, MockMailBox, mock_get_conn):
        MockMailBox.return_value.login.return_value.__enter__ = MagicMock()
        MockMailBox.return_value.login.return_value.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        mock_get_conn.return_value = conn
        resp = self.client.post('/api/settings/email-verify/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['imap']['ok'])
        self.assertTrue(resp.data['smtp']['ok'])
        conn.open.assert_called_once()
        conn.close.assert_called_once()

    @patch('apps.api.templates_config.views.get_connection')
    @patch('apps.api.templates_config.views.MailBox')
    def test_verify_reports_failures_without_500(self, MockMailBox, mock_get_conn):
        MockMailBox.return_value.login.side_effect = Exception('bad creds')
        conn = MagicMock()
        conn.open.side_effect = Exception('smtp down')
        mock_get_conn.return_value = conn
        resp = self.client.post('/api/settings/email-verify/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['imap']['ok'])
        self.assertIn('bad creds', resp.data['imap']['error'])
        self.assertFalse(resp.data['smtp']['ok'])
        self.assertIn('smtp down', resp.data['smtp']['error'])
