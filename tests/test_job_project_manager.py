from rest_framework.test import APIClient
from django.contrib.auth.models import Permission

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


class JobProjectManagerSerializerTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(
            username='pm_bob', first_name='Bob', last_name='Brown', password='x'
        )
        self.job = Job.objects.create(
            job_number='JOB-PMS-0001', name='Ser Job', status='draft', contact=self.contact,
        )

    def test_get_includes_pm_fields_null(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['project_manager'])
        self.assertIsNone(resp.data['project_manager_name'])

    def test_patch_sets_project_manager(self):
        resp = self.client.patch(
            f'/api/jobs/{self.job.pk}/', {'project_manager': self.pm.pk}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.project_manager_id, self.pm.pk)
        self.assertEqual(resp.data['project_manager'], self.pm.pk)
        self.assertEqual(resp.data['project_manager_name'], 'Bob Brown')

    def test_pm_name_falls_back_to_username(self):
        nameless = User.objects.create_user(username='justuser', password='x')
        self.job.project_manager = nameless
        self.job.save()
        resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.data['project_manager_name'], 'justuser')
