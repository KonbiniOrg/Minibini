from django.test import TestCase

from apps.core.history import record_history, history_model_for
from apps.core.models import JobHistory, CrmHistory, PurchasingHistory


class HistoryRoutingTest(TestCase):
    """record_history routes each object_type to its domain's table."""

    DOMAIN = {
        'job': JobHistory, 'task': JobHistory, 'estimate': JobHistory,
        'changeorder': JobHistory, 'invoice': JobHistory, 'material': JobHistory,
        'deliverable': JobHistory, 'shipment': JobHistory,
        'contact': CrmHistory, 'business': CrmHistory,
        'purchaseorder': PurchasingHistory, 'bill': PurchasingHistory,
    }

    def test_record_history_writes_to_domain_table(self):
        for object_type, model in self.DOMAIN.items():
            with self.subTest(object_type=object_type):
                entry = record_history(object_type=object_type, entry_type='note',
                                       object_id=1, text='x')
                self.assertIsInstance(entry, model)
                self.assertTrue(model.objects.filter(pk=entry.pk).exists())

    def test_history_model_for(self):
        self.assertIs(history_model_for('invoice'), JobHistory)
        self.assertIs(history_model_for('business'), CrmHistory)
        self.assertIs(history_model_for('bill'), PurchasingHistory)
        # untracked object types route nowhere
        self.assertIsNone(history_model_for('shift'))

    def test_unknown_object_type_raises(self):
        with self.assertRaises(ValueError):
            record_history(object_type='shift', object_id=1)

    def test_timestamp_backdates(self):
        from django.utils import timezone
        from datetime import timedelta
        when = timezone.now() - timedelta(days=10)
        entry = record_history(object_type='job', entry_type='note', object_id=1,
                               text='old', timestamp=when)
        self.assertEqual(JobHistory.objects.get(pk=entry.pk).timestamp, when)
