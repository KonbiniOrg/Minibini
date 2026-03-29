from django.test import TestCase
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog
from apps.contacts.models import Business


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
