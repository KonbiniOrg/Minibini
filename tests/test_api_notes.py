from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User


class JobNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_job(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(
            f'/api/jobs/{job.pk}/notes/',
            {'text': 'Customer called about delivery.'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.entry_type, 'note')
        self.assertEqual(entry.object_type, 'job')
        self.assertEqual(entry.object_id, job.pk)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.text, 'Customer called about delivery.')
        self.assertIsNone(entry.changes)

    def test_add_note_requires_text(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(f'/api/jobs/{job.pk}/notes/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_add_empty_note_rejected(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(
            f'/api/jobs/{job.pk}/notes/', {'text': ''}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_add_whitespace_only_note_rejected(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(
            f'/api/jobs/{job.pk}/notes/', {'text': '   '}, format='json',
        )
        self.assertEqual(response.status_code, 400)


class ContactNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_contact(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post(
            f'/api/contacts/{contact.pk}/notes/',
            {'text': 'Preferred morning calls.'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.object_type, 'contact')
        self.assertEqual(entry.object_id, contact.pk)


class BusinessNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_business(self):
        from apps.contacts.models import Business
        business = Business.objects.first()
        response = self.client.post(
            f'/api/businesses/{business.pk}/notes/',
            {'text': 'Net 30 terms confirmed.'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.object_type, 'business')
        self.assertEqual(entry.object_id, business.pk)
