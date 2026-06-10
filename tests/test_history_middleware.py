from django.test import TestCase
from apps.core.models import CrmHistory
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User
from apps.contacts.models import Contact


class HistoryMiddlewareAPITest(BaseTestCase):
    """Test history tracking through the full request cycle via API."""

    def setUp(self):
        super().setUp()
        self.api_client = APIClient()
        self.user = User.objects.get(username='admin')
        self.api_client.force_authenticate(user=self.user)

    def test_api_update_creates_audit_entry(self):
        """PATCH via API creates a history entry with the request user."""
        contact = Contact.objects.first()
        old_name = contact.first_name
        response = self.api_client.patch(
            f'/api/contacts/{contact.pk}/',
            {'first_name': 'UpdatedViaAPI'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk, entry_type='audit',
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.changes['first_name']['old'], old_name)
        self.assertEqual(entry.changes['first_name']['new'], 'UpdatedViaAPI')
        self.assertEqual(entry.user, self.user)

    def test_no_change_no_entry(self):
        """Saving without actual field changes creates no history entry."""
        contact = Contact.objects.first()
        # PATCH with same value
        response = self.api_client.patch(
            f'/api/contacts/{contact.pk}/',
            {'first_name': contact.first_name},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk,
        )
        self.assertEqual(entries.count(), 0)

    def test_multiple_field_changes_single_entry(self):
        """Changing multiple fields creates one entry with all changes."""
        contact = Contact.objects.first()
        response = self.api_client.patch(
            f'/api/contacts/{contact.pk}/',
            {'first_name': 'NewFirst', 'last_name': 'NewLast'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk,
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertIn('first_name', entry.changes)
        self.assertIn('last_name', entry.changes)

    def test_create_new_object_creates_entry(self):
        """Creating a new tracked object via API creates an audit entry."""
        response = self.api_client.post(
            '/api/contacts/',
            {'first_name': 'Brand', 'last_name': 'New', 'email': 'new@test.com',
             'mobile_number': '555-0199'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        new_id = response.data['contact_id']
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=new_id,
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.entry_type, 'audit')
        self.assertTrue(entry.changes.get('_created'))
        self.assertEqual(entry.text, '')

    def test_entry_user_is_request_user(self):
        """History entries record the authenticated user from the request."""
        contact = Contact.objects.first()
        self.api_client.patch(
            f'/api/contacts/{contact.pk}/',
            {'first_name': 'TestUser'},
            format='json',
        )
        entry = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk,
        ).first()
        self.assertEqual(entry.user, self.user)


class HistoryDirectSaveTest(BaseTestCase):
    """Test history tracking for direct .save() calls outside requests."""

    def test_direct_save_creates_entry_without_user(self):
        """Direct .save() outside a request still creates an entry, but with user=None."""
        contact = Contact.objects.first()
        old_name = contact.first_name
        contact.first_name = 'DirectChange'
        contact.save()
        entries = CrmHistory.objects.filter(
            object_type='contact', object_id=contact.pk,
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertIsNone(entry.user)
        self.assertEqual(entry.changes['first_name']['old'], old_name)
        self.assertEqual(entry.changes['first_name']['new'], 'DirectChange')
