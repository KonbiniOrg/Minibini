from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Task, PlanTask
from apps.estimates.models import Estimate, EstWorksheet
from apps.contacts.models import Contact, Business
from apps.invoicing.models import Invoice
from apps.inventory.models import PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill
from apps.core.models import AccountingCategory, User
from decimal import Decimal


class SearchViewTests(TestCase):
    """Test cases for the search functionality"""

    def setUp(self):
        """Set up test data for search tests"""
        self.client = Client()

        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

        # Create contact first (needed for business default_contact)
        self.contact1 = Contact.objects.create(
            first_name='John Doe',
            last_name='',
            email='john.doe@example.com',
            mobile_number='555-0001',
            addr1='456 Oak Ave',
            city='Springfield',
            postal_code='12345'
        )

        # Create a business with default contact
        self.business = Business.objects.create(
            business_name='Acme Corporation',
            our_reference_code='ACME001',
            business_address='123 Main St, Springfield',
            business_phone='555-1234',
            default_contact=self.contact1
        )

        # Link contact to business
        self.contact1.business = self.business
        self.contact1.save()

        self.contact2 = Contact.objects.create(
            first_name='Jane Smith',
            last_name='',
            email='jane.smith@example.com',
            work_number='555-0002',
            addr1='789 Pine St',
            city='Shelbyville',
            postal_code='67890'
        )

        # Create jobs
        self.job1 = Job.objects.create(
            job_number='JOB-001',
            contact=self.contact1,
            customer_po_number='PO-12345',
            description='Custom furniture project for office'
        )

        self.job2 = Job.objects.create(
            job_number='JOB-002',
            contact=self.contact2,
            customer_po_number='PO-67890',
            description='Residential table and chairs'
        )

        # Create estimates
        self.estimate1 = Estimate.objects.create(
            job=self.job1,
            estimate_number='EST-001',
            version=1
        )

        self.estimate2 = Estimate.objects.create(
            job=self.job2,
            estimate_number='EST-002',
            version=1
        )

        # Create tasks directly on job1 (replacing former work-order tasks)
        self.job_task1 = Task.objects.create(
            name='Install fixtures',
            job=self.job1,
            units='hours',
            rate=Decimal('45.00')
        )
        self.job_task2 = Task.objects.create(
            name='Paint walls',
            job=self.job1,
            units='hours',
            rate=Decimal('40.00')
        )
        # A task on job2 for cross-job isolation checks
        self.job2_task = Task.objects.create(
            name='Deliver chairs',
            job=self.job2,
            units='ea',
            rate=Decimal('20.00')
        )

        # Create est worksheets
        self.worksheet1 = EstWorksheet.objects.create(
            job=self.job1,
            estimate=self.estimate1,
            version=1
        )

        # Create plan tasks on the worksheet
        self.task1 = PlanTask.objects.create(
            name='Cut wood pieces',
            est_worksheet=self.worksheet1,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('10.00')
        )

        self.task2 = PlanTask.objects.create(
            name='Assemble furniture',
            est_worksheet=self.worksheet1,
            units='hours',
            rate=Decimal('60.00'),
            est_qty=Decimal('5.00')
        )

        # Create invoices
        self.invoice1 = Invoice.objects.create(
            job=self.job1,
            invoice_number='INV-001'
        )

        # Create price list items
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.price_item1 = PriceListItem.objects.create(
            code='WOOD-001',
            description='Oak plank 2x4x8',
            units='pcs',
            purchase_price=Decimal('15.00'),
            selling_price=Decimal('25.00'),
            accounting_category=self.category
        )

        self.price_item2 = PriceListItem.objects.create(
            code='HARDWARE-001',
            description='Wood screws box of 100',
            units='ea',
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            accounting_category=self.category
        )

        # Create purchase orders
        self.po1 = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-2024-001'
        )
        # Transition PO to issued status so bills can be created from it
        PurchaseOrderLineItem.objects.create(purchase_order=self.po1, description='Test item', price=Decimal('100.00'))
        self.po1.status = PurchaseOrder.STATUS_ISSUED
        self.po1.save()

        # Create bills
        self.bill1 = Bill.objects.create(
            bill_number='BILL-2024-001',
            purchase_order=self.po1,
            business=self.business,
            contact=self.contact1,
            vendor_invoice_number='VENDOR-INV-001'
        )

    def test_search_url_resolves(self):
        """Test that the search URL resolves correctly"""
        url = reverse('search:search')
        self.assertEqual(url, '/search/')

    def test_search_view_returns_200(self):
        """Test that search view returns successful response"""
        response = self.client.get(reverse('search:search'))
        self.assertEqual(response.status_code, 200)

    def test_search_with_empty_query(self):
        """Test search with no query returns empty results"""
        response = self.client.get(reverse('search:search'), {'q': ''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 0)
        self.assertContains(response, 'Please enter a search query')

    def _job_parents(self, response):
        """Helper: extract parent Jobs from the grouped jobs category."""
        groups = response.context['categories'].get('jobs', {}).get('grouped_items', [])
        return [g['parent'] for g in groups]

    def _job_group_for(self, response, job):
        """Helper: return the grouped entry for a given Job, or None."""
        groups = response.context['categories'].get('jobs', {}).get('grouped_items', [])
        for g in groups:
            if g['parent'].pk == job.pk:
                return g
        return None

    def test_search_jobs_by_job_number(self):
        """Test searching jobs by job number"""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)
        parents = self._job_parents(response)
        self.assertIn(self.job1, parents)
        self.assertNotIn(self.job2, parents)
        self.assertContains(response, 'JOB-001')

    def test_search_jobs_case_insensitive(self):
        """Test that job search is case-insensitive"""
        response = self.client.get(reverse('search:search'), {'q': 'job-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, self._job_parents(response))

        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, self._job_parents(response))

    def test_search_jobs_by_description(self):
        """Test searching jobs by description text"""
        response = self.client.get(reverse('search:search'), {'q': 'table'})
        self.assertEqual(response.status_code, 200)
        parents = self._job_parents(response)
        # job2 has "table" in description
        self.assertIn(self.job2, parents)
        self.assertNotIn(self.job1, parents)

    def test_search_jobs_by_customer_po(self):
        """Test searching jobs by customer PO number"""
        response = self.client.get(reverse('search:search'), {'q': 'PO-12345'})
        self.assertEqual(response.status_code, 200)
        parents = self._job_parents(response)
        self.assertIn(self.job1, parents)
        self.assertNotIn(self.job2, parents)

    def test_search_jobs_by_customer_po_number(self):
        """A job with a unique customer_po_number surfaces via grouped jobs search."""
        job = Job.objects.create(
            job_number='JOB-PO-X',
            contact=self.contact1,
            customer_po_number='PO-9999',
            description='unrelated description'
        )
        # Full token
        response = self.client.get(reverse('search:search'), {'q': 'PO-9999'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(job, self._job_parents(response))
        # Partial substring
        response = self.client.get(reverse('search:search'), {'q': '9999'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(job, self._job_parents(response))

    def test_search_jobs_by_contact_last_name(self):
        """A job whose contact has a distinctive last_name surfaces via grouped jobs search."""
        contact = Contact.objects.create(
            first_name='Alice',
            last_name='Smithson',
            email='alice.smithson@example.com'
        )
        job = Job.objects.create(
            job_number='JOB-7777',
            contact=contact,
            description='unrelated description'
        )
        # Case-insensitive partial match on last_name
        response = self.client.get(reverse('search:search'), {'q': 'smith'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(job, self._job_parents(response))

    def test_search_jobs_grouped_shape_contains_tasks(self):
        """Query matching a task name surfaces the task under its parent Job."""
        response = self.client.get(reverse('search:search'), {'q': 'Install fixtures'})
        self.assertEqual(response.status_code, 200)
        group = self._job_group_for(response, self.job1)
        self.assertIsNotNone(group, 'job1 should be present as a parent')
        self.assertIn(self.job_task1, group['tasks'])
        self.assertNotIn(self.job_task2, group['tasks'])

    def test_search_jobs_matching_description_only_has_empty_task_list(self):
        """A job matching by description (with no matching tasks) has tasks=[]."""
        # 'office' appears in job1.description but not in any task fields.
        response = self.client.get(reverse('search:search'), {'q': 'office'})
        self.assertEqual(response.status_code, 200)
        group = self._job_group_for(response, self.job1)
        self.assertIsNotNone(group)
        self.assertEqual(group['tasks'], [])

    def test_search_jobs_multiple_tasks_grouped_under_one_job(self):
        """Two tasks on the same job appear under ONE job entry, not two."""
        # Both job_task1 and job_task2 have units='hours'
        response = self.client.get(reverse('search:search'), {'q': 'hours'})
        self.assertEqual(response.status_code, 200)
        groups = response.context['categories'].get('jobs', {}).get('grouped_items', [])
        job1_groups = [g for g in groups if g['parent'].pk == self.job1.pk]
        self.assertEqual(len(job1_groups), 1, 'job1 should appear exactly once')
        task_ids = {t.pk for t in job1_groups[0]['tasks']}
        self.assertIn(self.job_task1.pk, task_ids)
        self.assertIn(self.job_task2.pk, task_ids)

    def test_work_orders_category_absent(self):
        """The 'work_orders' category is no longer part of search results."""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('work_orders', response.context['categories'])

    def test_work_orders_category_filter_returns_empty(self):
        """Filtering by the removed 'work_orders' category yields no results."""
        response = self.client.get(
            reverse('search:search'),
            {'q': 'JOB-001', 'category': 'work_orders'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['categories'], {})

    def test_search_contacts_by_name(self):
        """Test searching contacts by name"""
        response = self.client.get(reverse('search:search'), {'q': 'John Doe'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contact1, response.context['categories']['contacts']['items'])
        self.assertNotIn(self.contact2, response.context['categories']['contacts']['items'])

    def test_search_contacts_by_email(self):
        """Test searching contacts by email address"""
        response = self.client.get(reverse('search:search'), {'q': 'jane.smith@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contact2, response.context['categories']['contacts']['items'])
        self.assertNotIn(self.contact1, response.context['categories']['contacts']['items'])

    def test_search_contacts_by_phone(self):
        """Test searching contacts by phone number"""
        response = self.client.get(reverse('search:search'), {'q': '555-0001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contact1, response.context['categories']['contacts']['items'])

    def test_search_contacts_by_city(self):
        """Test searching contacts by city"""
        response = self.client.get(reverse('search:search'), {'q': 'Springfield'})
        self.assertEqual(response.status_code, 200)
        contacts = list(response.context['categories']['contacts']['items'])
        self.assertIn(self.contact1, contacts)
        # Also check if business is found
        self.assertIn(self.business, list(response.context['categories']['businesses']['items']))

    def test_search_businesses_by_name(self):
        """Test searching businesses by business name"""
        response = self.client.get(reverse('search:search'), {'q': 'Acme'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.business, response.context['categories']['businesses']['items'])

    def test_search_businesses_by_reference_code(self):
        """Test searching businesses by reference code"""
        response = self.client.get(reverse('search:search'), {'q': 'ACME001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.business, response.context['categories']['businesses']['items'])

    def test_search_estimates_by_estimate_number(self):
        """Test searching estimates by estimate number"""
        response = self.client.get(reverse('search:search'), {'q': 'EST-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.estimate1, response.context['categories']['estimates']['grouped_items'])
        self.assertNotIn(self.estimate2, response.context['categories']['estimates']['grouped_items'])

    def test_search_estimates_by_job_number(self):
        """Test searching estimates by associated job number"""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-002'})
        self.assertEqual(response.status_code, 200)
        # Should find both the job and its estimate
        self.assertIn(self.job2, self._job_parents(response))
        self.assertIn(self.estimate2, response.context['categories']['estimates']['grouped_items'])

    def test_search_invoices_by_invoice_number(self):
        """Test searching invoices by invoice number"""
        response = self.client.get(reverse('search:search'), {'q': 'INV-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.invoice1, response.context['categories']['invoices']['grouped_items'])

    def test_search_price_list_items_by_code(self):
        """Test searching price list items by item code"""
        response = self.client.get(reverse('search:search'), {'q': 'WOOD-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.price_item1, response.context['categories']['price_list_items']['items'])
        self.assertNotIn(self.price_item2, response.context['categories']['price_list_items']['items'])

    def test_search_price_list_items_by_description(self):
        """Test searching price list items by description"""
        response = self.client.get(reverse('search:search'), {'q': 'screws'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.price_item2, response.context['categories']['price_list_items']['items'])
        self.assertNotIn(self.price_item1, response.context['categories']['price_list_items']['items'])

    def test_search_purchase_orders_by_po_number(self):
        """Test searching purchase orders by PO number"""
        response = self.client.get(reverse('search:search'), {'q': 'PO-2024-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.po1, response.context['categories']['purchase_orders']['items'])

    def test_search_bills_by_vendor_invoice(self):
        """Test searching bills by vendor invoice number"""
        response = self.client.get(reverse('search:search'), {'q': 'VENDOR-INV-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.bill1, response.context['categories']['bills']['items'])

    def test_search_partial_match(self):
        """Test that partial matches work correctly"""
        response = self.client.get(reverse('search:search'), {'q': 'Oak'})
        self.assertEqual(response.status_code, 200)
        # Should match "Oak plank 2x4x8"
        self.assertIn(self.price_item1, response.context['categories']['price_list_items']['items'])

    def test_search_multiple_results_across_models(self):
        """Test search that returns results from multiple model types"""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)

        # Should find job, estimate, worksheet, invoice
        self.assertIn(self.job1, self._job_parents(response))
        self.assertIn(self.estimate1, response.context['categories']['estimates']['grouped_items'])
        self.assertIn(self.worksheet1, response.context['categories']['est_worksheets'])
        self.assertIn(self.invoice1, response.context['categories']['invoices']['grouped_items'])

        # Total count should reflect all matches
        self.assertGreater(response.context['total_count'], 1)

    def test_search_total_count_accuracy(self):
        """Test that total_count accurately reflects number of results"""
        response = self.client.get(reverse('search:search'), {'q': 'furniture'})
        self.assertEqual(response.status_code, 200)

        # Count manually
        expected_count = (
            len(response.context['categories'].get('jobs', {}).get('grouped_items', [])) +
            len(response.context['categories'].get('estimates', {}).get('grouped_items', [])) +
            len(response.context['categories'].get('est_worksheets', [])) +
            len(response.context['categories'].get('contacts', {}).get('items', [])) +
            len(response.context['categories'].get('businesses', {}).get('items', [])) +
            len(response.context['categories'].get('invoices', {}).get('grouped_items', [])) +
            len(response.context['categories'].get('price_list_items', {}).get('items', [])) +
            len(response.context['categories'].get('purchase_orders', {}).get('items', [])) +
            len(response.context['categories'].get('bills', {}).get('items', []))
        )

        self.assertEqual(response.context['total_count'], expected_count)

    def test_search_no_results(self):
        """Test search with query that has no matches"""
        response = self.client.get(reverse('search:search'), {'q': 'NONEXISTENT12345'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 0)
        self.assertContains(response, 'No results found')

    def test_search_numeric_query(self):
        """Test searching with numeric values"""
        response = self.client.get(reverse('search:search'), {'q': '12345'})
        self.assertEqual(response.status_code, 200)
        # Should match postal code (contact) and customer_po_number (job).
        self.assertIn(self.contact1, response.context['categories']['contacts']['items'])
        self.assertIn(self.job1, self._job_parents(response))

    def test_search_special_characters(self):
        """Test searching with special characters like hyphens"""
        response = self.client.get(reverse('search:search'), {'q': 'PO-2024-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.po1, response.context['categories']['purchase_orders']['items'])

    def test_search_whitespace_handling(self):
        """Test that leading/trailing whitespace is handled properly"""
        response1 = self.client.get(reverse('search:search'), {'q': '  JOB-001  '})
        response2 = self.client.get(reverse('search:search'), {'q': 'JOB-001'})

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        # Both should return same results
        groups1 = response1.context['categories'].get('jobs', {}).get('grouped_items', [])
        groups2 = response2.context['categories'].get('jobs', {}).get('grouped_items', [])
        self.assertEqual(
            [g['parent'].pk for g in groups1],
            [g['parent'].pk for g in groups2]
        )

    def test_search_context_structure(self):
        """Test that the response context has the correct structure"""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)

        # Check that all expected top-level keys are present
        self.assertIn('query', response.context)
        self.assertIn('categories', response.context)
        self.assertIn('total_count', response.context)

        # Check that categories dict exists and has some results
        categories = response.context['categories']
        self.assertIsInstance(categories, dict)

        # Since we searched for 'JOB-001', we should at least have jobs category
        self.assertIn('jobs', categories)
        self.assertIn('grouped_items', categories['jobs'])

    def test_search_template_used(self):
        """Test that the correct template is used"""
        response = self.client.get(reverse('search:search'), {'q': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'search/search_results.html')

    def test_category_numeric_mapping_exists(self):
        """Test that category numeric mappings are properly defined"""
        from apps.search.services import SearchService

        # Verify all category constants are defined
        self.assertGreater(SearchService.CATEGORY_BUSINESSES, 0)
        self.assertGreater(SearchService.CATEGORY_CONTACTS, 0)
        self.assertGreater(SearchService.CATEGORY_JOBS, 0)

        # Verify bidirectional mappings
        for cat_id, cat_key in SearchService.CATEGORY_ID_TO_KEY.items():
            self.assertEqual(SearchService.CATEGORY_KEY_TO_ID[cat_key], cat_id)

    def test_category_id_from_string_case_insensitive(self):
        """Test that category string lookup is case-insensitive"""
        from apps.search.services import SearchService

        # Test with different cases
        jobs_id_lower = SearchService.get_category_id_from_string('jobs')
        jobs_id_upper = SearchService.get_category_id_from_string('JOBS')
        jobs_id_mixed = SearchService.get_category_id_from_string('JoBs')

        self.assertIsNotNone(jobs_id_lower)
        self.assertEqual(jobs_id_lower, jobs_id_upper)
        self.assertEqual(jobs_id_lower, jobs_id_mixed)

        # Test with whitespace
        jobs_id_space = SearchService.get_category_id_from_string('  jobs  ')
        self.assertEqual(jobs_id_lower, jobs_id_space)

    def test_category_id_conversion_methods(self):
        """Test category ID conversion helper methods"""
        from apps.search.services import SearchService

        # Test get_category_key_from_id
        jobs_key = SearchService.get_category_key_from_id(SearchService.CATEGORY_JOBS)
        self.assertEqual(jobs_key, 'jobs')

        # Test get_category_display_name
        jobs_display = SearchService.get_category_display_name(SearchService.CATEGORY_JOBS)
        self.assertEqual(jobs_display, 'Jobs')

        # Test invalid ID
        invalid_key = SearchService.get_category_key_from_id(99999)
        self.assertIsNone(invalid_key)

    def test_category_filter_with_different_cases(self):
        """Test that category filtering works with different string cases"""
        from apps.search.services import SearchService

        # Create sample categories
        categories = {
            'jobs': {'items': [self.job1]},
            'contacts': {'items': [self.contact1]},
        }

        # Test with lowercase
        result_lower = SearchService.apply_category_filter(categories, 'jobs')
        self.assertIn('jobs', result_lower)
        self.assertNotIn('contacts', result_lower)

        # Test with uppercase
        result_upper = SearchService.apply_category_filter(categories, 'JOBS')
        self.assertIn('jobs', result_upper)
        self.assertNotIn('contacts', result_upper)

        # Test with mixed case
        result_mixed = SearchService.apply_category_filter(categories, 'JoBs')
        self.assertIn('jobs', result_mixed)
        self.assertNotIn('contacts', result_mixed)

    def test_get_all_category_info(self):
        """Test that get_all_category_info returns structured data"""
        from apps.search.services import SearchService

        category_info = SearchService.get_all_category_info()

        # Should return a list of dicts
        self.assertIsInstance(category_info, list)
        self.assertGreater(len(category_info), 0)

        # Each item should have id, key, and display_name
        for item in category_info:
            self.assertIn('id', item)
            self.assertIn('key', item)
            self.assertIn('display_name', item)
            self.assertIsInstance(item['id'], int)
            self.assertIsInstance(item['key'], str)
            self.assertIsInstance(item['display_name'], str)
