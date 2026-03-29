from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from unittest.mock import patch, MagicMock
from apps.qbo.models import QBOConnection, QBOSyncLog
from apps.contacts.models import Business

User = get_user_model()


class QBOConnectionModelTest(TestCase):
    """Test QBOConnection model creation and methods."""

    def test_create_connection(self):
        """Can create a QBO connection record."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='1234567890',
            access_token='test_access_token',
            refresh_token='test_refresh_token',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertEqual(conn.realm_id, '1234567890')
        self.assertTrue(conn.is_active)

    def test_is_access_token_expired(self):
        """is_access_token_expired returns True when token is past expiry."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now - timezone.timedelta(minutes=5),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertTrue(conn.is_access_token_expired)

    def test_is_access_token_not_expired(self):
        """is_access_token_expired returns False when token is still valid."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(minutes=30),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertFalse(conn.is_access_token_expired)

    def test_is_refresh_token_expiring_soon(self):
        """is_refresh_token_expiring_soon returns True within 7 days of expiry."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=5),
            connected_at=now,
        )
        self.assertTrue(conn.is_refresh_token_expiring_soon)

    def test_str_representation(self):
        """String representation includes realm_id and status."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertIn('123', str(conn))


class QBOSyncLogModelTest(TestCase):
    """Test QBOSyncLog model."""

    def test_create_sync_log(self):
        """Can create a sync log entry."""
        log = QBOSyncLog.objects.create(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='99',
            action='create',
            status='success',
        )
        self.assertEqual(log.entity_type, 'customer')
        self.assertEqual(log.status, 'success')
        self.assertIsNotNone(log.synced_at)

    def test_create_failed_sync_log(self):
        """Can create a failed sync log with error message."""
        log = QBOSyncLog.objects.create(
            entity_type='invoice',
            entity_id=10,
            qbo_entity_type='Invoice',
            qbo_entity_id='',
            action='create',
            status='failed',
            error_message='Authentication expired',
        )
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.error_message, 'Authentication expired')


class BusinessQBOFieldsTest(TestCase):
    """Test QBO ID fields on Business model."""

    def _create_business(self, name='Test Corp', **kwargs):
        """Helper: create a Business with required Contact."""
        from apps.contacts.models import Contact
        contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', mobile_number='555-0000',
        )
        return Business.objects.create(
            business_name=name, default_contact=contact, **kwargs
        )

    def test_business_has_qbo_customer_id(self):
        """Business model has qbo_customer_id field, blank by default."""
        biz = self._create_business()
        self.assertEqual(biz.qbo_customer_id, '')

    def test_business_has_qbo_vendor_id(self):
        """Business model has qbo_vendor_id field, blank by default."""
        biz = self._create_business()
        self.assertEqual(biz.qbo_vendor_id, '')

    def test_business_can_be_both_customer_and_vendor(self):
        """A business can have both QBO customer and vendor IDs."""
        biz = self._create_business()
        biz.qbo_customer_id = '100'
        biz.qbo_vendor_id = '200'
        biz.save()
        biz.refresh_from_db()
        self.assertEqual(biz.qbo_customer_id, '100')
        self.assertEqual(biz.qbo_vendor_id, '200')


class QBOOAuthFlowTest(TestCase):
    """Test the OAuth connection flow API endpoints."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.worker = User.objects.create_user(username='worker', password='testpass')

    def test_connect_url_requires_auth(self):
        """QBO connect endpoint requires authentication."""
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 302)  # redirect to login

    def test_connect_url_requires_can_manage_config(self):
        """QBO connect endpoint requires can_manage_config permission."""
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 403)

    @patch('apps.qbo.views.AuthClient')
    def test_connect_redirects_to_intuit(self, mock_auth_class):
        """QBO connect endpoint redirects to Intuit authorization URL."""
        mock_auth = MagicMock()
        mock_auth.get_authorization_url.return_value = 'https://intuit.com/oauth?state=123'
        mock_auth.state_token = 'mocked_state'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('intuit.com', response.url)

    def test_status_returns_not_connected(self):
        """Status endpoint returns not_connected when no connection exists."""
        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/status/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'not_connected')

    def test_status_returns_connected(self):
        """Status endpoint returns connected when active connection exists."""
        now = timezone.now()
        QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/status/')
        data = response.json()
        self.assertEqual(data['status'], 'connected')
        self.assertEqual(data['realm_id'], '123')

    @patch('apps.qbo.views.AuthClient')
    def test_callback_creates_connection(self, mock_auth_class):
        """OAuth callback exchanges code for tokens and creates QBOConnection."""
        mock_auth = MagicMock()
        mock_auth.access_token = 'new_access_token'
        mock_auth.refresh_token = 'new_refresh_token'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        # Set the CSRF state token in session (normally set by connect view)
        session = self.client.session
        session['qbo_csrf_token'] = 'test_state'
        session.save()

        response = self.client.get('/api/qbo/callback/', {
            'code': 'auth_code_123',
            'realmId': '9876543210',
            'state': 'test_state',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/#/settings', response.url)

        conn = QBOConnection.objects.get(is_active=True)
        self.assertEqual(conn.realm_id, '9876543210')
        self.assertEqual(conn.access_token, 'new_access_token')

    @patch('apps.qbo.views.AuthClient')
    def test_callback_deactivates_prior_connections(self, mock_auth_class):
        """OAuth callback deactivates any existing active connections."""
        now = timezone.now()
        old_conn = QBOConnection.objects.create(
            realm_id='old_realm',
            access_token='old_tok',
            refresh_token='old_ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )

        mock_auth = MagicMock()
        mock_auth.access_token = 'new_tok'
        mock_auth.refresh_token = 'new_ref'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        session = self.client.session
        session['qbo_csrf_token'] = 'test_state'
        session.save()

        self.client.get('/api/qbo/callback/', {
            'code': 'code', 'realmId': 'new_realm', 'state': 'test_state',
        })

        old_conn.refresh_from_db()
        self.assertFalse(old_conn.is_active)
        self.assertEqual(QBOConnection.objects.filter(is_active=True).count(), 1)

    def test_callback_rejects_invalid_state(self):
        """OAuth callback rejects requests with invalid CSRF state token."""
        self.client.login(username='admin', password='testpass')
        session = self.client.session
        session['qbo_csrf_token'] = 'correct_state'
        session.save()

        response = self.client.get('/api/qbo/callback/', {
            'code': 'auth_code', 'realmId': '123', 'state': 'wrong_state',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(QBOConnection.objects.count(), 0)

    def test_disconnect_deactivates_connection(self):
        """Disconnect endpoint deactivates the active connection."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.client.login(username='admin', password='testpass')
        response = self.client.post('/api/qbo/disconnect/')
        self.assertEqual(response.status_code, 200)
        conn.refresh_from_db()
        self.assertFalse(conn.is_active)
