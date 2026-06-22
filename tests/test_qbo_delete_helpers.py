"""Tests for QBOService.delete_and_log and QBOSyncService.run_delete helpers."""
from unittest.mock import MagicMock, patch, call

from django.test import TestCase, SimpleTestCase

from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOService, QBOSyncService
from quickbooks.exceptions import ObjectNotFoundException


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _FakeRecord:
    """Minimal stand-in for a model with QBO sync state."""
    def __init__(self):
        self.qbo_sync_status = 'synced'
        self.qbo_sync_error = ''

    def mark_failed(self, error):
        self.qbo_sync_status = 'sync_failed'
        self.qbo_sync_error = str(error)


# ---------------------------------------------------------------------------
# QBOService.delete_and_log — success
# ---------------------------------------------------------------------------

class DeleteAndLogSuccessTest(TestCase):
    """Happy path: SDK get+delete called, success log written, returns None."""

    def _make_sdk_class(self, qbo_id='42'):
        """Return a mock SDK class whose .get() returns a mock object."""
        mock_obj = MagicMock()
        sdk_class = MagicMock()
        sdk_class.get.return_value = mock_obj
        return sdk_class, mock_obj

    def test_calls_sdk_get_with_id_and_client(self):
        sdk_class, mock_obj = self._make_sdk_class()
        client = MagicMock()

        with patch.object(QBOService, 'log_sync'):
            QBOService.delete_and_log(
                sdk_class, '42', client,
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=10,
            )

        sdk_class.get.assert_called_once_with('42', qb=client)

    def test_calls_delete_on_fetched_object(self):
        sdk_class, mock_obj = self._make_sdk_class()
        client = MagicMock()

        with patch.object(QBOService, 'log_sync'):
            QBOService.delete_and_log(
                sdk_class, '42', client,
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=10,
            )

        mock_obj.delete.assert_called_once_with(qb=client)

    def test_returns_none_on_success(self):
        sdk_class, _ = self._make_sdk_class()

        with patch.object(QBOService, 'log_sync'):
            result = QBOService.delete_and_log(
                sdk_class, '42', MagicMock(),
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=10,
            )

        self.assertIsNone(result)

    def test_writes_success_log_row(self):
        sdk_class, _ = self._make_sdk_class()

        QBOService.delete_and_log(
            sdk_class, '42', MagicMock(),
            entity_type='bill',
            qbo_entity_type='Bill',
            entity_id=10,
        )

        log = QBOSyncLog.objects.get(entity_type='bill', entity_id=10)
        self.assertEqual(log.action, 'delete')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '42')
        self.assertEqual(log.qbo_entity_type, 'Bill')
        self.assertEqual(log.error_message, '')


# ---------------------------------------------------------------------------
# QBOService.delete_and_log — idempotent (not-found treated as success)
# ---------------------------------------------------------------------------

