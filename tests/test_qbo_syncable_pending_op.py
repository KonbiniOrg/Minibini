from django.test import SimpleTestCase
from apps.expenses.models import Expense  # a concrete QBOSyncable


class PendingOpTests(SimpleTestCase):
    def test_constants(self):
        self.assertEqual(Expense.OP_CREATE, 'create')
        self.assertEqual(Expense.OP_UPDATE, 'update')
        self.assertEqual(Expense.OP_DELETE, 'delete')

    def test_mark_failed_records_op(self):
        exp = Expense()
        exp.save = lambda *a, **k: None  # avoid DB
        exp.mark_failed('boom', Expense.OP_DELETE)
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_FAILED)
        self.assertEqual(exp.qbo_sync_error, 'boom')
        self.assertEqual(exp.qbo_pending_op, 'delete')

    def test_mark_synced_clears_op(self):
        exp = Expense()
        exp.save = lambda *a, **k: None
        exp.qbo_pending_op = 'update'
        exp.mark_synced('qbo-1')
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_SYNCED)
        self.assertEqual(exp.qbo_id, 'qbo-1')
        self.assertEqual(exp.qbo_pending_op, '')
