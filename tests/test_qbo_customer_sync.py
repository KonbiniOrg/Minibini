from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOCustomerSyncService


class CustomerSyncTest(TestCase):
    """Test syncing a Business to QBO as a Customer."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@acme.com',
            mobile_number='555-5678',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp',
            business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_creates_qbo_record(self, mock_get_client):
        """push_customer creates a Customer in QBO and stores the ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '42'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            result = QBOCustomerSyncService.push_customer(self.business)

        self.business.refresh_from_db()
        self.assertEqual(self.business.qbo_customer_id, '42')
        self.assertEqual(result, '42')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_skips_if_already_synced(self, mock_get_client):
        """push_customer returns existing ID if already synced."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        result = QBOCustomerSyncService.push_customer(self.business)
        self.assertEqual(result, '42')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_logs_success(self, mock_get_client):
        """push_customer creates a sync log on success."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '42'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            QBOCustomerSyncService.push_customer(self.business)

        log = QBOSyncLog.objects.get(entity_type='customer')
        self.assertEqual(log.entity_id, self.business.pk)
        self.assertEqual(log.qbo_entity_id, '42')
        self.assertEqual(log.status, 'success')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_logs_failure(self, mock_get_client):
        """push_customer logs failure and raises on API error."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.save = MagicMock(side_effect=Exception('QBO API error'))

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            with self.assertRaises(Exception):
                QBOCustomerSyncService.push_customer(self.business)

        log = QBOSyncLog.objects.get(entity_type='customer')
        self.assertEqual(log.status, 'failed')
        self.assertIn('QBO API error', log.error_message)

    def test_push_customer_raises_without_connection(self):
        """push_customer raises if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOCustomerSyncService.push_customer(self.business)

    def test_build_customer_fields(self):
        """_build_customer maps Business/Contact fields correctly."""
        customer = QBOCustomerSyncService._build_customer(self.business)
        self.assertEqual(customer.CompanyName, 'Acme Corp')
        self.assertEqual(customer.DisplayName, 'Acme Corp')
        self.assertEqual(customer.PrimaryPhone.FreeFormNumber, '555-1234')
        self.assertEqual(customer.PrimaryEmailAddr.Address, 'john@acme.com')
