from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Estimate
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class SearchWithinResultsTest(TestCase):
    def setUp(self):
        self.client = Client()

        # Create test contacts and businesses
        self.contact1 = Contact.objects.create(
            first_name="John",
            last_name="Smith",
            email="john.smith@example.com",
            work_number="555-1111"
        )
        self.contact2 = Contact.objects.create(
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@example.com",
            mobile_number="555-2222"
        )
        self.contact3 = Contact.objects.create(
            first_name="Bob",
            last_name="Johnson",
            email="bob.johnson@example.com",
            work_number="555-3333"
        )

        self.business1 = Business.objects.create(
            business_name="Smith Corp",
            default_contact=self.contact1
        )
        self.contact1.business = self.business1
        self.contact1.save()

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        # Create test jobs
        self.job1 = Job.objects.create(
            job_number="JOB-2025-0001",
            contact=self.contact1,
            description="Office renovation project"
        )
        self.job2 = Job.objects.create(
            job_number="JOB-2025-0002",
            contact=self.contact2,
            description="Website development project"
        )
        self.job3 = Job.objects.create(
            job_number="JOB-2025-0003",
            contact=self.contact3,
            description="Office maintenance project"
        )

        # Create test estimates
        self.estimate1 = Estimate.objects.create(
            estimate_number="EST-2025-0001",
            job=self.job1,
            version=1,
            status="draft"
        )
        self.estimate2 = Estimate.objects.create(
            estimate_number="EST-2025-0002",
            job=self.job2,
            version=1,
            status="open"
        )

        self.search_url = reverse('search:search')
        self.search_within_url = reverse('search:search_within')

    def test_initial_search_stores_results_in_session(self):
        """Test that performing a search stores result IDs in the session"""
        response = self.client.get(self.search_url, {'q': 'project'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('search_result_ids', self.client.session)
        self.assertIn('search_original_query', self.client.session)
        self.assertEqual(self.client.session['search_original_query'], 'project')

        # Should have stored Job IDs
        self.assertIn('Job', self.client.session['search_result_ids'])

    def test_search_within_filters_stored_results(self):
        """Test that search within results filters only the stored results"""
        # First, perform initial search for "project"
        response1 = self.client.get(self.search_url, {'q': 'project'})
        self.assertEqual(response1.status_code, 200)

        # All 3 jobs should be found (all have "project" in description)
        self.assertContains(response1, 'JOB-2025-0001')
        self.assertContains(response1, 'JOB-2025-0002')
        self.assertContains(response1, 'JOB-2025-0003')

        # Now search within results for "Office" (should match jobs 1 and 3)
        response2 = self.client.get(self.search_within_url, {'within_q': 'Office'})
        self.assertEqual(response2.status_code, 200)

        # Should find jobs with "Office" in description
        self.assertContains(response2, 'JOB-2025-0001')  # Office renovation
        self.assertContains(response2, 'JOB-2025-0003')  # Office maintenance

        # Should NOT find job 2 (Website development)
        self.assertNotContains(response2, 'Website development')

    def test_search_within_displays_ui_elements(self):
        """Test that the search within UI elements are displayed correctly"""
        # Perform initial search
        response1 = self.client.get(self.search_url, {'q': 'project'})

        # Should show the "Search Within Results" box
        self.assertContains(response1, 'Search Within These Results')
        self.assertContains(response1, 'within_q')

        # Now do a search within
        response2 = self.client.get(self.search_within_url, {'within_q': 'Office'})

        # Should show the "Return to All Results" button
        self.assertContains(response2, 'Return to All Results')
        self.assertContains(response2, 'Showing filtered results')

    def test_search_within_with_no_stored_results(self):
        """Test that search within fails gracefully when no results are stored"""
        # Clear session
        session = self.client.session
        session.clear()
        session.save()

        response = self.client.get(self.search_within_url, {'within_q': 'test'})

        # Should return successfully but with no results
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_stored_results'])

    def test_search_within_respects_filters(self):
        """Test that search within results still respects category and other filters"""
        # Initial search
        self.client.get(self.search_url, {'q': 'project'})

        # Search within with category filter
        response = self.client.get(self.search_within_url, {
            'within_q': 'Office',
            'category': 'Jobs'
        })

        self.assertEqual(response.status_code, 200)
        # Should still find matching jobs
        self.assertContains(response, 'JOB-2025-0001')

    def test_search_within_contact_names(self):
        """Test searching within results for contact names"""
        # Initial search for Smith (business and contact)
        response1 = self.client.get(self.search_url, {'q': 'Smith'})

        # Should find contact John Smith and Smith Corp business
        self.assertEqual(response1.status_code, 200)

        # Now search within for "John"
        response2 = self.client.get(self.search_within_url, {'within_q': 'John'})
        self.assertEqual(response2.status_code, 200)

        # Should find John Smith contact
        self.assertContains(response2, 'John Smith')

        # Should not find Jane Doe (not in original results)
        self.assertNotContains(response2, 'Jane Doe')

    def test_filter_by_estimates_category(self):
        """Test that filtering by 'estimates' category shows estimates correctly"""
        # Initial search that will return both jobs and estimates
        response = self.client.get(self.search_url, {'q': '2025'})
        self.assertEqual(response.status_code, 200)

        # Should find both jobs and estimates
        self.assertContains(response, 'JOB-2025-0001')
        self.assertContains(response, 'EST-2025-0001')

        # Now filter by estimates category only
        response_filtered = self.client.get(self.search_url, {
            'q': '2025',
            'category': 'estimates'
        })
        self.assertEqual(response_filtered.status_code, 200)

        # Should have a non-zero total count
        self.assertGreater(response_filtered.context['total_count'], 0)
        self.assertEqual(response_filtered.context['total_count'], 2)

        # Should find estimates
        self.assertContains(response_filtered, 'EST-2025-0001')
        self.assertContains(response_filtered, 'EST-2025-0002')

        # Verify only estimates category is in the response
        categories = response_filtered.context['categories']
        self.assertIn('estimates', categories)
        self.assertNotIn('jobs', categories)
        self.assertNotIn('contacts', categories)
        self.assertNotIn('businesses', categories)
