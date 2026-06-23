"""Tests for QBOSyncLog.triggered_by auto-attribution from request context."""
from django.test import TestCase

from apps.core.history import HistoryContext, set_history_context
from apps.core.models import User
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOService


class SyncLogAttributionTest(TestCase):
    """QBOService.log_sync sets triggered_by from the active HistoryContext."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testsyncer', password='pw', first_name='Test', last_name='Syncer',
        )

    def tearDown(self):
        set_history_context(None)

    def test_triggered_by_set_from_context(self):
        """With a HistoryContext holding a user, log_sync records that user."""
        set_history_context(HistoryContext(user=self.user))

        log = QBOService.log_sync('expense', 1, 'Purchase', 'q1', 'create', 'success')

        log.refresh_from_db()
        self.assertEqual(log.triggered_by, self.user)

    def test_triggered_by_none_without_context(self):
        """With no HistoryContext, triggered_by is None."""
        # Ensure no context is set (setUp sets nothing; tearDown resets)
        log = QBOService.log_sync('expense', 2, 'Purchase', 'q2', 'create', 'success')

        log.refresh_from_db()
        self.assertIsNone(log.triggered_by)

    def test_explicit_triggered_by_overrides_context(self):
        """An explicit triggered_by= argument overrides the context user."""
        other_user = User.objects.create_user(
            username='otheruser', password='pw',
        )
        set_history_context(HistoryContext(user=self.user))

        log = QBOService.log_sync(
            'expense', 3, 'Purchase', 'q3', 'create', 'success',
            triggered_by=other_user,
        )

        log.refresh_from_db()
        self.assertEqual(log.triggered_by, other_user)

    def test_explicit_triggered_by_none_falls_back_to_context(self):
        """Passing triggered_by=None (the default) falls back to the context user —
        `None` means 'use the request context', not 'force no attribution'. There
        is no path that needs to force-null over a present context."""
        set_history_context(HistoryContext(user=self.user))

        # triggered_by=None (the default) should still use context
        log = QBOService.log_sync(
            'expense', 4, 'Purchase', 'q4', 'create', 'success',
            triggered_by=None,
        )

        log.refresh_from_db()
        self.assertEqual(log.triggered_by, self.user)
