from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact, Business, Tag


class TagListAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_tags_returns_200(self):
        response = self.client.get('/api/tags/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_list_tags_search_param_filters_by_name(self):
        Tag.objects.create(name='apple')
        Tag.objects.create(name='apricot')
        Tag.objects.create(name='banana')
        response = self.client.get('/api/tags/', {'search': 'ap'})
        self.assertEqual(response.status_code, 200)
        names = [t['name'] for t in response.data['results']]
        self.assertIn('apple', names)
        self.assertIn('apricot', names)
        self.assertNotIn('banana', names)

    def test_unauthenticated_returns_403(self):
        unauth = APIClient()
        response = unauth.get('/api/tags/')
        self.assertEqual(response.status_code, 403)


class ContactTagTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            first_name='Tag', last_name='Subject',
            email='tagsubject@test.com', mobile_number='555-100-0001',
        )

    def test_add_new_tag_creates_tag_and_attaches_to_contact(self):
        response = self.client.post(
            f'/api/contacts/{self.contact.pk}/add-tag/',
            {'name': 'vip'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        names = [t['name'] for t in response.data]
        self.assertIn('vip', names)
        self.assertTrue(Tag.objects.filter(name='vip').exists())

    def test_add_existing_tag_reuses_record(self):
        Tag.objects.create(name='reuse-me')
        self.client.post(
            f'/api/contacts/{self.contact.pk}/add-tag/',
            {'name': 'reuse-me'},
            format='json',
        )
        self.assertEqual(Tag.objects.filter(name='reuse-me').count(), 1)

    def test_add_tag_missing_name_returns_400(self):
        response = self.client.post(
            f'/api/contacts/{self.contact.pk}/add-tag/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_added_tag_appears_in_contact_retrieve_response(self):
        tag = Tag.objects.create(name='retrieve-tag')
        self.contact.tags.add(tag)
        response = self.client.get(f'/api/contacts/{self.contact.pk}/')
        self.assertEqual(response.status_code, 200)
        tag_names = [t['name'] for t in response.data.get('tags', [])]
        self.assertIn('retrieve-tag', tag_names)

    def test_added_tag_appears_in_contact_list_response(self):
        tag = Tag.objects.create(name='list-tag')
        self.contact.tags.add(tag)
        response = self.client.get('/api/contacts/')
        self.assertEqual(response.status_code, 200)
        contact_data = next(
            (c for c in response.data['results'] if c['contact_id'] == self.contact.pk), None
        )
        self.assertIsNotNone(contact_data)
        tag_names = [t['name'] for t in contact_data.get('tags', [])]
        self.assertIn('list-tag', tag_names)

    def test_remove_tag_detaches_from_contact(self):
        tag = Tag.objects.create(name='remove-contact-tag')
        self.contact.tags.add(tag)
        response = self.client.post(
            f'/api/contacts/{self.contact.pk}/remove-tag/',
            {'tag_id': tag.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        names = [t['name'] for t in response.data]
        self.assertNotIn('remove-contact-tag', names)

    def test_remove_tag_missing_tag_id_returns_400(self):
        response = self.client.post(
            f'/api/contacts/{self.contact.pk}/remove-tag/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_remove_tag_does_not_delete_tag_record(self):
        tag = Tag.objects.create(name='keep-tag')
        self.contact.tags.add(tag)
        self.client.post(
            f'/api/contacts/{self.contact.pk}/remove-tag/',
            {'tag_id': tag.pk},
            format='json',
        )
        self.assertTrue(Tag.objects.filter(name='keep-tag').exists())


class BusinessTagTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        dc = Contact.objects.create(
            first_name='BizTag', last_name='Contact',
            email='biztag@test.com', mobile_number='555-100-0002',
        )
        self.business = Business.objects.create(
            business_name='Tag Test Corp',
            default_contact=dc,
        )

    def test_add_tag_to_business(self):
        response = self.client.post(
            f'/api/businesses/{self.business.pk}/add-tag/',
            {'name': 'preferred'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        names = [t['name'] for t in response.data]
        self.assertIn('preferred', names)

    def test_added_tag_appears_in_business_retrieve_response(self):
        tag = Tag.objects.create(name='biz-retrieve-tag')
        self.business.tags.add(tag)
        response = self.client.get(f'/api/businesses/{self.business.pk}/')
        self.assertEqual(response.status_code, 200)
        tag_names = [t['name'] for t in response.data.get('tags', [])]
        self.assertIn('biz-retrieve-tag', tag_names)

    def test_remove_tag_from_business(self):
        tag = Tag.objects.create(name='biz-remove-tag')
        self.business.tags.add(tag)
        response = self.client.post(
            f'/api/businesses/{self.business.pk}/remove-tag/',
            {'tag_id': tag.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        names = [t['name'] for t in response.data]
        self.assertNotIn('biz-remove-tag', names)

    def test_add_tag_missing_name_returns_400(self):
        response = self.client.post(
            f'/api/businesses/{self.business.pk}/add-tag/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class TagSharingTest(BaseTestCase):
    """Tags are shared records — the same name on a contact and a business is one Tag row."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            first_name='Share', last_name='Contact',
            email='share@test.com', mobile_number='555-100-0003',
        )
        dc = Contact.objects.create(
            first_name='Share', last_name='BizContact',
            email='sharebiz@test.com', mobile_number='555-100-0004',
        )
        self.business = Business.objects.create(
            business_name='Share Tag Corp',
            default_contact=dc,
        )

    def test_same_name_applied_to_contact_and_business_is_one_tag(self):
        self.client.post(
            f'/api/contacts/{self.contact.pk}/add-tag/',
            {'name': 'shared-tag'},
            format='json',
        )
        self.client.post(
            f'/api/businesses/{self.business.pk}/add-tag/',
            {'name': 'shared-tag'},
            format='json',
        )
        self.assertEqual(Tag.objects.filter(name='shared-tag').count(), 1)

    def test_shared_tag_is_linked_to_both_entities(self):
        tag = Tag.objects.create(name='cross-entity-tag')
        self.contact.tags.add(tag)
        self.business.tags.add(tag)
        self.assertIn(self.contact, tag.contacts.all())
        self.assertIn(self.business, tag.businesses.all())

    def test_shared_tag_appears_in_tags_list(self):
        tag = Tag.objects.create(name='listed-shared-tag')
        self.contact.tags.add(tag)
        self.business.tags.add(tag)
        response = self.client.get('/api/tags/')
        names = [t['name'] for t in response.data['results']]
        self.assertIn('listed-shared-tag', names)
