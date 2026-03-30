from unittest.mock import patch, MagicMock
from django.core.exceptions import ValidationError
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


class ContactQBOCustomerIdConstraintTest(TestCase):
    """Test that Contact can't have both business and qbo_customer_id."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Solo',
            email='jane@solo.com', mobile_number='555-0001',
        )

    def test_contact_can_have_qbo_customer_id_without_business(self):
        """Individual contact can store a QBO customer ID."""
        self.contact.qbo_customer_id = '99'
        self.contact.clean()
        self.contact.save()
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.qbo_customer_id, '99')

    def test_contact_qbo_customer_id_defaults_to_null(self):
        """New contact has null qbo_customer_id."""
        self.assertIsNone(self.contact.qbo_customer_id)

    def test_contact_with_business_cannot_have_qbo_customer_id(self):
        """Contact with a business cannot also have qbo_customer_id."""
        business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = business
        self.contact.qbo_customer_id = '99'
        with self.assertRaises(ValidationError):
            self.contact.clean()

    def test_contact_with_business_and_no_qbo_id_is_valid(self):
        """Contact with business but no qbo_customer_id is fine."""
        business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = business
        self.contact.save()
        self.contact.clean()  # should not raise


class IndividualContactCustomerSyncTest(TestCase):
    """Test syncing an individual Contact (no business) to QBO as a Customer."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Solo',
            email='jane@solo.com', mobile_number='555-0001',
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_contact_creates_qbo_customer(self, mock_get_client):
        """push_contact_as_customer creates a QBO customer for an individual."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '77'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_contact_customer',
                   return_value=mock_customer):
            result = QBOCustomerSyncService.push_contact_as_customer(self.contact)

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.qbo_customer_id, '77')
        self.assertEqual(result, '77')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_contact_skips_if_already_synced(self, mock_get_client):
        """push_contact_as_customer returns existing ID if already synced."""
        self.contact.qbo_customer_id = '77'
        self.contact.save()

        result = QBOCustomerSyncService.push_contact_as_customer(self.contact)
        self.assertEqual(result, '77')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_contact_logs_success(self, mock_get_client):
        """push_contact_as_customer logs sync success."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '77'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_contact_customer',
                   return_value=mock_customer):
            QBOCustomerSyncService.push_contact_as_customer(self.contact)

        log = QBOSyncLog.objects.get(entity_type='contact_customer')
        self.assertEqual(log.qbo_entity_id, '77')
        self.assertEqual(log.status, 'success')

    def test_push_contact_raises_without_connection(self):
        """push_contact_as_customer raises if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOCustomerSyncService.push_contact_as_customer(self.contact)

    def test_build_contact_customer_uses_name(self):
        """_build_contact_customer uses contact name, not company."""
        customer = QBOCustomerSyncService._build_contact_customer(self.contact)
        self.assertEqual(customer.DisplayName, 'Jane Solo')
        self.assertFalse(hasattr(customer, 'CompanyName') and customer.CompanyName)
        self.assertEqual(customer.PrimaryEmailAddr.Address, 'jane@solo.com')
