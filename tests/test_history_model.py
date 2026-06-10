from django.test import TestCase
from apps.core.models import JobHistory
from apps.core.history import record_history
from apps.core.models import User
from tests.base import BaseTestCase


class HistoryEntryModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')

    def test_create_audit_entry(self):
        entry = record_history(
            entry_type='audit',
            object_type='estimate',
            object_id=1,
            user=self.user,
            changes={'status': {'old': 'draft', 'new': 'open'}},
        )
        self.assertEqual(entry.entry_type, 'audit')
        self.assertEqual(entry.object_type, 'estimate')
        self.assertEqual(entry.object_id, 1)
        self.assertEqual(entry.user, self.user)
        self.assertIsNotNone(entry.timestamp)
        self.assertEqual(entry.changes['status']['old'], 'draft')
        self.assertEqual(entry.text, '')

    def test_create_action_entry(self):
        entry = record_history(
            entry_type='action',
            object_type='job',
            object_id=1,
            user=None,
            changes={
                'status': {'old': 'submitted', 'new': 'approved'},
                '_action': 'Estimate EST-2025-0001 accepted',
            },
        )
        self.assertEqual(entry.entry_type, 'action')
        self.assertEqual(entry.changes['_action'], 'Estimate EST-2025-0001 accepted')
        self.assertEqual(entry.text, '')
        self.assertIsNone(entry.user)

    def test_create_note_entry(self):
        entry = record_history(
            entry_type='note',
            object_type='job',
            object_id=1,
            user=self.user,
            text='Customer called to confirm delivery date.',
        )
        self.assertEqual(entry.entry_type, 'note')
        self.assertIsNone(entry.changes)
        self.assertEqual(entry.text, 'Customer called to confirm delivery date.')

    def test_ordering_newest_first(self):
        e1 = record_history(
            entry_type='audit', object_type='job', object_id=1,
            changes={'name': {'old': 'A', 'new': 'B'}},
        )
        e2 = record_history(
            entry_type='note', object_type='job', object_id=1,
            text='A note',
        )
        entries = list(JobHistory.objects.all())
        self.assertEqual(entries[0].pk, e2.pk)
        self.assertEqual(entries[1].pk, e1.pk)

    def test_entry_type_choices(self):
        valid_types = ['audit', 'action', 'note']
        for t in valid_types:
            entry = JobHistory(entry_type=t, object_type='job', object_id=1)
            entry.full_clean()  # should not raise


class SystemUserTest(BaseTestCase):
    def test_system_user_exists(self):
        system = User.objects.get(username='system')
        self.assertTrue(system.is_active)
        self.assertFalse(system.is_superuser)
        self.assertFalse(system.is_staff)
