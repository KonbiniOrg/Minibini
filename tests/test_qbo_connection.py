from django.test import TestCase
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog


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
