from django.test import TestCase
from tests.base import BaseTestCase
from apps.contacts.models import Contact


class HistoryDecoratorTest(BaseTestCase):
    def test_model_is_marked_as_tracked(self):
        self.assertTrue(getattr(Contact, '_history_tracked', False))

    def test_model_has_exclude_set(self):
        self.assertIsInstance(Contact._history_exclude, set)

    def test_post_init_creates_snapshot(self):
        contact = Contact.objects.first()
        self.assertTrue(hasattr(contact, '_history_original'))
        self.assertIn('first_name', contact._history_original)
        self.assertEqual(contact._history_original['first_name'], contact.first_name)

    def test_snapshot_excludes_excluded_fields(self):
        """Excluded fields are not in the snapshot."""
        contact = Contact.objects.first()
        for field in Contact._history_exclude:
            self.assertNotIn(field, contact._history_original)

    def test_new_instance_has_no_snapshot(self):
        """A brand new (unsaved) instance has _history_original = None."""
        contact = Contact(first_name='New', last_name='Person')
        self.assertIsNone(getattr(contact, '_history_original', 'missing'))
