from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.services import QBODisplayNameService


class DisplayNameGenerationTest(TestCase):
    """Test QBO DisplayName generation for customer/vendor records."""

    def _create_business(self, name='Acme Corp', **kwargs):
        """Helper: create a Business with required Contact."""
        contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', mobile_number='555-0000',
        )
        return Business.objects.create(
            business_name=name, default_contact=contact, **kwargs
        )

    def test_first_record_uses_plain_name(self):
        """First QBO record for a business uses the business name as-is."""
        biz = self._create_business()
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp')

    def test_vendor_first_uses_plain_name(self):
        """If vendor is created first, it gets the plain name."""
        biz = self._create_business()
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp')

    def test_second_record_gets_suffix_customer(self):
        """If vendor exists, customer record gets (Customer) suffix."""
        biz = self._create_business(qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp (Customer)')

    def test_second_record_gets_suffix_vendor(self):
        """If customer exists, vendor record gets (Vendor) suffix."""
        biz = self._create_business(qbo_customer_id='100')
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp (Vendor)')

    def test_both_exist_customer_gets_suffix(self):
        """If both exist, customer still gets suffix (other role exists)."""
        biz = self._create_business(qbo_customer_id='100', qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp (Customer)')

    def test_both_exist_vendor_gets_suffix(self):
        """If both exist, vendor still gets suffix (other role exists)."""
        biz = self._create_business(qbo_customer_id='100', qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp (Vendor)')

    def test_long_name_truncated(self):
        """QBO DisplayName max is 500 chars. Suffix still fits."""
        biz = self._create_business(qbo_customer_id='100')
        # Simulate a long name at the service level (bypassing DB field length)
        biz.business_name = 'A' * 495
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertLessEqual(len(name), 500)
        self.assertTrue(name.endswith('(Vendor)'))
