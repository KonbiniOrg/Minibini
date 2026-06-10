from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job


class JobProjectManagerModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(
            username='pm_alice', first_name='Alice', last_name='Anderson', password='x'
        )

    def _make_job(self, **kwargs):
        return Job.objects.create(
            job_number=kwargs.pop('job_number', 'JOB-PM-0001'),
            name=kwargs.pop('name', 'PM Job'),
            status=Job.STATUS_DRAFT,
            contact=self.contact,
            **kwargs,
        )

    def test_project_manager_defaults_to_none(self):
        job = self._make_job()
        job.refresh_from_db()
        self.assertIsNone(job.project_manager)

    def test_project_manager_can_be_assigned(self):
        job = self._make_job(project_manager=self.pm)
        job.refresh_from_db()
        self.assertEqual(job.project_manager_id, self.pm.pk)

    def test_deleting_pm_user_nulls_field_not_job(self):
        job = self._make_job(job_number='JOB-PM-0002', project_manager=self.pm)
        self.pm.delete()
        job.refresh_from_db()
        self.assertIsNone(job.project_manager)
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())

    def test_managed_jobs_reverse_relation(self):
        job = self._make_job(job_number='JOB-PM-0003', project_manager=self.pm)
        self.assertIn(job, self.pm.managed_jobs.all())
