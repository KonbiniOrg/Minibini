from tests.base import BaseTestCase
from apps.jobs.services import BoardService
from apps.jobs.models import Job


class BoardColorStabilityTest(BaseTestCase):
    """BoardService surfaces Job.accent_color as the per-job color so
    colors are stable across page loads and across the schedule view."""

    def test_get_approved_data_returns_job_accent_color(self):
        job = Job.objects.filter(status=Job.STATUS_IN_PROGRESS).first()
        if not job:
            job = Job.objects.first()
            for s in ('submitted', 'approved', 'in_progress'):
                job.status = s
                job.save()
        # Force a known-distinct color so we can tell if BoardService is
        # actually reading the field or coincidentally returning the same
        # palette entry by position.
        job.accent_color = '#84cc16'  # palette index 6
        job.save(update_fields=['accent_color'])
        data = BoardService.get_approved_data()
        match = next(j for j in data['jobs'] if j['job_id'] == job.pk)
        self.assertEqual(match['accent_color'], '#84cc16')