class DeleteAndLogIdempotentTest(TestCase):
    """Not-found from QBO should be treated as a successful delete."""

    def _not_found_exc(self):
        return ObjectNotFoundException('Object Not Found', error_code=610)

    def test_get_raises_not_found_is_treated_as_success(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = self._not_found_exc()

        # Should not raise
        QBOService.delete_and_log(
            sdk_class, '99', MagicMock(),
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=5,
        )

    def test_not_found_writes_success_log(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = self._not_found_exc()

        QBOService.delete_and_log(
            sdk_class, '99', MagicMock(),
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=5,
        )

        log = QBOSyncLog.objects.get(entity_type='expense', entity_id=5)
        self.assertEqual(log.action, 'delete')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '99')

    def test_not_found_returns_none(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = self._not_found_exc()

        result = QBOService.delete_and_log(
            sdk_class, '99', MagicMock(),
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=5,
        )

        self.assertIsNone(result)

    def test_delete_raises_not_found_is_treated_as_success(self):
        """If .delete() itself raises ObjectNotFoundException, still treat as success."""
        mock_obj = MagicMock()
        mock_obj.delete.side_effect = self._not_found_exc()
        sdk_class = MagicMock()
        sdk_class.get.return_value = mock_obj

        # Should not raise
        QBOService.delete_and_log(
            sdk_class, '77', MagicMock(),
            entity_type='bill',
            qbo_entity_type='Bill',
            entity_id=7,
        )

        log = QBOSyncLog.objects.get(entity_type='bill', entity_id=7)
        self.assertEqual(log.status, 'success')


# ---------------------------------------------------------------------------
# QBOService.delete_and_log — real failure (non-not-found)
# ---------------------------------------------------------------------------

class DeleteAndLogFailureTest(TestCase):
    """A real (non-not-found) error: write failed log and re-raise."""

    def test_reraises_non_not_found_exception(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = RuntimeError('network timeout')

        with self.assertRaises(RuntimeError):
            QBOService.delete_and_log(
                sdk_class, '33', MagicMock(),
                entity_type='vendor',
                qbo_entity_type='Vendor',
                entity_id=3,
            )

    def test_writes_failed_log_on_real_error(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = RuntimeError('connection refused')

        try:
            QBOService.delete_and_log(
                sdk_class, '33', MagicMock(),
                entity_type='vendor',
                qbo_entity_type='Vendor',
                entity_id=3,
            )
        except RuntimeError:
            pass

        log = QBOSyncLog.objects.get(entity_type='vendor', entity_id=3)
        self.assertEqual(log.action, 'delete')
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.qbo_entity_id, '')
        self.assertIn('connection refused', log.error_message)

    def test_failed_log_no_success_log_also_written(self):
        sdk_class = MagicMock()
        sdk_class.get.side_effect = ValueError('auth expired')

        try:
            QBOService.delete_and_log(
                sdk_class, '44', MagicMock(),
                entity_type='customer',
                qbo_entity_type='Customer',
                entity_id=9,
            )
        except ValueError:
            pass

        logs = QBOSyncLog.objects.filter(entity_type='customer', entity_id=9)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().status, 'failed')

    def test_qbo_non_not_found_exception_reraises(self):
        """A QuickbooksException with a non-610 error code should be treated as real failure."""
        from quickbooks.exceptions import QuickbooksException
        sdk_class = MagicMock()
        sdk_class.get.side_effect = QuickbooksException('Rate limit', error_code=429)

        with self.assertRaises(QuickbooksException):
            QBOService.delete_and_log(
                sdk_class, '55', MagicMock(),
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=11,
            )

        log = QBOSyncLog.objects.get(entity_type='bill', entity_id=11)
        self.assertEqual(log.status, 'failed')


# ---------------------------------------------------------------------------
# QBOSyncService.run_delete
# ---------------------------------------------------------------------------

class RunDeleteSuccessTest(SimpleTestCase):
    """run_delete success: returns None, record NOT marked failed."""

    def test_returns_none_on_success(self):
        rec = _FakeRecord()
        result = QBOSyncService.run_delete(rec, lambda: None)
        self.assertIsNone(result)

    def test_record_not_marked_failed_on_success(self):
        rec = _FakeRecord()
        QBOSyncService.run_delete(rec, lambda: None)
        self.assertEqual(rec.qbo_sync_status, 'synced')

    def test_delete_callable_called(self):
        rec = _FakeRecord()
        called = []
        def delete_callable():
            called.append(True)
        QBOSyncService.run_delete(rec, delete_callable)
        self.assertEqual(called, [True])


class RunDeleteFailureTest(SimpleTestCase):
    """run_delete failure: mark_failed called AND exception re-raised."""

    def test_reraises_exception(self):
        rec = _FakeRecord()
        def boom():
            raise ValueError('QBO delete failed')

        with self.assertRaises(ValueError):
            QBOSyncService.run_delete(rec, boom)

    def test_marks_record_failed(self):
        rec = _FakeRecord()
        def boom():
            raise ValueError('network error')

        try:
            QBOSyncService.run_delete(rec, boom)
        except ValueError:
            pass

        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'network error')

    def test_mark_failed_called_with_error(self):
        rec = _FakeRecord()
        err = RuntimeError('timeout')
        def boom():
            raise err

        mark_called_with = []
        original_mark_failed = rec.mark_failed
        def tracking_mark_failed(e):
            mark_called_with.append(e)
            original_mark_failed(e)
        rec.mark_failed = tracking_mark_failed

        try:
            QBOSyncService.run_delete(rec, boom)
        except RuntimeError:
            pass

        self.assertEqual(len(mark_called_with), 1)
        self.assertIs(mark_called_with[0], err)
