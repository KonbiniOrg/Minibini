"""Tests for ?starts_with=, ?search=, and ?tag= on /api/contacts/ and /api/businesses/."""
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact, Business, Tag


class ContactStartsWithTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.alice = Contact.objects.create(
            first_name='Alice', last_name='Zebra',
            email='alice@filter.com', mobile_number='555-200-0001',
        )
        self.bob = Contact.objects.create(
            first_name='Bob', last_name='Yak',
            email='bob@filter.com', mobile_number='555-200-0002',
        )
        self.digit = Contact.objects.create(
            first_name='3M', last_name='Person',
            email='digit@filter.com', mobile_number='555-200-0003',
        )

    def test_starts_with_letter_returns_only_matching_first_names(self):
        response = self.client.get('/api/contacts/', {'starts_with': 'A'})
        self.assertEqual(response.status_code, 200)
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(self.alice.pk, ids)
        self.assertNotIn(self.bob.pk, ids)

    def test_starts_with_is_case_insensitive(self):
        response = self.client.get('/api/contacts/', {'starts_with': 'a'})
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(self.alice.pk, ids)

    def test_starts_with_digit_range_returns_digit_contacts(self):
        response = self.client.get('/api/contacts/', {'starts_with': '0-9'})
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(self.digit.pk, ids)
        self.assertNotIn(self.alice.pk, ids)
        self.assertNotIn(self.bob.pk, ids)

    def test_no_starts_with_returns_all(self):
        response = self.client.get('/api/contacts/')
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(self.alice.pk, ids)
        self.assertIn(self.bob.pk, ids)


class ContactSearchTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.target = Contact.objects.create(
            first_name='Srchfirst', last_name='Srchlast',
            email='srchuniq@filtertest.com',
            mobile_number='4155550101',
            work_number='(415) 555-0102',
            home_number='415.555.0103',
        )
        self.other = Contact.objects.create(
            first_name='Unrelated', last_name='Person',
            email='nope@nope.com', mobile_number='999-999-9999',
        )

    def _ids(self, response):
        return [c['contact_id'] for c in response.data['results']]

    def test_search_by_first_name(self):
        r = self.client.get('/api/contacts/', {'search': 'Srchfirst'})
        self.assertIn(self.target.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_search_by_last_name(self):
        r = self.client.get('/api/contacts/', {'search': 'Srchlast'})
        self.assertIn(self.target.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_search_by_email(self):
        r = self.client.get('/api/contacts/', {'search': 'srchuniq'})
        self.assertIn(self.target.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_search_plain_digits_matches_mobile(self):
        """Plain digit string matches mobile stored without formatting."""
        r = self.client.get('/api/contacts/', {'search': '4155550101'})
        self.assertIn(self.target.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_search_dashes_stripped_matches_work_number_with_parens_spaces(self):
        """'4155550102' should match work_number '(415) 555-0102' after stripping."""
        r = self.client.get('/api/contacts/', {'search': '4155550102'})
        self.assertIn(self.target.pk, self._ids(r))

    def test_search_formatted_query_matches_plain_stored_mobile(self):
        """'415-555-0101' should match mobile '4155550101' after stripping dashes."""
        r = self.client.get('/api/contacts/', {'search': '415-555-0101'})
        self.assertIn(self.target.pk, self._ids(r))

    def test_search_dots_stripped_matches_home_number(self):
        """'4155550103' should match home_number '415.555.0103' after stripping dots."""
        r = self.client.get('/api/contacts/', {'search': '4155550103'})
        self.assertIn(self.target.pk, self._ids(r))

    def test_search_formatting_chars_only_does_not_match_unrelated_contact(self):
        """A search term that strips to empty string should not match via phone path."""
        r = self.client.get('/api/contacts/', {'search': '-'})
        # 'other' has no '-' in name or email, so should not appear
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_starts_with_and_search_both_apply(self):
        r = self.client.get('/api/contacts/', {'starts_with': 'S', 'search': 'Srchlast'})
        self.assertIn(self.target.pk, self._ids(r))
        # 'Unrelated' starts with U — excluded by starts_with
        self.assertNotIn(self.other.pk, self._ids(r))


class BusinessStartsWithTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        dc1 = Contact.objects.create(first_name='B1', last_name='C', email='b1@bsw.com', mobile_number='555-201-0001')
        dc2 = Contact.objects.create(first_name='B2', last_name='C', email='b2@bsw.com', mobile_number='555-201-0002')
        dc3 = Contact.objects.create(first_name='B3', last_name='C', email='b3@bsw.com', mobile_number='555-201-0003')
        self.biz_a = Business.objects.create(business_name='Acme Corp Bsw', default_contact=dc1)
        self.biz_b = Business.objects.create(business_name='Beta Ltd Bsw', default_contact=dc2)
        self.biz_0 = Business.objects.create(business_name='3D Co Bsw', default_contact=dc3)

    def test_starts_with_letter_filters_by_business_name(self):
        response = self.client.get('/api/businesses/', {'starts_with': 'A'})
        self.assertEqual(response.status_code, 200)
        ids = [b['business_id'] for b in response.data['results']]
        self.assertIn(self.biz_a.pk, ids)
        self.assertNotIn(self.biz_b.pk, ids)

    def test_starts_with_digit_range_matches_digit_business_names(self):
        response = self.client.get('/api/businesses/', {'starts_with': '0-9'})
        ids = [b['business_id'] for b in response.data['results']]
        self.assertIn(self.biz_0.pk, ids)
        self.assertNotIn(self.biz_a.pk, ids)


class BusinessSearchTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        dc = Contact.objects.create(
            first_name='BizSrch', last_name='C',
            email='bizsrch@test.com', mobile_number='555-202-0001',
        )
        self.biz = Business.objects.create(
            business_name='Unique Biz Search Corp',
            business_phone='555-777-8888',
            default_contact=dc,
        )
        dc2 = Contact.objects.create(
            first_name='Other', last_name='C',
            email='other@test.com', mobile_number='555-202-0002',
        )
        self.other = Business.objects.create(
            business_name='Unrelated Biz', default_contact=dc2,
        )

    def _ids(self, response):
        return [b['business_id'] for b in response.data['results']]

    def test_search_by_business_name(self):
        r = self.client.get('/api/businesses/', {'search': 'Unique Biz Search'})
        self.assertIn(self.biz.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_search_by_reference_code(self):
        # our_reference_code is auto-generated; use whatever was assigned
        r = self.client.get('/api/businesses/', {'search': self.biz.our_reference_code})
        self.assertIn(self.biz.pk, self._ids(r))

    def test_search_by_phone_substring(self):
        r = self.client.get('/api/businesses/', {'search': '777-8888'})
        self.assertIn(self.biz.pk, self._ids(r))
        self.assertNotIn(self.other.pk, self._ids(r))

    def test_no_match_returns_empty(self):
        r = self.client.get('/api/businesses/', {'search': 'xyznosuchthing99999'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 0)


class ContactTagFilterTest(BaseTestCase):
    """Tests for ?tag= on GET /api/contacts/"""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        self.tag_vip = Tag.objects.create(name='vip-cf')
        self.tag_local = Tag.objects.create(name='local-cf')

        self.contact_both = Contact.objects.create(
            first_name='Both', last_name='Tags',
            email='both@tagfilter.com', mobile_number='555-300-0001',
        )
        self.contact_both.tags.add(self.tag_vip, self.tag_local)

        self.contact_vip_only = Contact.objects.create(
            first_name='Vip', last_name='Only',
            email='vip@tagfilter.com', mobile_number='555-300-0002',
        )
        self.contact_vip_only.tags.add(self.tag_vip)

        self.contact_none = Contact.objects.create(
            first_name='No', last_name='Tags',
            email='none@tagfilter.com', mobile_number='555-300-0003',
        )

    def _ids(self, response):
        return [c['contact_id'] for c in response.data['results']]

    def test_single_tag_returns_contacts_with_that_tag(self):
        r = self.client.get('/api/contacts/', {'tag': self.tag_vip.pk})
        ids = self._ids(r)
        self.assertIn(self.contact_both.pk, ids)
        self.assertIn(self.contact_vip_only.pk, ids)
        self.assertNotIn(self.contact_none.pk, ids)

    def test_multiple_tags_requires_all_tags(self):
        # AND logic: only contact_both has both tags
        r = self.client.get('/api/contacts/', [
            ('tag', self.tag_vip.pk),
            ('tag', self.tag_local.pk),
        ])
        ids = self._ids(r)
        self.assertIn(self.contact_both.pk, ids)
        self.assertNotIn(self.contact_vip_only.pk, ids)
        self.assertNotIn(self.contact_none.pk, ids)

    def test_no_tag_filter_returns_all(self):
        r = self.client.get('/api/contacts/')
        ids = self._ids(r)
        self.assertIn(self.contact_both.pk, ids)
        self.assertIn(self.contact_vip_only.pk, ids)
        self.assertIn(self.contact_none.pk, ids)

    def test_tag_filter_combined_with_search(self):
        r = self.client.get('/api/contacts/', {'tag': self.tag_vip.pk, 'search': 'Both'})
        ids = self._ids(r)
        self.assertIn(self.contact_both.pk, ids)
        self.assertNotIn(self.contact_vip_only.pk, ids)

    def test_tag_filter_combined_with_starts_with(self):
        r = self.client.get('/api/contacts/', {'tag': self.tag_vip.pk, 'starts_with': 'V'})
        ids = self._ids(r)
        self.assertIn(self.contact_vip_only.pk, ids)
        self.assertNotIn(self.contact_both.pk, ids)  # starts with 'B', not 'V'

    def test_tags_included_in_list_response(self):
        r = self.client.get('/api/contacts/')
        self.assertEqual(r.status_code, 200)
        target = next((c for c in r.data['results'] if c['contact_id'] == self.contact_both.pk), None)
        self.assertIsNotNone(target)
        tag_names = [t['name'] for t in target.get('tags', [])]
        self.assertIn('vip-cf', tag_names)
        self.assertIn('local-cf', tag_names)

    def test_unmatched_tag_returns_empty(self):
        tag_unused = Tag.objects.create(name='unused-cf')
        r = self.client.get('/api/contacts/', {'tag': tag_unused.pk})
        # Only contacts with this tag — none have it
        ids = self._ids(r)
        self.assertNotIn(self.contact_both.pk, ids)
        self.assertNotIn(self.contact_vip_only.pk, ids)
        self.assertNotIn(self.contact_none.pk, ids)


class BusinessTagFilterTest(BaseTestCase):
    """Tests for ?tag= on GET /api/businesses/"""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        self.tag_key = Tag.objects.create(name='key-account-bf')
        self.tag_local = Tag.objects.create(name='local-bf')

        dc1 = Contact.objects.create(first_name='BF1', last_name='C', email='bf1@t.com', mobile_number='555-301-0001')
        dc2 = Contact.objects.create(first_name='BF2', last_name='C', email='bf2@t.com', mobile_number='555-301-0002')
        dc3 = Contact.objects.create(first_name='BF3', last_name='C', email='bf3@t.com', mobile_number='555-301-0003')

        self.biz_both = Business.objects.create(business_name='BF Both Tags Corp', default_contact=dc1)
        self.biz_both.tags.add(self.tag_key, self.tag_local)

        self.biz_one = Business.objects.create(business_name='BF One Tag Corp', default_contact=dc2)
        self.biz_one.tags.add(self.tag_key)

        self.biz_none = Business.objects.create(business_name='BF No Tags Corp', default_contact=dc3)

    def _ids(self, response):
        return [b['business_id'] for b in response.data['results']]

    def test_single_tag_returns_businesses_with_that_tag(self):
        r = self.client.get('/api/businesses/', {'tag': self.tag_key.pk})
        ids = self._ids(r)
        self.assertIn(self.biz_both.pk, ids)
        self.assertIn(self.biz_one.pk, ids)
        self.assertNotIn(self.biz_none.pk, ids)

    def test_multiple_tags_requires_all_tags(self):
        r = self.client.get('/api/businesses/', [
            ('tag', self.tag_key.pk),
            ('tag', self.tag_local.pk),
        ])
        ids = self._ids(r)
        self.assertIn(self.biz_both.pk, ids)
        self.assertNotIn(self.biz_one.pk, ids)
        self.assertNotIn(self.biz_none.pk, ids)

    def test_no_tag_filter_returns_all(self):
        r = self.client.get('/api/businesses/')
        ids = self._ids(r)
        self.assertIn(self.biz_both.pk, ids)
        self.assertIn(self.biz_one.pk, ids)
        self.assertIn(self.biz_none.pk, ids)

    def test_tags_included_in_list_response(self):
        r = self.client.get('/api/businesses/')
        self.assertEqual(r.status_code, 200)
        target = next((b for b in r.data['results'] if b['business_id'] == self.biz_both.pk), None)
        self.assertIsNotNone(target)
        tag_names = [t['name'] for t in target.get('tags', [])]
        self.assertIn('key-account-bf', tag_names)
        self.assertIn('local-bf', tag_names)
