from django.test import SimpleTestCase
from apps.qbo.services import QBOSyncService


class _FakeRecord:
    OP_CREATE = 'create'
    OP_UPDATE = 'update'
    OP_DELETE = 'delete'

    def __init__(self):
        self.qbo_id = ''
        self.qbo_sync_status = 'pending'
        self.qbo_sync_error = ''
        self.qbo_pending_op = ''

    def mark_synced(self, qbo_id):
        self.qbo_id = qbo_id
        self.qbo_sync_status = 'synced'
        self.qbo_sync_error = ''
        self.qbo_pending_op = ''

    def mark_failed(self, error, op=''):
        self.qbo_sync_status = 'sync_failed'
        self.qbo_sync_error = str(error)
        self.qbo_pending_op = op


class QBOSyncServiceTests(SimpleTestCase):
    def test_run_create_marks_synced_on_success(self):
        rec = _FakeRecord()
        out = QBOSyncService.run_create(rec, lambda: 'qbo-99')
        self.assertEqual(out, 'qbo-99')
        self.assertEqual(rec.qbo_id, 'qbo-99')
        self.assertEqual(rec.qbo_sync_status, 'synced')

    def test_run_create_marks_failed_on_exception(self):
        rec = _FakeRecord()
        def boom():
            raise ValueError('No active QBO connection')
        out = QBOSyncService.run_create(rec, boom)
        self.assertIsNone(out)
        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'No active QBO connection')

    def test_run_update_clears_error_on_success(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        rec.qbo_sync_status = 'sync_failed'
        rec.qbo_sync_error = 'old'
        QBOSyncService.run_update(rec, lambda: None)
        self.assertEqual(rec.qbo_sync_status, 'synced')
        self.assertEqual(rec.qbo_sync_error, '')

    def test_run_update_marks_failed_on_exception(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        def boom():
            raise RuntimeError('payload bad')
        QBOSyncService.run_update(rec, boom)
        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'payload bad')

    def test_run_create_marks_failed_with_create_op(self):
        rec = _FakeRecord()
        QBOSyncService.run_create(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
        self.assertEqual(rec.qbo_pending_op, 'create')

    def test_run_update_marks_failed_with_update_op(self):
        rec = _FakeRecord()
        rec.qbo_id = 'q1'
        QBOSyncService.run_update(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
        self.assertEqual(rec.qbo_pending_op, 'update')

    def test_run_delete_marks_failed_with_delete_op_and_reraises(self):
        rec = _FakeRecord()
        rec.qbo_id = 'q1'
        with self.assertRaises(ValueError):
            QBOSyncService.run_delete(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
        self.assertEqual(rec.qbo_pending_op, 'delete')
