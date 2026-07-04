"""Tests for QBOService.save_and_log helper."""
from unittest.mock import MagicMock, patch, call

from django.test import TestCase

from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOService


class SaveAndLogSuccessTest(TestCase):
    """save_and_log happy path: saves the object, writes a success log, returns str(Id)."""

    def test_returns_str_of_id(self):
        qbo_obj = MagicMock()
        qbo_obj.save = MagicMock()
        qbo_obj.Id = 99

        client = MagicMock()

        with patch.object(QBOService, 'log_sync') as mock_log:
            result = QBOService.save_and_log(
                qbo_obj, client,
                entity_type='customer',
                qbo_entity_type='Customer',
                entity_id=42,
            )

        self.assertEqual(result, '99')

    def test_calls_save_with_client(self):
        qbo_obj = MagicMock()
        qbo_obj.Id = '55'
        client = MagicMock()

        with patch.object(QBOService, 'log_sync'):
            QBOService.save_and_log(
                qbo_obj, client,
                entity_type='vendor',
                qbo_entity_type='Vendor',
                entity_id=7,
            )

        qbo_obj.save.assert_called_once_with(qb=client)

    def test_writes_success_log_row(self):
        qbo_obj = MagicMock()
        qbo_obj.Id = '42'

        QBOService.save_and_log(
            qbo_obj, MagicMock(),
            entity_type='customer',
            qbo_entity_type='Customer',
            entity_id=10,
        )

        log = QBOSyncLog.objects.get(entity_type='customer', entity_id=10)
        self.assertEqual(log.qbo_entity_id, '42')
        self.assertEqual(log.qbo_entity_type, 'Customer')
        self.assertEqual(log.action, 'create')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.error_message, '')

    def test_default_action_is_create(self):
        qbo_obj = MagicMock()
        qbo_obj.Id = '1'

        QBOService.save_and_log(
            qbo_obj, MagicMock(),
            entity_type='vendor',
            qbo_entity_type='Vendor',
            entity_id=5,
        )

        log = QBOSyncLog.objects.get(entity_type='vendor', entity_id=5)
        self.assertEqual(log.action, 'create')

    def test_update_action_is_recorded(self):
        qbo_obj = MagicMock()
        qbo_obj.Id = '2'

        QBOService.save_and_log(
            qbo_obj, MagicMock(),
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=20,
            action='update',
        )

        log = QBOSyncLog.objects.get(entity_type='expense', entity_id=20)
        self.assertEqual(log.action, 'update')
        self.assertEqual(log.status, 'success')


class SaveAndLogFailureTest(TestCase):
    """save_and_log failure path: writes a failed log row and re-raises."""

    def test_reraises_exception(self):
        qbo_obj = MagicMock()
        qbo_obj.save = MagicMock(side_effect=RuntimeError('QBO API down'))
        client = MagicMock()

        with self.assertRaises(RuntimeError):
            QBOService.save_and_log(
                qbo_obj, client,
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=99,
            )

    def test_writes_failed_log_row_with_empty_qbo_entity_id(self):
        qbo_obj = MagicMock()
        qbo_obj.save = MagicMock(side_effect=RuntimeError('Network timeout'))

        try:
            QBOService.save_and_log(
                qbo_obj, MagicMock(),
                entity_type='bill',
                qbo_entity_type='Bill',
                entity_id=99,
            )
        except RuntimeError:
            pass

        log = QBOSyncLog.objects.get(entity_type='bill', entity_id=99)
        self.assertEqual(log.qbo_entity_id, '')
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.error_message, 'Network timeout')

    def test_failed_log_row_records_correct_fields(self):
        qbo_obj = MagicMock()
        qbo_obj.save = MagicMock(side_effect=ValueError('auth error'))

        try:
            QBOService.save_and_log(
                qbo_obj, MagicMock(),
                entity_type='expense',
                qbo_entity_type='Purchase',
                entity_id=77,
                action='update',
            )
        except ValueError:
            pass

        log = QBOSyncLog.objects.get(entity_type='expense', entity_id=77)
        self.assertEqual(log.qbo_entity_type, 'Purchase')
        self.assertEqual(log.action, 'update')
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.qbo_entity_id, '')
        self.assertIn('auth error', log.error_message)

    def test_no_success_log_written_on_failure(self):
        qbo_obj = MagicMock()
        qbo_obj.save = MagicMock(side_effect=RuntimeError('boom'))

        try:
            QBOService.save_and_log(
                qbo_obj, MagicMock(),
                entity_type='customer',
                qbo_entity_type='Customer',
                entity_id=55,
            )
        except RuntimeError:
            pass

        logs = QBOSyncLog.objects.filter(entity_type='customer', entity_id=55)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().status, 'failed')
