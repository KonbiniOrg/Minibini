from datetime import timedelta
from apps.core.models import JobHistory
from apps.core.history import record_history
from decimal import Decimal

from django.core.management import call_command
from django.utils import timezone
from tests.base import BaseTestCase


class BackfillJobHistoryTest(BaseTestCase):
    def test_backfill_creates_marked_entries_for_job(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        before = JobHistory.objects.filter(object_type='job', object_id=job.pk).count()
        call_command('backfill_job_history', f'--job={job.pk}')
        after = JobHistory.objects.filter(object_type='job', object_id=job.pk).count()
        self.assertGreater(after, before)
        marked = JobHistory.objects.filter(
            object_type='job', object_id=job.pk, changes___backfill=True,
        )
        self.assertTrue(marked.exists())

    def test_clear_removes_only_backfilled_entries(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        keep = record_history(
            entry_type='note', object_type='job', object_id=job.pk, text='real note',
        )
        call_command('backfill_job_history', f'--job={job.pk}')
        call_command('backfill_job_history', f'--job={job.pk}', '--clear')
        self.assertTrue(JobHistory.objects.filter(pk=keep.pk).exists())
        self.assertFalse(
            JobHistory.objects.filter(object_id=job.pk, changes___backfill=True).exists()
        )

    def test_task_creation_not_before_job_creation(self):
        """A backfilled Task 'created' entry must never predate the Job's."""
        from apps.jobs.models import Job, Task
        job = Job.objects.first()
        task = Task.objects.filter(job=job).first()
        if task is None:
            task = Task.objects.create(job=job, name='BF chronology task', service_item_id=1)
        call_command('backfill_job_history', f'--job={job.pk}')
        job_created = JobHistory.objects.filter(
            object_type='job', object_id=job.pk,
            changes___created=True, changes___backfill=True,
        ).order_by('timestamp').first()
        task_created = JobHistory.objects.filter(
            object_type='task', object_id=task.pk,
            changes___created=True, changes___backfill=True,
        ).order_by('timestamp').first()
        self.assertIsNotNone(job_created)
        self.assertIsNotNone(task_created)
        self.assertGreaterEqual(task_created.timestamp, job_created.timestamp)

    def test_no_placeholder_actions_real_action_emitted(self):
        """Action entries read like real lifecycle events, not 'Backfilled activity on X'."""
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate
        job = Job.objects.first()
        Estimate.objects.create(
            job=job, estimate_number='BF-EST-CHRONO', version=99,
            status='open', sent_date=timezone.now(),
        )
        call_command('backfill_job_history', f'--job={job.pk}')
        actions = JobHistory.objects.filter(entry_type='action', changes___backfill=True)
        self.assertTrue(actions.exists())
        for a in actions:
            self.assertNotIn('Backfilled activity', a.changes.get('_action', ''))
        # the sent estimate produced a human 'sent to the customer' beat
        self.assertTrue(
            actions.filter(changes___action__icontains='sent to the customer').exists()
        )

    def test_entries_are_at_least_a_minute_apart(self):
        """No two backfilled entries collide on the same timestamp."""
        from apps.jobs.models import Job, Task
        job = Job.objects.first()
        # several tasks share one anchor date -> would collide without spacing
        for i in range(4):
            Task.objects.create(job=job, name=f'BF spacing {i}', service_item_id=1)
        call_command('backfill_job_history', f'--job={job.pk}')
        times = list(
            JobHistory.objects.filter(changes___backfill=True)
            .order_by('timestamp').values_list('timestamp', flat=True)
        )
        self.assertGreater(len(times), 4)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, timedelta(minutes=1))

    def test_emits_field_diff_audit(self):
        """At least one backfilled audit entry is a real field diff (old -> new)."""
        from apps.jobs.models import Job
        from apps.deliverables.models import Deliverable
        job = Job.objects.first()
        Deliverable.objects.create(
            job=job, description='BF widget', qty_ordered=Decimal('3'), units='ea',
        )
        call_command('backfill_job_history', f'--job={job.pk}')
        audits = JobHistory.objects.filter(entry_type='audit', changes___backfill=True)
        has_diff = any(
            [k for k in (a.changes or {}) if not k.startswith('_')]
            for a in audits
        )
        self.assertTrue(has_diff)
