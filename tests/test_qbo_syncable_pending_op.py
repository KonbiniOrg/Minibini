from django.test import SimpleTestCase
from apps.purchasing.models import BillPayment  # a concrete QBOSyncable


class PendingOpTests(SimpleTestCase):
    def test_constants(self):
        self.assertEqual(BillPayment.OP_CREATE, 'create')
        self.assertEqual(BillPayment.OP_UPDATE, 'update')
        self.assertEqual(BillPayment.OP_DELETE, 'delete')

    def test_mark_failed_records_op(self):
        bp = BillPayment()
        bp.save = lambda *a, **k: None  # avoid DB
        bp.mark_failed('boom', BillPayment.OP_DELETE)
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_FAILED)
        self.assertEqual(bp.qbo_sync_error, 'boom')
        self.assertEqual(bp.qbo_pending_op, 'delete')

    def test_mark_synced_clears_op(self):
        bp = BillPayment()
        bp.save = lambda *a, **k: None
        bp.qbo_pending_op = 'update'
        bp.mark_synced('qbo-1')
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_SYNCED)
        self.assertEqual(bp.qbo_id, 'qbo-1')
        self.assertEqual(bp.qbo_pending_op, '')
