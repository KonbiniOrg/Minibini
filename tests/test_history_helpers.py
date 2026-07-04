"""Tests for current_request_user() and record_action() helpers in apps/core/history.py."""
from unittest.mock import MagicMock

from apps.core.history import (
    HistoryContext,
    current_request_user,
    get_history_context,
    record_action,
    set_history_context,
)
from apps.core.models import User
from apps.purchasing.models import Bill
from tests.base import BaseTestCase


class CurrentRequestUserTest(BaseTestCase):
    """Unit tests for current_request_user()."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')

    def tearDown(self):
        set_history_context(None)
        super().tearDown()

    def test_returns_none_with_no_context(self):
        set_history_context(None)
        self.assertIsNone(current_request_user())

    def test_returns_user_from_context_user_attribute(self):
        ctx = HistoryContext(user=self.user)
        set_history_context(ctx)
        self.assertEqual(current_request_user(), self.user)

    def test_returns_user_from_request_on_context(self):
        """Mirrors middleware's flush-time resolution: prefers _request.user when authenticated."""
        ctx = HistoryContext()
        request = MagicMock()
        # Use a MagicMock for user so is_authenticated can be set freely
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        # But we want to verify the actual user object is returned, so
        # use the real user as the request user by assigning it via spec-less mock
        request.user = self.user
        # Patch is_authenticated via a wrapper: use the real user on a mock request
        # Since real User.is_authenticated is a property we can't assign, attach a
        # mock request where .user is a MagicMock whose is_authenticated is True
        # and pk matches self.user
        mock_req_user = MagicMock()
        mock_req_user.is_authenticated = True
        mock_req_user.pk = self.user.pk
        request.user = mock_req_user
        ctx._request = request
        set_history_context(ctx)
        result = current_request_user()
        self.assertEqual(result, mock_req_user)

    def test_request_user_takes_precedence_over_ctx_user(self):
        """_request.user wins over ctx.user when both are set."""
        other_user = User.objects.exclude(pk=self.user.pk).first()
        if other_user is None:
            other_user = User.objects.create_user(
                username='test_second_user', password='x'
            )
        ctx = HistoryContext(user=other_user)
        request = MagicMock()
        mock_req_user = MagicMock()
        mock_req_user.is_authenticated = True
        request.user = mock_req_user
        ctx._request = request
        set_history_context(ctx)
        # Should return the request user, not other_user from ctx
        self.assertEqual(current_request_user(), mock_req_user)

    def test_falls_back_to_ctx_user_when_request_user_unauthenticated(self):
        ctx = HistoryContext(user=self.user)
        request = MagicMock()
        request.user.is_authenticated = False
        ctx._request = request
        set_history_context(ctx)
        self.assertEqual(current_request_user(), self.user)

    def test_returns_none_when_request_user_is_none(self):
        ctx = HistoryContext()
        request = MagicMock()
        request.user = None
        ctx._request = request
        set_history_context(ctx)
        self.assertIsNone(current_request_user())


class RecordActionTest(BaseTestCase):
    """Integration tests for record_action() — writes real DB rows."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')
        self.bill = Bill.objects.first()
        if self.bill is None:
            self.fail('Fixture must contain at least one Bill')

    def tearDown(self):
        set_history_context(None)
        super().tearDown()

    def test_writes_action_entry_with_context_user(self):
        ctx = HistoryContext(user=self.user)
        set_history_context(ctx)
        entry = record_action('bill', self.bill.pk, 'X happened')
        self.assertEqual(entry.entry_type, 'action')
        self.assertEqual(entry.object_type, 'bill')
        self.assertEqual(entry.object_id, self.bill.pk)
        self.assertEqual(entry.changes, {'_action': 'X happened'})
        self.assertEqual(entry.user, self.user)

    def test_writes_action_entry_with_null_user_when_no_context(self):
        set_history_context(None)
        entry = record_action('bill', self.bill.pk, 'no context write')
        self.assertEqual(entry.entry_type, 'action')
        self.assertIsNone(entry.user)
        self.assertEqual(entry.changes, {'_action': 'no context write'})

    def test_explicit_user_overrides_context_user(self):
        other_user = User.objects.exclude(pk=self.user.pk).first()
        if other_user is None:
            other_user = User.objects.create_user(
                username='test_second_user_b', password='x'
            )
        ctx = HistoryContext(user=self.user)
        set_history_context(ctx)
        entry = record_action('bill', self.bill.pk, 'Y happened', user=other_user)
        self.assertEqual(entry.user, other_user)

    def test_action_persisted_to_db(self):
        """Entry created by record_action is actually saved to the DB."""
        from apps.core.models import PurchasingHistory
        set_history_context(None)
        entry = record_action('bill', self.bill.pk, 'persist check')
        fetched = PurchasingHistory.objects.get(pk=entry.pk)
        self.assertEqual(fetched.entry_type, 'action')
        self.assertEqual(fetched.changes, {'_action': 'persist check'})
