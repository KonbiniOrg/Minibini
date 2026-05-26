from django.test import TestCase
from django.utils import timezone
from apps.core.models import ScheduledProcessRun


class ScheduledProcessRunModelTest(TestCase):
    def test_create_and_defaults(self):
        run = ScheduledProcessRun.objects.create(
            process_name='demo', started_at=timezone.now(),
        )
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_OK)
        self.assertIsNone(run.finished_at)
        self.assertEqual(run.error, '')

    def test_summary_json_roundtrip(self):
        run = ScheduledProcessRun.objects.create(
            process_name='demo', started_at=timezone.now(),
            outcome=ScheduledProcessRun.OUTCOME_SKIPPED,
            summary={'reason': 'no connection'},
        )
        run.refresh_from_db()
        self.assertEqual(run.summary, {'reason': 'no connection'})
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_SKIPPED)
