from django.core.management import call_command
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry


class BackfillJobHistoryTest(BaseTestCase):
    def test_backfill_creates_marked_entries_for_job(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        before = HistoryEntry.objects.filter(object_type='job', object_id=job.pk).count()
        call_command('backfill_job_history', f'--job={job.pk}')
        after = HistoryEntry.objects.filter(object_type='job', object_id=job.pk).count()
        self.assertGreater(after, before)
        marked = HistoryEntry.objects.filter(
            object_type='job', object_id=job.pk, changes___backfill=True,
        )
        self.assertTrue(marked.exists())

    def test_clear_removes_only_backfilled_entries(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        keep = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='real note',
        )
        call_command('backfill_job_history', f'--job={job.pk}')
        call_command('backfill_job_history', f'--job={job.pk}', '--clear')
        self.assertTrue(HistoryEntry.objects.filter(pk=keep.pk).exists())
        self.assertFalse(
            HistoryEntry.objects.filter(object_id=job.pk, changes___backfill=True).exists()
        )
