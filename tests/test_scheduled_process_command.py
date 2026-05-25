from django.test import TestCase
from apps.core.models import ScheduledProcessRun
from apps.core.management.base import ScheduledProcessCommand, SkipRun


class _OkCmd(ScheduledProcessCommand):
    process_name = 'test_ok'

    def run(self):
        return {'did': 1}


class _SkipCmd(ScheduledProcessCommand):
    process_name = 'test_skip'

    def run(self):
        raise SkipRun('no connection')


class _FailCmd(ScheduledProcessCommand):
    process_name = 'test_fail'

    def run(self):
        raise ValueError('boom')


class _ErrorsCmd(ScheduledProcessCommand):
    process_name = 'test_errors'

    def run(self):
        return {'did': 2, 'errors': ['boom on item 5']}


class ScheduledProcessCommandTest(TestCase):
    def test_ok_run_records_summary(self):
        _OkCmd().handle()
        run = ScheduledProcessRun.objects.get(process_name='test_ok')
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_OK)
        self.assertEqual(run.summary, {'did': 1})
        self.assertIsNotNone(run.finished_at)

    def test_skip_run_records_reason(self):
        _SkipCmd().handle()
        run = ScheduledProcessRun.objects.get(process_name='test_skip')
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_SKIPPED)
        self.assertEqual(run.summary, {'reason': 'no connection'})

    def test_failed_run_records_and_reraises(self):
        with self.assertRaises(ValueError):
            _FailCmd().handle()
        run = ScheduledProcessRun.objects.get(process_name='test_fail')
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_FAILED)
        self.assertIn('boom', run.error)
        self.assertIsNotNone(run.finished_at)

    def test_run_with_errors_records_failed_but_keeps_summary(self):
        _ErrorsCmd().handle()
        run = ScheduledProcessRun.objects.get(process_name='test_errors')
        self.assertEqual(run.outcome, ScheduledProcessRun.OUTCOME_FAILED)
        self.assertEqual(run.summary, {'did': 2, 'errors': ['boom on item 5']})
