from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord, TempEmail
from apps.jobs.models import Job
from django.utils import timezone


class EmailAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        # Create an email record with temp data for testing
        self.email = EmailRecord.objects.create(
            message_id='<test-123@example.com>',
            job=None,
        )
        self.temp_email = TempEmail.objects.create(
            email_record=self.email,
            uid='12345',
            subject='Test Email Subject',
            from_email='sender@example.com',
            to_email='recipient@example.com',
            cc_email='',
            date_sent=timezone.now(),
            is_read=False,
            is_starred=False,
            has_attachments=False,
        )

    def test_list_emails(self):
        response = self.client.get('/api/emails/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_retrieve_email(self):
        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message_id'], '<test-123@example.com>')
        self.assertEqual(response.data['temp_email']['subject'], 'Test Email Subject')

    def test_retrieve_email_not_found(self):
        response = self.client.get('/api/emails/99999/')
        self.assertEqual(response.status_code, 404)

    def test_link_to_job(self):
        job = Job.objects.first()
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-job/',
            {'job_id': job.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertEqual(self.email.job_id, job.pk)

    def test_link_to_job_missing_job_id(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-job/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_unlink_from_job(self):
        job = Job.objects.first()
        self.email.job = job
        self.email.save()
        response = self.client.post(f'/api/emails/{self.email.pk}/unlink-from-job/')
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertIsNone(self.email.job)

    def test_send_stub_returns_501(self):
        response = self.client.post('/api/emails/send/', {}, format='json')
        self.assertEqual(response.status_code, 501)
