"""Tests for search filter refinement: date range, start date, job status, and search-within filters."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact, Business
from apps.core.models import User, AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, Task
from apps.search.services import SearchService
from tests.base import BaseTestCase


class JobStatusFilterServiceTest(BaseTestCase):
    """Unit tests for SearchService.apply_job_status_filter."""

    def setUp(self):
        super().setUp()
        contact = Contact.objects.create(first_name='Alice', last_name='Smith')
        self.job_draft = Job.objects.create(
            job_number='FILT-001',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        self.job_approved = Job.objects.create(
            job_number='FILT-002',
            contact=contact,
            status=Job.STATUS_APPROVED,
        )
        self.job_completed = Job.objects.create(
            job_number='FILT-003',
            contact=contact,
            status=Job.STATUS_COMPLETED,
        )
        self.categories = {
            'jobs': {
                'grouped_items': [
                    {'parent': self.job_draft, 'tasks': []},
                    {'parent': self.job_approved, 'tasks': []},
                    {'parent': self.job_completed, 'tasks': []},
                ]
            }
        }

    def test_single_status_filter(self):
        result = SearchService.apply_job_status_filter(self.categories, ['draft'])
        jobs = result['jobs']['grouped_items']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['parent'].status, Job.STATUS_DRAFT)

    def test_multiple_status_filter(self):
        result = SearchService.apply_job_status_filter(self.categories, ['draft', 'approved'])
        jobs = result['jobs']['grouped_items']
        self.assertEqual(len(jobs), 2)
        statuses = {g['parent'].status for g in jobs}
        self.assertIn(Job.STATUS_DRAFT, statuses)
        self.assertIn(Job.STATUS_APPROVED, statuses)

    def test_no_status_filter_returns_all(self):
        result = SearchService.apply_job_status_filter(self.categories, [])
        self.assertEqual(len(result['jobs']['grouped_items']), 3)

    def test_status_filter_non_jobs_categories_unchanged(self):
        business = Business.objects.create(
            business_name='Test Corp',
            default_contact=Contact.objects.create(first_name='Bob', last_name='Jones'),
        )
        categories_with_businesses = dict(self.categories)
        categories_with_businesses['businesses'] = {'items': [business], 'subcategories': {}}
        result = SearchService.apply_job_status_filter(categories_with_businesses, ['draft'])
        self.assertIn('businesses', result)
        self.assertEqual(result['businesses']['items'], [business])

    def test_empty_result_after_filter_drops_jobs_key(self):
        result = SearchService.apply_job_status_filter(self.categories, ['cancelled'])
        self.assertNotIn('jobs', result)


class StartDateFilterServiceTest(BaseTestCase):
    """Unit tests for SearchService.apply_start_date_filter."""

    def setUp(self):
        super().setUp()
        contact = Contact.objects.create(first_name='Carol', last_name='White')
        now = timezone.now()
        self.job_started_early = Job.objects.create(
            job_number='SD-001',
            contact=contact,
            status=Job.STATUS_APPROVED,
            start_date=now - timedelta(days=30),
        )
        self.job_started_recent = Job.objects.create(
            job_number='SD-002',
            contact=contact,
            status=Job.STATUS_APPROVED,
            start_date=now - timedelta(days=5),
        )
        self.job_no_start = Job.objects.create(
            job_number='SD-003',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        self.categories = {
            'jobs': {
                'grouped_items': [
                    {'parent': self.job_started_early, 'tasks': []},
                    {'parent': self.job_started_recent, 'tasks': []},
                    {'parent': self.job_no_start, 'tasks': []},
                ]
            }
        }

    def test_start_date_from_excludes_older(self):
        cutoff = (timezone.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        result = SearchService.apply_start_date_filter(self.categories, cutoff, None)
        jobs = result['jobs']['grouped_items']
        # Only job_started_recent passes; job_no_start has no start_date so passes through
        numbers = {g['parent'].job_number for g in jobs}
        self.assertNotIn('SD-001', numbers)
        self.assertIn('SD-002', numbers)

    def test_start_date_to_excludes_newer(self):
        cutoff = (timezone.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        result = SearchService.apply_start_date_filter(self.categories, None, cutoff)
        jobs = result['jobs']['grouped_items']
        numbers = {g['parent'].job_number for g in jobs}
        self.assertIn('SD-001', numbers)
        self.assertNotIn('SD-002', numbers)

    def test_no_start_date_filter_returns_all(self):
        result = SearchService.apply_start_date_filter(self.categories, None, None)
        self.assertEqual(len(result['jobs']['grouped_items']), 3)

    def test_non_jobs_categories_unchanged(self):
        business = Business.objects.create(
            business_name='SD Corp',
            default_contact=Contact.objects.create(first_name='Dave', last_name='Green'),
        )
        cats = dict(self.categories)
        cats['businesses'] = {'items': [business], 'subcategories': {}}
        cutoff = (timezone.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        result = SearchService.apply_start_date_filter(cats, cutoff, None)
        self.assertIn('businesses', result)


class SearchAPIFilterTest(BaseTestCase):
    """Integration tests for filter params on GET /api/search/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        contact = Contact.objects.create(first_name='Eve', last_name='Brown')
        self.job_draft = Job.objects.create(
            job_number='API-FILT-001',
            contact=contact,
            description='filterable draft job',
            status=Job.STATUS_DRAFT,
        )
        self.job_approved = Job.objects.create(
            job_number='API-FILT-002',
            contact=contact,
            description='filterable approved job',
            status=Job.STATUS_APPROVED,
            start_date=timezone.now(),
        )

    def test_job_status_filter_returns_only_matching(self):
        response = self.client.get('/api/search/', {'q': 'filterable', 'job_status': 'draft'})
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        for group in jobs:
            self.assertEqual(group['job']['status'], Job.STATUS_DRAFT)

    def test_date_from_filter_accepted(self):
        response = self.client.get('/api/search/', {
            'q': 'filterable',
            'date_from': '2000-01-01',
        })
        self.assertEqual(response.status_code, 200)

    def test_start_date_from_filter_returns_only_started_jobs(self):
        # job_approved has start_date=now; job_draft has no start_date
        future = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        response = self.client.get('/api/search/', {
            'q': 'filterable',
            'start_date_to': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
            'start_date_from': timezone.now().strftime('%Y-%m-%d'),
        })
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        numbers = [g['job']['job_number'] for g in jobs]
        # job_approved should be present (has start_date today), job_draft should not
        self.assertIn('API-FILT-002', numbers)
        self.assertNotIn('API-FILT-001', numbers)

    def test_job_summary_includes_start_date_and_created_date(self):
        response = self.client.get('/api/search/', {'q': 'filterable'})
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        self.assertTrue(len(jobs) > 0)
        job_data = jobs[0]['job']
        self.assertIn('start_date', job_data)
        self.assertIn('created_date', job_data)


