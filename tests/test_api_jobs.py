from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job


class JobAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def _get_approved_job(self):
        """Get or create a job in 'approved' status (draft→submitted→approved)."""
        job = Job.objects.filter(status='approved').first()
        if not job:
            job = Job.objects.first()
            # Walk through valid transitions
            job.status = 'submitted'
            job.save()
            job.status = 'approved'
            job.save()
        return job

    def test_list_jobs(self):
        response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_job(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post('/api/jobs/', {
            'name': 'Test API Job',
            'contact': contact.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Test API Job')
        self.assertIn('job_number', response.data)

    def test_retrieve_job(self):
        job = Job.objects.first()
        response = self.client.get(f'/api/jobs/{job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['job_id'], job.pk)

    def test_update_job(self):
        job = Job.objects.first()
        response = self.client.patch(f'/api/jobs/{job.pk}/', {
            'name': 'Updated Name',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')

    def test_delete_job(self):
        # Create a standalone job with no related objects
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post('/api/jobs/', {
            'name': 'Delete Me',
            'contact': contact.pk,
        }, format='json')
        job_id = response.data['job_id']
        response = self.client.delete(f'/api/jobs/{job_id}/')
        self.assertEqual(response.status_code, 204)

    def test_complete_job(self):
        job = self._get_approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/complete/')
        self.assertEqual(response.status_code, 200)

    def test_cancel_job_requires_reason(self):
        job = self._get_approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_job_with_reason(self):
        job = self._get_approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {
            'reason': 'Customer withdrew',
        }, format='json')
        self.assertEqual(response.status_code, 200)
