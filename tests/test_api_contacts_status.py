from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService
from tests.test_contacts_status import make_business, make_job
from apps.jobs.models import Job


class StatusEndpointsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_deactivate_and_reactivate_contact(self):
        c = Contact.objects.create(first_name='Api', last_name='X', email='api@x.test')
        r = self.client.post(f'/api/contacts/{c.pk}/deactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_active'])
        r = self.client.post(f'/api/contacts/{c.pk}/reactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['is_active'])

    def test_blockers_render_as_detail_sentence(self):
        c = Contact.objects.create(first_name='Blk', last_name='X', email='blk@x.test')
        make_job(c, Job.STATUS_DRAFT)
        r = self.client.post(f'/api/contacts/{c.pk}/deactivate/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('1 open job', r.data['detail'])

    def test_business_impact_then_deactivate(self):
        b, dc, _ = make_business('ApiCo')
        r = self.client.get(f'/api/businesses/{b.pk}/deactivate-impact/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['contact_count'], 2)
        self.assertEqual(r.data['blockers'], [])
        r = self.client.post(f'/api/businesses/{b.pk}/deactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_active'])
        dc.refresh_from_db()
        self.assertFalse(dc.is_active)

    def test_requires_can_manage_jobs(self):
        plain = User.objects.create_user(username='plain', password='x')
        self.client.force_authenticate(user=plain)
        c = Contact.objects.create(first_name='Perm', last_name='X', email='perm@x.test')
        self.assertEqual(self.client.post(f'/api/contacts/{c.pk}/deactivate/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/businesses/{Business.objects.first().pk}/deactivate-impact/').status_code, 403)

    def test_patch_inactive_contact_refused(self):
        c = Contact.objects.create(first_name='Ro', last_name='X', email='ro@x.test', is_active=False)
        r = self.client.patch(f'/api/contacts/{c.pk}/', {'first_name': 'Nope'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('inactive', r.data['detail'])
        r = self.client.post(f'/api/contacts/{c.pk}/notes/', {'text': 'hi'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f'/api/contacts/{c.pk}/add-tag/', {'name': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_duplicate_409_carries_is_active(self):
        Contact.objects.create(first_name='Dup', last_name='X', email='dup@x.test', is_active=False)
        r = self.client.post('/api/contacts/', {'first_name': 'A', 'last_name': 'B', 'email': 'dup@x.test'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.data['existing_contact']['is_active'])


class StatusFilterTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.live = Contact.objects.create(first_name='Live', last_name='X', email='live@x.test')
        self.dead = Contact.objects.create(first_name='Dead', last_name='X', email='dead@x.test', is_active=False)
        b, dc, _ = make_business('DeadCo')
        ContactService.deactivate_business(b)
        self.dead_biz = b

    def _ids(self, url, **params):
        return [r.get('contact_id') or r.get('business_id')
                for r in self.client.get(url, params).data['results']]

    def test_default_is_active_only(self):
        ids = self._ids('/api/contacts/')
        self.assertIn(self.live.pk, ids); self.assertNotIn(self.dead.pk, ids)
        self.assertNotIn(self.dead_biz.pk, self._ids('/api/businesses/'))

    def test_inactive_and_all(self):
        ids = self._ids('/api/contacts/', status='inactive')
        self.assertIn(self.dead.pk, ids); self.assertNotIn(self.live.pk, ids)
        ids = self._ids('/api/contacts/', status='all')
        self.assertIn(self.dead.pk, ids); self.assertIn(self.live.pk, ids)
        self.assertIn(self.dead_biz.pk, self._ids('/api/businesses/', status='all'))

    def test_bogus_status_falls_back_to_active(self):
        ids = self._ids('/api/contacts/', status='bogus')
        self.assertNotIn(self.dead.pk, ids)

    def test_retrieve_is_unfiltered(self):
        self.assertEqual(self.client.get(f'/api/contacts/{self.dead.pk}/').status_code, 200)

    def test_search_param_combines_with_status(self):
        ids = self._ids('/api/contacts/', status='all', search='Dead')
        self.assertIn(self.dead.pk, ids); self.assertNotIn(self.live.pk, ids)
