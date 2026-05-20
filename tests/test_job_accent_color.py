from tests.base import BaseTestCase
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.contacts.models import Contact


class JobAccentColorTest(BaseTestCase):
    """Job.accent_color is auto-assigned on first save and persistent."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()

    def test_new_job_gets_accent_color(self):
        job = JobService.create_job(
            contact=self.contact, description='Test job',
        )
        self.assertIsNotNone(job.accent_color)
        self.assertTrue(job.accent_color.startswith('#'))
        self.assertEqual(len(job.accent_color), 7)

    def test_existing_color_preserved_on_resave(self):
        job = JobService.create_job(
            contact=self.contact, description='Test job',
        )
        original = job.accent_color
        job.description = 'Edited'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.accent_color, original)


class JobAccentColorBackfillTest(BaseTestCase):
    """Existing Jobs (loaded from fixture without accent_color) get colors
    via the backfill data migration. Verified indirectly: fixture-loaded
    jobs have non-null accent_color after migrations run."""

    def test_fixture_jobs_have_accent_color(self):
        from apps.jobs.models import JOB_ACCENT_COLOR_PALETTE
        self.assertTrue(Job.objects.exists(), 'Need fixture jobs for this test')
        for job in Job.objects.all():
            self.assertIsNotNone(
                job.accent_color,
                f"Job pk={job.pk} has no accent_color after backfill",
            )
            self.assertIn(job.accent_color, JOB_ACCENT_COLOR_PALETTE)
