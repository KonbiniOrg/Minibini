from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.core.models import User, Configuration
from .base import FixtureTestCase


class UserModelFixtureTest(FixtureTestCase):
    """
    Test User model using fixture data loaded from unit_test_data.json
    """
    
    def test_user_exists_from_fixture(self):
        """Test that users from fixture data exist and have correct properties"""
        admin_user = User.objects.get(username="admin")
        self.assertEqual(admin_user.first_name, "Admin")
        self.assertEqual(admin_user.last_name, "User")
        self.assertEqual(admin_user.email, "admin@minibini.com")
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_staff)
        
        manager_user = User.objects.get(username="manager1")
        self.assertEqual(manager_user.first_name, "John")
        self.assertEqual(manager_user.last_name, "Manager")
        self.assertEqual(manager_user.email, "manager@minibini.com")
        self.assertFalse(manager_user.is_superuser)
        self.assertTrue(manager_user.is_staff)
        
        # Test new regular user
        public_user = User.objects.get(username="johnq")
        self.assertEqual(public_user.first_name, "John Q")
        self.assertEqual(public_user.last_name, "Public")
        self.assertEqual(public_user.email, "john.public@example.com")
        self.assertFalse(public_user.is_superuser)
        self.assertFalse(public_user.is_staff)
        self.assertTrue(public_user.is_active)
        
    def test_user_contact_relationships(self):
        """Test that user-contact relationships work correctly"""
        admin_user = User.objects.get(username="admin")
        self.assertIsNotNone(admin_user.contact)
        self.assertEqual(admin_user.contact.name, "John Doe")
        
        # Test new regular user has correct contact
        public_user = User.objects.get(username="johnq")
        self.assertIsNotNone(public_user.contact)
        self.assertEqual(public_user.contact.name, "John Q Public")
        self.assertEqual(public_user.contact.email, "john.public@example.com")
        
class ConfigurationModelFixtureTest(FixtureTestCase):
    """
    Test Configuration model using fixture data
    """

    def test_configurations_exist_from_fixture(self):
        """Test that configurations from fixture exist with correct data"""
        job_seq = Configuration.objects.get(key="job_number_sequence")
        self.assertEqual(job_seq.value, "JOB-{year}-{counter:04d}")

        # Estimates are not numbered via the service (they derive {job}-{ver}),
        # so there is no estimate_number_sequence key.

        invoice_seq = Configuration.objects.get(key="invoice_number_sequence")
        self.assertEqual(invoice_seq.value, "INV-{year}-{counter:04d}")

    def test_configuration_str_method_with_fixture_data(self):
        """Test configuration string representation with fixture data"""
        job_seq = Configuration.objects.get(key="job_number_sequence")
        self.assertEqual(str(job_seq), "job_number_sequence: JOB-{year}-{counter:04d}")

    def test_update_existing_configuration(self):
        """Test updating existing configuration from fixture data"""
        invoice_seq = Configuration.objects.get(key="invoice_number_sequence")
        original_value = invoice_seq.value

        invoice_seq.value = "INV-{year}-{month:02d}-{counter:04d}"
        invoice_seq.save()

        updated_config = Configuration.objects.get(key="invoice_number_sequence")
        self.assertNotEqual(updated_config.value, original_value)
        self.assertEqual(updated_config.value, "INV-{year}-{month:02d}-{counter:04d}")

    def test_create_new_configuration(self):
        """Test creating new configuration alongside existing fixture data"""
        new_config = Configuration.objects.create(
            key="email_settings",
            value="smtp.example.com"
        )
        self.assertEqual(new_config.key, "email_settings")
        self.assertEqual(new_config.value, "smtp.example.com")
        # Count will depend on how many fixture entries exist
        self.assertGreater(Configuration.objects.count(), 1)