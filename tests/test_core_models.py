from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from apps.core.models import User, Configuration
from apps.contacts.models import Contact


class UserModelTest(TestCase):
    def setUp(self):
        self.group = Group.objects.create(
            name="Test Group"
        )
        
    def test_user_creation(self):
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123"
        )
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("testpassword123"))
        
    def test_user_with_group(self):
        user = User.objects.create_user(
            username="testuser"
        )
        user.groups.add(self.group)
        self.assertIn(self.group, user.groups.all())
        
    def test_user_str_method(self):
        user = User.objects.create_user(username="testuser")
        self.assertEqual(str(user), "testuser")
    
    def test_user_contact_unique_constraint(self):
        """Test that each Contact can be associated with at most one User"""
        # Create a contact
        contact = Contact.objects.create(
            first_name='John Doe',
            last_name='',
            email="john@example.com"
        )
        
        # Create first user with the contact - should work
        user1 = User.objects.create_user(
            username="user1",
            contact=contact
        )
        self.assertEqual(user1.contact, contact)
        
        # Try to create second user with same contact - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="user2", 
                    contact=contact
                )
        
        # Verify first user still exists and has the contact (after transaction rollback)
        user1.refresh_from_db()
        self.assertEqual(user1.contact, contact)
        
        # Test that users can exist without contacts (should still work)
        user3 = User.objects.create_user(username="user3")
        self.assertIsNone(user3.contact)
        
        # Test that multiple users can have no contact (null values are allowed)
        user4 = User.objects.create_user(username="user4")
        self.assertIsNone(user4.contact)


class GroupModelTest(TestCase):
    def test_group_creation(self):
        group = Group.objects.create(name="Manager")
        
        self.assertEqual(group.name, "Manager")
        self.assertEqual(str(group), "Manager")
        
    def test_group_str_method(self):
        group = Group.objects.create(name="Admin")
        self.assertEqual(str(group), "Admin")
        
    def test_user_group_assignment(self):
        group = Group.objects.create(name="Employee")
        user = User.objects.create_user(username="testuser")
        
        user.groups.add(group)
        self.assertIn(group, user.groups.all())
        self.assertIn(user, group.user_set.all())


class ConfigurationModelTest(TestCase):
    def test_configuration_creation(self):
        config = Configuration.objects.create(
            key="job_number_sequence",
            value="JOB-{year}-{counter:04d}"
        )
        self.assertEqual(config.key, "job_number_sequence")
        self.assertEqual(config.value, "JOB-{year}-{counter:04d}")

    def test_configuration_str_method(self):
        config = Configuration.objects.create(key="test_key", value="test_value")
        self.assertEqual(str(config), "test_key: test_value")

    def test_configuration_empty_value(self):
        config = Configuration.objects.create(key="empty_config", value="")
        self.assertEqual(config.key, "empty_config")
        self.assertEqual(config.value, "")

    def test_configuration_key_is_primary_key(self):
        """Test that key is the primary key and must be unique"""
        config1 = Configuration.objects.create(key="unique_key", value="value1")

        # Trying to create another config with same key should fail
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Configuration.objects.create(key="unique_key", value="value2")