class SearchWithinAPITest(BaseTestCase):
    """Tests for the `within` param that narrows results of an initial search."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        contact = Contact.objects.create(first_name='Frank', last_name='Castle')
        self.job_alpha = Job.objects.create(
            job_number='WI-001',
            contact=contact,
            description='within test alpha job',
        )
        self.job_beta = Job.objects.create(
            job_number='WI-002',
            contact=contact,
            description='within test beta job',
        )

    def test_within_narrows_to_matching_subset(self):
        response = self.client.get('/api/search/', {'q': 'within test', 'within': 'alpha'})
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        numbers = [g['job']['job_number'] for g in jobs]
        self.assertIn('WI-001', numbers)
        self.assertNotIn('WI-002', numbers)

    def test_within_with_no_matches_returns_zero(self):
        response = self.client.get('/api/search/', {'q': 'within test', 'within': 'zzznomatch'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 0)

    def test_without_within_returns_all(self):
        response = self.client.get('/api/search/', {'q': 'within test'})
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        numbers = [g['job']['job_number'] for g in jobs]
        self.assertIn('WI-001', numbers)
        self.assertIn('WI-002', numbers)

    def test_within_combines_with_other_filters(self):
        """within should operate on already-filtered results."""
        contact = Contact.objects.create(first_name='Gina', last_name='Miles')
        Job.objects.create(
            job_number='WI-003',
            contact=contact,
            description='within test alpha job',
            status=Job.STATUS_APPROVED,
            start_date=timezone.now(),
        )
        # category=jobs + within=alpha: WI-001 (draft) and WI-003 (approved) both match
        response = self.client.get('/api/search/', {
            'q': 'within test',
            'within': 'alpha',
            'job_status': Job.STATUS_APPROVED,
        })
        self.assertEqual(response.status_code, 200)
        jobs = response.data['results'].get('jobs', [])
        numbers = [g['job']['job_number'] for g in jobs]
        self.assertIn('WI-003', numbers)
        self.assertNotIn('WI-001', numbers)
        self.assertNotIn('WI-002', numbers)


class PriceFilterServiceTest(BaseTestCase):
    """Unit tests for SearchService.apply_price_filter."""

    def setUp(self):
        super().setUp()
        cat = AccountingCategory.objects.first()
        self.cheap = InventoryItem.objects.create(
            code='CHEAP', description='price filter cheap item',
            selling_price=Decimal('5.00'), accounting_category=cat
        )
        self.mid = InventoryItem.objects.create(
            code='MID', description='price filter mid item',
            selling_price=Decimal('50.00'), accounting_category=cat
        )
        self.expensive = InventoryItem.objects.create(
            code='EXP', description='price filter expensive item',
            selling_price=Decimal('500.00'), accounting_category=cat
        )
        self.categories = {
            'inventory_items': {
                'items': [self.cheap, self.mid, self.expensive],
                'subcategories': {}
            }
        }

    def test_price_min_excludes_cheaper(self):
        result = SearchService.apply_price_filter(self.categories, Decimal('10'), None)
        codes = [i.code for i in result['inventory_items']['items']]
        self.assertNotIn('CHEAP', codes)
        self.assertIn('MID', codes)
        self.assertIn('EXP', codes)

    def test_price_max_excludes_pricier(self):
        result = SearchService.apply_price_filter(self.categories, None, Decimal('100'))
        codes = [i.code for i in result['inventory_items']['items']]
        self.assertIn('CHEAP', codes)
        self.assertIn('MID', codes)
        self.assertNotIn('EXP', codes)

    def test_price_range(self):
        result = SearchService.apply_price_filter(self.categories, Decimal('10'), Decimal('100'))
        codes = [i.code for i in result['inventory_items']['items']]
        self.assertEqual(codes, ['MID'])

    def test_no_price_filter_returns_all(self):
        result = SearchService.apply_price_filter(self.categories, None, None)
        self.assertEqual(len(result['inventory_items']['items']), 3)

    def test_non_price_categories_unchanged(self):
        contact = Contact.objects.create(first_name='Zara', last_name='Price')
        cats = dict(self.categories)
        cats['contacts'] = {'items': [contact], 'subcategories': {}}
        result = SearchService.apply_price_filter(cats, Decimal('1000'), None)
        self.assertIn('contacts', result)

    def test_line_item_entities_filtered_by_matching_line_item_price(self):
        cat = AccountingCategory.objects.first()
        contact = Contact.objects.create(first_name='Joe', last_name='Filter')
        job = Job.objects.create(job_number='PF-001', contact=contact, description='price filter estimate job')
        estimate = Estimate.objects.create(job=job, estimate_number='PF-EST-001', version=1)
        cheap_li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='cheap line',
            price=Decimal('5.00'), qty=1, accounting_category=cat
        )
        estimate.matching_line_items = [cheap_li]
        cats = {'estimates': {'grouped_items': [estimate]}}
        # price_min=100 should exclude it since the only matching line item is $5
        result = SearchService.apply_price_filter(cats, Decimal('100'), None)
        self.assertNotIn('estimates', result)

    def test_entity_with_no_matching_line_items_passes_price_filter(self):
        """Entity matched on header fields (no line items) should not be filtered out."""
        contact = Contact.objects.create(first_name='Kay', last_name='Header')
        job = Job.objects.create(job_number='PF-002', contact=contact, description='price filter header match')
        estimate = Estimate.objects.create(job=job, estimate_number='PF-EST-002', version=1)
        estimate.matching_line_items = []  # matched on estimate_number, not line items
        cats = {'estimates': {'grouped_items': [estimate]}}
        result = SearchService.apply_price_filter(cats, Decimal('1000'), None)
        self.assertIn('estimates', result)


class PriceFilterAPITest(BaseTestCase):
    """Integration tests for price_min / price_max params on GET /api/search/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        cat = AccountingCategory.objects.first()
        InventoryItem.objects.create(
            code='SRCH-CHEAP', description='searchable price item cheap',
            selling_price=Decimal('5.00'), accounting_category=cat
        )
        InventoryItem.objects.create(
            code='SRCH-EXP', description='searchable price item expensive',
            selling_price=Decimal('999.00'), accounting_category=cat
        )

    def test_price_min_filters_inventory_items(self):
        response = self.client.get('/api/search/', {'q': 'searchable price item', 'price_min': '100'})
        self.assertEqual(response.status_code, 200)
        items = response.data['results'].get('inventory_items', [])
        codes = [i['code'] for i in items]
        self.assertIn('SRCH-EXP', codes)
        self.assertNotIn('SRCH-CHEAP', codes)

    def test_price_max_filters_inventory_items(self):
        response = self.client.get('/api/search/', {'q': 'searchable price item', 'price_max': '100'})
        self.assertEqual(response.status_code, 200)
        items = response.data['results'].get('inventory_items', [])
        codes = [i['code'] for i in items]
        self.assertIn('SRCH-CHEAP', codes)
        self.assertNotIn('SRCH-EXP', codes)

    def test_no_price_filter_returns_all(self):
        response = self.client.get('/api/search/', {'q': 'searchable price item'})
        self.assertEqual(response.status_code, 200)
        items = response.data['results'].get('inventory_items', [])
        codes = [i['code'] for i in items]
        self.assertIn('SRCH-CHEAP', codes)
        self.assertIn('SRCH-EXP', codes)
