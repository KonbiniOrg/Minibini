from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from apps.qbo.models import QBOConnection
from apps.qbo.services import QBOService


class QBOServiceConnectionTest(TestCase):
    """Test QBOService connection management."""

    def setUp(self):
        now = timezone.now()
        self.connection = QBOConnection.objects.create(
            realm_id='123456',
            access_token='valid_token',
            refresh_token='valid_refresh',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )

    def test_get_active_connection(self):
        """get_active_connection returns the active QBO connection."""
        conn = QBOService.get_active_connection()
        self.assertEqual(conn.realm_id, '123456')

    def test_get_active_connection_none_when_inactive(self):
        """get_active_connection returns None when no active connection."""
        self.connection.is_active = False
        self.connection.save()
        self.assertIsNone(QBOService.get_active_connection())

    def test_get_active_connection_none_when_empty(self):
        """get_active_connection returns None when no connections exist."""
        QBOConnection.objects.all().delete()
        self.assertIsNone(QBOService.get_active_connection())


class QBOServiceSyncLogTest(TestCase):
    """Test QBOService sync logging."""

    def test_log_sync_success(self):
        """log_sync creates a success log entry."""
        from apps.qbo.models import QBOSyncLog
        QBOService.log_sync(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='99',
            action='create',
            status='success',
        )
        log = QBOSyncLog.objects.get(entity_id=42)
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '99')

    def test_log_sync_failure(self):
        """log_sync creates a failure log entry with error message."""
        from apps.qbo.models import QBOSyncLog
        QBOService.log_sync(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='',
            action='create',
            status='failed',
            error_message='Auth expired',
        )
        log = QBOSyncLog.objects.get(entity_id=42)
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.error_message, 'Auth expired')
