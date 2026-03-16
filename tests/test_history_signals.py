from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User
from apps.estimates.models import Estimate
from apps.estimates.signals import estimate_status_changed_for_job


class SignalHistoryTest(BaseTestCase):
    def test_job_status_change_from_signal_creates_action_entry(self):
        """When a signal changes job status, an action entry is created with System user and reason."""
        system_user = User.objects.get(username='system')
        # Get an estimate whose job is in a state that can transition
        estimate = Estimate.objects.first()
        job = estimate.job
        # Set job to a state that allows transition to approved
        job.status = 'submitted'
        job.save()

        # Clear any history from setup saves
        HistoryEntry.objects.all().delete()

        # Trigger the signal
        estimate_status_changed_for_job.send(
            sender=Estimate,
            estimate=estimate,
            new_job_status='approved',
        )

        entries = HistoryEntry.objects.filter(
            object_type='job',
            object_id=job.pk,
            entry_type='action',
        )
        self.assertTrue(entries.exists())
        entry = entries.first()
        self.assertEqual(entry.user, system_user)
        self.assertIn('status', entry.changes)
        self.assertEqual(entry.changes['status']['old'], 'submitted')
        self.assertEqual(entry.changes['status']['new'], 'approved')
        self.assertIn(estimate.estimate_number, entry.text)

    def test_no_action_entry_when_job_already_completed(self):
        """No action entry when job is in terminal state."""
        estimate = Estimate.objects.first()
        job = estimate.job
        # Walk through valid transitions to reach 'completed'
        job.status = 'submitted'
        job.save()
        job.status = 'approved'
        job.save()
        job.status = 'completed'
        job.save()

        HistoryEntry.objects.all().delete()

        estimate_status_changed_for_job.send(
            sender=Estimate,
            estimate=estimate,
            new_job_status='approved',
        )

        entries = HistoryEntry.objects.filter(
            object_type='job',
            object_id=job.pk,
            entry_type='action',
        )
        self.assertFalse(entries.exists())
