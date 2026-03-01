"""
Tests for the tag system on contacts and businesses.

Covers:
- Tag model creation and uniqueness
- M2M: adding/removing tags on Contact and Business
- tag_list view (GET list, POST create)
- delete_tag view
- contact_list tag filter (?tag=<id>)
- business_list tag filter (?tag=<id>)
- add_tag_to_contact / remove_tag_from_contact views
- add_tag_to_business / remove_tag_from_business views
- Tags displayed on contact_detail and business_detail
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError

from apps.contacts.models import Contact, Business, Tag


def make_contact(first_name='John', last_name='Doe', email=None, **kwargs):
    email = email or f'{first_name.lower()}.{last_name.lower()}@example.com'
    return Contact.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        work_number='555-0001',
        **kwargs,
    )


def make_business(name='Test Business', contact=None):
    if contact is None:
        contact = make_contact(email=f'default@{name.replace(" ", "").lower()}.com')
    b = Business.objects.create(business_name=name, default_contact=contact)
    contact.business = b
    contact.save()
    return b


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TagModelTest(TestCase):

    def test_create_tag(self):
        tag = Tag.objects.create(name='pays late')
        self.assertEqual(tag.name, 'pays late')
        self.assertIsNotNone(tag.tag_id)

    def test_str_returns_name(self):
        tag = Tag.objects.create(name='VIP')
        self.assertEqual(str(tag), 'VIP')

    def test_name_must_be_unique(self):
        Tag.objects.create(name='duplicate')
        with self.assertRaises(IntegrityError):
            Tag.objects.create(name='duplicate')

    def test_tags_ordered_alphabetically(self):
        Tag.objects.create(name='zebra')
        Tag.objects.create(name='apple')
        Tag.objects.create(name='mango')
        names = list(Tag.objects.values_list('name', flat=True))
        self.assertEqual(names, ['apple', 'mango', 'zebra'])


class ContactTagM2MTest(TestCase):

    def setUp(self):
        self.contact = make_contact()
        self.tag1 = Tag.objects.create(name='pays late')
        self.tag2 = Tag.objects.create(name='VIP')

    def test_add_tag_to_contact(self):
        self.contact.tags.add(self.tag1)
        self.assertIn(self.tag1, self.contact.tags.all())

    def test_remove_tag_from_contact(self):
        self.contact.tags.add(self.tag1, self.tag2)
        self.contact.tags.remove(self.tag1)
        self.assertNotIn(self.tag1, self.contact.tags.all())
        self.assertIn(self.tag2, self.contact.tags.all())

    def test_contact_tags_reverse_relation(self):
        self.contact.tags.add(self.tag1)
        self.assertIn(self.contact, self.tag1.contacts.all())


class BusinessTagM2MTest(TestCase):

    def setUp(self):
        self.business = make_business()
        self.tag1 = Tag.objects.create(name='wholesale')
        self.tag2 = Tag.objects.create(name='net 30')

    def test_add_tag_to_business(self):
        self.business.tags.add(self.tag1)
        self.assertIn(self.tag1, self.business.tags.all())

    def test_remove_tag_from_business(self):
        self.business.tags.add(self.tag1, self.tag2)
        self.business.tags.remove(self.tag1)
        self.assertNotIn(self.tag1, self.business.tags.all())
        self.assertIn(self.tag2, self.business.tags.all())

    def test_business_tags_reverse_relation(self):
        self.business.tags.add(self.tag1)
        self.assertIn(self.business, self.tag1.businesses.all())


# ---------------------------------------------------------------------------
# tag_list view
# ---------------------------------------------------------------------------

class TagListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('contacts:tag_list')

    def test_get_renders_tag_list(self):
        Tag.objects.create(name='existing tag')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'existing tag')

    def test_post_creates_tag(self):
        response = self.client.post(self.url, {'name': 'new tag'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Tag.objects.filter(name='new tag').exists())

    def test_post_duplicate_shows_error(self):
        Tag.objects.create(name='duplicate')
        response = self.client.post(self.url, {'name': 'duplicate'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_post_empty_name_shows_error(self):
        response = self.client.post(self.url, {'name': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tag.objects.filter(name='').exists())


# ---------------------------------------------------------------------------
# delete_tag view
# ---------------------------------------------------------------------------

class DeleteTagViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.tag = Tag.objects.create(name='to delete')

    def test_post_deletes_tag(self):
        url = reverse('contacts:delete_tag', args=[self.tag.tag_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tag.objects.filter(tag_id=self.tag.tag_id).exists())

    def test_get_redirects(self):
        url = reverse('contacts:delete_tag', args=[self.tag.tag_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        # Tag should NOT be deleted by a GET
        self.assertTrue(Tag.objects.filter(tag_id=self.tag.tag_id).exists())

    def test_deleting_tag_removes_it_from_contacts(self):
        contact = make_contact()
        contact.tags.add(self.tag)
        url = reverse('contacts:delete_tag', args=[self.tag.tag_id])
        self.client.post(url)
        contact.refresh_from_db()
        self.assertNotIn(self.tag, contact.tags.all())


# ---------------------------------------------------------------------------
# add/remove tag on contact views
# ---------------------------------------------------------------------------

class AddRemoveTagContactViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.contact = make_contact()
        self.tag = Tag.objects.create(name='VIP')

    def test_add_tag_to_contact(self):
        url = reverse('contacts:add_tag_to_contact', args=[self.contact.contact_id])
        response = self.client.post(url, {'tag_id': self.tag.tag_id})
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.tag, self.contact.tags.all())

    def test_add_tag_redirects_to_contact_detail(self):
        url = reverse('contacts:add_tag_to_contact', args=[self.contact.contact_id])
        response = self.client.post(url, {'tag_id': self.tag.tag_id})
        expected = reverse('contacts:contact_detail', args=[self.contact.contact_id])
        self.assertRedirects(response, expected)

    def test_remove_tag_from_contact(self):
        self.contact.tags.add(self.tag)
        url = reverse('contacts:remove_tag_from_contact', args=[self.contact.contact_id, self.tag.tag_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(self.tag, self.contact.tags.all())

    def test_remove_tag_redirects_to_contact_detail(self):
        self.contact.tags.add(self.tag)
        url = reverse('contacts:remove_tag_from_contact', args=[self.contact.contact_id, self.tag.tag_id])
        response = self.client.post(url)
        expected = reverse('contacts:contact_detail', args=[self.contact.contact_id])
        self.assertRedirects(response, expected)


# ---------------------------------------------------------------------------
# add/remove tag on business views
# ---------------------------------------------------------------------------

class AddRemoveTagBusinessViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.tag = Tag.objects.create(name='wholesale')

    def test_add_tag_to_business(self):
        url = reverse('contacts:add_tag_to_business', args=[self.business.business_id])
        response = self.client.post(url, {'tag_id': self.tag.tag_id})
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.tag, self.business.tags.all())

    def test_add_tag_redirects_to_business_detail(self):
        url = reverse('contacts:add_tag_to_business', args=[self.business.business_id])
        response = self.client.post(url, {'tag_id': self.tag.tag_id})
        expected = reverse('contacts:business_detail', args=[self.business.business_id])
        self.assertRedirects(response, expected)

    def test_remove_tag_from_business(self):
        self.business.tags.add(self.tag)
        url = reverse('contacts:remove_tag_from_business', args=[self.business.business_id, self.tag.tag_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(self.tag, self.business.tags.all())

    def test_remove_tag_redirects_to_business_detail(self):
        self.business.tags.add(self.tag)
        url = reverse('contacts:remove_tag_from_business', args=[self.business.business_id, self.tag.tag_id])
        response = self.client.post(url)
        expected = reverse('contacts:business_detail', args=[self.business.business_id])
        self.assertRedirects(response, expected)


# ---------------------------------------------------------------------------
# contact_list tag filter
# ---------------------------------------------------------------------------

class ContactListTagFilterTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.tag = Tag.objects.create(name='pays late')
        self.tagged_contact = make_contact(first_name='Alice', last_name='Late', email='alice@late.com')
        self.tagged_contact.tags.add(self.tag)
        self.untagged_contact = make_contact(first_name='Bob', last_name='Good', email='bob@good.com')

    def test_no_filter_shows_all_contacts(self):
        url = reverse('contacts:contact_list')
        response = self.client.get(url)
        self.assertContains(response, 'Alice')
        self.assertContains(response, 'Bob')

    def test_tag_filter_shows_only_tagged(self):
        url = reverse('contacts:contact_list') + f'?tag={self.tag.tag_id}'
        response = self.client.get(url)
        self.assertContains(response, 'Alice')
        self.assertNotContains(response, 'Bob')

    def test_tag_filter_passes_all_tags_to_template(self):
        url = reverse('contacts:contact_list')
        response = self.client.get(url)
        self.assertIn('all_tags', response.context)
        self.assertIn(self.tag, response.context['all_tags'])

    def test_active_tag_passed_to_template(self):
        url = reverse('contacts:contact_list') + f'?tag={self.tag.tag_id}'
        response = self.client.get(url)
        self.assertEqual(response.context['active_tag'], self.tag)


# ---------------------------------------------------------------------------
# business_list tag filter
# ---------------------------------------------------------------------------

class BusinessListTagFilterTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.tag = Tag.objects.create(name='wholesale')
        self.tagged_biz = make_business('Tagged Corp')
        self.tagged_biz.tags.add(self.tag)
        self.untagged_biz = make_business('Normal Corp')

    def test_no_filter_shows_all_businesses(self):
        url = reverse('contacts:business_list')
        response = self.client.get(url)
        self.assertContains(response, 'Tagged Corp')
        self.assertContains(response, 'Normal Corp')

    def test_tag_filter_shows_only_tagged(self):
        url = reverse('contacts:business_list') + f'?tag={self.tag.tag_id}'
        response = self.client.get(url)
        self.assertContains(response, 'Tagged Corp')
        self.assertNotContains(response, 'Normal Corp')

    def test_tag_filter_passes_all_tags_to_template(self):
        url = reverse('contacts:business_list')
        response = self.client.get(url)
        self.assertIn('all_tags', response.context)
        self.assertIn(self.tag, response.context['all_tags'])

    def test_active_tag_passed_to_template(self):
        url = reverse('contacts:business_list') + f'?tag={self.tag.tag_id}'
        response = self.client.get(url)
        self.assertEqual(response.context['active_tag'], self.tag)


# ---------------------------------------------------------------------------
# Tags displayed on detail pages
# ---------------------------------------------------------------------------

class ContactDetailTagDisplayTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.contact = make_contact()
        self.tag = Tag.objects.create(name='VIP')
        self.contact.tags.add(self.tag)

    def test_contact_detail_shows_tag(self):
        url = reverse('contacts:contact_detail', args=[self.contact.contact_id])
        response = self.client.get(url)
        self.assertContains(response, 'VIP')

    def test_contact_detail_shows_add_tag_form(self):
        url = reverse('contacts:contact_detail', args=[self.contact.contact_id])
        response = self.client.get(url)
        add_url = reverse('contacts:add_tag_to_contact', args=[self.contact.contact_id])
        self.assertContains(response, add_url)

    def test_contact_detail_shows_remove_tag_form(self):
        url = reverse('contacts:contact_detail', args=[self.contact.contact_id])
        response = self.client.get(url)
        remove_url = reverse('contacts:remove_tag_from_contact', args=[self.contact.contact_id, self.tag.tag_id])
        self.assertContains(response, remove_url)


class BusinessDetailTagDisplayTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.business = make_business()
        self.tag = Tag.objects.create(name='wholesale')
        self.business.tags.add(self.tag)

    def test_business_detail_shows_tag(self):
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)
        self.assertContains(response, 'wholesale')

    def test_business_detail_shows_add_tag_form(self):
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)
        add_url = reverse('contacts:add_tag_to_business', args=[self.business.business_id])
        self.assertContains(response, add_url)

    def test_business_detail_shows_remove_tag_form(self):
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)
        remove_url = reverse('contacts:remove_tag_from_business', args=[self.business.business_id, self.tag.tag_id])
        self.assertContains(response, remove_url)
