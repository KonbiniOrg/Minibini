from django.test import SimpleTestCase
from apps.qbo.services import QBOSyncService


class _FakeRecord:
    def __init__(self):
        self.qbo_id = ''
        self.qbo_sync_status = 'pending'
        self.qbo_sync_error = ''
    def mark_synced(self, qbo_id):
        self.qbo_id = qbo_id
        self.qbo_sync_status = 'synced'
        self.qbo_sync_error = ''
    def mark_failed(self, error):
        self.qbo_sync_status = 'sync_failed'
        self.qbo_sync_error = str(error)


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

    def test_run_resync_clears_error_on_success(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        rec.qbo_sync_status = 'sync_failed'
        rec.qbo_sync_error = 'old'
        QBOSyncService.run_resync(rec, lambda: None)
        self.assertEqual(rec.qbo_sync_status, 'synced')
        self.assertEqual(rec.qbo_sync_error, '')

    def test_run_resync_marks_failed_on_exception(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        def boom():
            raise RuntimeError('payload bad')
        QBOSyncService.run_resync(rec, boom)
        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'payload bad')
