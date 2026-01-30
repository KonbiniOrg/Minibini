from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Estimate, Task, WorkOrder, EstWorksheet
from apps.contacts.models import Contact, Business
from apps.invoicing.models import Invoice, PriceListItem
from apps.purchasing.models import PurchaseOrder, Bill
from apps.core.models import User
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

        # Create work orders
        self.work_order1 = WorkOrder.objects.create(
            job=self.job1
        )

        # Create est worksheets
        self.worksheet1 = EstWorksheet.objects.create(
            job=self.job1,
            estimate=self.estimate1,
            version=1
        )

        # Create tasks
        self.task1 = Task.objects.create(
            name='Cut wood pieces',
            est_worksheet=self.worksheet1,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('10.00'),
            assignee=self.user
        )

        self.task2 = Task.objects.create(
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
        self.price_item1 = PriceListItem.objects.create(
            code='WOOD-001',
            description='Oak plank 2x4x8',
            units='piece',
            purchase_price=Decimal('15.00'),
            selling_price=Decimal('25.00')
        )

        self.price_item2 = PriceListItem.objects.create(
            code='HARDWARE-001',
            description='Wood screws box of 100',
            units='box',
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00')
        )

        # Create purchase orders
        self.po1 = PurchaseOrder.objects.create(
            business=self.business,
            job=self.job1,
            po_number='PO-2024-001'
        )
        # Transition PO to issued status so bills can be created from it
        self.po1.status = 'issued'
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

    def test_search_jobs_by_job_number(self):
        """Test searching jobs by job number"""
        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])
        self.assertNotIn(self.job2, response.context['categories']['jobs']['items'])
        self.assertContains(response, 'JOB-001')

    def test_search_jobs_case_insensitive(self):
        """Test that job search is case-insensitive"""
        response = self.client.get(reverse('search:search'), {'q': 'job-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])

        response = self.client.get(reverse('search:search'), {'q': 'JOB-001'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])

    def test_search_jobs_by_description(self):
        """Test searching jobs by description text"""
        response = self.client.get(reverse('search:search'), {'q': 'table'})
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context['categories']['jobs']['items'])
        # job2 has "table" in description
        self.assertIn(self.job2, jobs)
        self.assertNotIn(self.job1, jobs)

    def test_search_jobs_by_customer_po(self):
        """Test searching jobs by customer PO number"""
        response = self.client.get(reverse('search:search'), {'q': 'PO-12345'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])
        self.assertNotIn(self.job2, response.context['categories']['jobs']['items'])

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
        self.assertIn(self.job2, response.context['categories']['jobs']['items'])
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

        # Should find job, estimate, work order, worksheet, invoice, and PO
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])
        self.assertIn(self.estimate1, response.context['categories']['estimates']['grouped_items'])
        self.assertIn(self.work_order1, response.context['categories']['work_orders'])
        self.assertIn(self.worksheet1, response.context['categories']['est_worksheets'])
        self.assertIn(self.invoice1, response.context['categories']['invoices']['grouped_items'])
        self.assertIn(self.po1, response.context['categories']['purchase_orders']['items'])

        # Total count should reflect all matches
        self.assertGreater(response.context['total_count'], 1)

    def test_search_total_count_accuracy(self):
        """Test that total_count accurately reflects number of results"""
        response = self.client.get(reverse('search:search'), {'q': 'furniture'})
        self.assertEqual(response.status_code, 200)

        # Count manually
        expected_count = (
            len(response.context['categories'].get('jobs', {}).get('items', [])) +
            len(response.context['categories'].get('estimates', {}).get('grouped_items', [])) +
            len(response.context['categories'].get('work_orders', [])) +
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
        # Should match postal code and PO number
        self.assertIn(self.contact1, response.context['categories']['contacts']['items'])
        self.assertIn(self.job1, response.context['categories']['jobs']['items'])

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
        self.assertEqual(
            response1.context['categories'].get('jobs', {}).get('items', []),
            response2.context['categories'].get('jobs', {}).get('items', [])
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
        self.assertIn('items', categories['jobs'])

    def test_search_template_used(self):
        """Test that the correct template is used"""
        response = self.client.get(reverse('search:search'), {'q': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'search/search_results.html')
