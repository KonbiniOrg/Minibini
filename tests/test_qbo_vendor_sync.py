from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOVendorSyncService


class VendorSyncTest(TestCase):
    """Test syncing a Business to QBO as a Vendor."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@supply.com',
            mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co',
            business_phone='555-9999',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_creates_qbo_record(self, mock_get_client):
        """push_vendor creates a Vendor in QBO and stores the ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_vendor = MagicMock()
        mock_vendor.Id = '55'
        mock_vendor.save = MagicMock(return_value=mock_vendor)

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor',
                   return_value=mock_vendor):
            result = QBOVendorSyncService.push_vendor(self.business)

        self.business.refresh_from_db()
        self.assertEqual(self.business.qbo_vendor_id, '55')
        self.assertEqual(result, '55')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_skips_if_already_synced(self, mock_get_client):
        """push_vendor returns existing ID if already synced."""
        self.business.qbo_vendor_id = '55'
        self.business.save()

        result = QBOVendorSyncService.push_vendor(self.business)
        self.assertEqual(result, '55')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_gets_suffix_when_customer_exists(self, mock_get_client):
        """Vendor gets (Vendor) suffix if customer record already exists."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor') as mock_build:
            mock_vendor = MagicMock()
            mock_vendor.Id = '55'
            mock_vendor.save = MagicMock(return_value=mock_vendor)
            mock_build.return_value = mock_vendor

            QBOVendorSyncService.push_vendor(self.business)

            # Verify _build_vendor was called with the business
            mock_build.assert_called_once_with(self.business)

    def test_build_vendor_display_name_with_existing_customer(self):
        """_build_vendor uses suffixed DisplayName when customer exists."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        vendor = QBOVendorSyncService._build_vendor(self.business)
        self.assertEqual(vendor.DisplayName, 'Supply Co (Vendor)')
        self.assertEqual(vendor.CompanyName, 'Supply Co')

    def test_build_vendor_display_name_first_record(self):
        """_build_vendor uses plain name when no customer exists."""
        vendor = QBOVendorSyncService._build_vendor(self.business)
        self.assertEqual(vendor.DisplayName, 'Supply Co')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_logs_success(self, mock_get_client):
        """push_vendor creates a sync log on success."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_vendor = MagicMock()
        mock_vendor.Id = '55'
        mock_vendor.save = MagicMock(return_value=mock_vendor)

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor',
                   return_value=mock_vendor):
            QBOVendorSyncService.push_vendor(self.business)

        log = QBOSyncLog.objects.get(entity_type='vendor')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '55')
