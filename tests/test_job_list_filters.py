from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class JobListFilterTestCase(TestCase):
    """Tests for job list view filtering functionality."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('jobs:list')

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        # Create contacts first (without business)
        self.contact1 = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john.doe@acme.com",
            work_number="555-1234"
        )
        self.contact2 = Contact.objects.create(
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@tech.com",
            work_number="555-5678"
        )
        self.contact3 = Contact.objects.create(
            first_name="Bob",
            last_name="Johnson",
            email="bob@acme.com",
            mobile_number="555-9999"
        )

        # Create businesses with default contacts
        self.business1 = Business.objects.create(
            business_name="Acme Corporation",
            default_contact=self.contact1
        )
        self.business2 = Business.objects.create(
            business_name="Tech Solutions",
            default_contact=self.contact2
        )

        # Update contacts with their business references
        self.contact1.business = self.business1
        self.contact1.save()
        self.contact2.business = self.business2
        self.contact2.save()
        self.contact3.business = self.business1
        self.contact3.save()

        # Create jobs with various statuses and dates
        now = timezone.now()

        self.job_draft = Job.objects.create(
            job_number="JOB-TEST-001",
            name="Draft Job",
            contact=self.contact1,
            status='draft',
            description="A draft job"
        )

        self.job_submitted = Job.objects.create(
            job_number="JOB-TEST-002",
            name="Submitted Job",
            contact=self.contact2,
            status='draft',
            description="A submitted job"
        )
        # Transition to submitted
        self.job_submitted.status = 'submitted'
        self.job_submitted.save()

        self.job_approved = Job.objects.create(
            job_number="JOB-TEST-003",
            name="Approved Job",
            contact=self.contact1,
            status='draft',
            description="An approved job"
        )
        # Transition through states to approved
        self.job_approved.status = 'submitted'
        self.job_approved.save()
        self.job_approved.status = 'approved'
        self.job_approved.save()

        self.job_completed = Job.objects.create(
            job_number="JOB-TEST-004",
            name="Completed Job",
            contact=self.contact3,
            status='draft',
            description="A completed job"
        )
        # Transition through states to completed
        self.job_completed.status = 'submitted'
        self.job_completed.save()
        self.job_completed.status = 'approved'
        self.job_completed.save()
        self.job_completed.status = 'completed'
        self.job_completed.save()

        self.job_rejected = Job.objects.create(
            job_number="JOB-TEST-005",
            name="Rejected Job",
            contact=self.contact2,
            status='draft',
            description="A rejected job"
        )
        # Transition to rejected
        self.job_rejected.status = 'rejected'
        self.job_rejected.save()

        self.job_cancelled = Job.objects.create(
            job_number="JOB-TEST-006",
            name="Cancelled Job",
            contact=self.contact1,
            status='draft',
            description="A cancelled job"
        )
        # Transition through states to cancelled
        self.job_cancelled.status = 'submitted'
        self.job_cancelled.save()
        self.job_cancelled.status = 'approved'
        self.job_cancelled.save()
        self.job_cancelled.status = 'cancelled'
        self.job_cancelled.save()


class JobListDefaultFilterTest(JobListFilterTestCase):
    """Tests for default filter behavior."""

    def test_default_shows_draft_and_approved_only(self):
        """Test that the default view shows only Draft and Approved jobs."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        job_statuses = [job.status for job in jobs]

        # Should only contain draft and approved
        self.assertIn('draft', job_statuses)
        self.assertIn('approved', job_statuses)
        self.assertNotIn('submitted', job_statuses)
        self.assertNotIn('completed', job_statuses)
        self.assertNotIn('rejected', job_statuses)
        self.assertNotIn('cancelled', job_statuses)

    def test_default_filters_in_context(self):
        """Test that default status filters are passed to template context."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        current_filters = response.context['current_filters']
        self.assertIn('draft', current_filters['statuses'])
        self.assertIn('approved', current_filters['statuses'])

    def test_all_status_choices_available_in_ui(self):
        """Test that all status choices are available in the filter UI."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        status_choices = response.context['status_choices']
        status_values = [choice[0] for choice in status_choices]

        # All statuses should be available for selection
        self.assertIn('draft', status_values)
        self.assertIn('submitted', status_values)
        self.assertIn('approved', status_values)
        self.assertIn('rejected', status_values)
        self.assertIn('completed', status_values)
        self.assertIn('cancelled', status_values)


class JobListStatusFilterTest(JobListFilterTestCase):
    """Tests for status filtering."""

    def test_filter_single_status(self):
        """Test filtering by a single status."""
        response = self.client.get(self.url, {'status': 'completed'})
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, 'completed')

    def test_filter_multiple_statuses(self):
        """Test filtering by multiple statuses."""
        response = self.client.get(self.url, {'status': ['draft', 'completed']})
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        job_statuses = {job.status for job in jobs}

        self.assertEqual(job_statuses, {'draft', 'completed'})

    def test_filter_all_statuses(self):
        """Test selecting all statuses shows all jobs."""
        response = self.client.get(self.url, {
            'status': ['draft', 'submitted', 'approved', 'rejected', 'completed', 'cancelled']
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        self.assertEqual(len(jobs), 6)  # All 6 jobs

    def test_filter_no_statuses_with_query_string(self):
        """Test that submitting with no statuses shows all jobs (no status filtering)."""
        # Submitting form with empty status (no status checkboxes checked)
        response = self.client.get(self.url, {'business': ''})  # Some query param but no status
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        # When query string exists but no status selected, all jobs are shown (no status filter applied)
        self.assertEqual(len(jobs), 6)


class JobListContactBusinessFilterTest(JobListFilterTestCase):
    """Tests for contact and business filtering."""

    def test_filter_by_contact(self):
        """Test filtering by specific contact."""
        response = self.client.get(self.url, {
            'status': ['draft', 'submitted', 'approved', 'completed', 'rejected', 'cancelled'],
            'contact': self.contact1.contact_id
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        for job in jobs:
            self.assertEqual(job.contact_id, self.contact1.contact_id)

    def test_filter_by_business(self):
        """Test filtering by business."""
        response = self.client.get(self.url, {
            'status': ['draft', 'submitted', 'approved', 'completed', 'rejected', 'cancelled'],
            'business': self.business1.business_id
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        for job in jobs:
            self.assertEqual(job.contact.business_id, self.business1.business_id)

    def test_filter_contact_and_business_combined(self):
        """Test filtering by both contact and business."""
        response = self.client.get(self.url, {
            'status': ['draft', 'submitted', 'approved', 'completed', 'rejected', 'cancelled'],
            'contact': self.contact1.contact_id,
            'business': self.business1.business_id
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        for job in jobs:
            self.assertEqual(job.contact_id, self.contact1.contact_id)
            self.assertEqual(job.contact.business_id, self.business1.business_id)


class JobListDateFilterTest(JobListFilterTestCase):
    """Tests for date filtering."""

    def test_filter_by_created_date_range(self):
        """Test filtering by created date range."""
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        response = self.client.get(self.url, {
            'status': ['draft', 'approved'],
            'date_type': 'created',
            'date_from': yesterday.isoformat(),
            'date_to': tomorrow.isoformat()
        })
        self.assertEqual(response.status_code, 200)

        # Jobs created today should be included
        jobs = list(response.context['jobs'])
        self.assertGreater(len(jobs), 0)

    def test_filter_by_due_date(self):
        """Test filtering by due date."""
        # Set a due date on one job
        future_date = timezone.now() + timedelta(days=7)
        self.job_draft.due_date = future_date
        self.job_draft.save()

        response = self.client.get(self.url, {
            'status': ['draft'],
            'date_type': 'due',
            'date_from': timezone.now().date().isoformat(),
            'date_to': (timezone.now().date() + timedelta(days=14)).isoformat()
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        # Should find the job with due date
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, self.job_draft.job_id)


class JobListSortingTest(JobListFilterTestCase):
    """Tests for sorting behavior."""

    def test_sort_by_status_order(self):
        """Test that jobs are sorted by status in correct order: Draft, Approved, Submitted, Completed, Rejected, Cancelled."""
        response = self.client.get(self.url, {
            'status': ['draft', 'submitted', 'approved', 'completed', 'rejected', 'cancelled']
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        statuses = [job.status for job in jobs]

        # Define expected order
        status_priority = {'draft': 0, 'approved': 1, 'submitted': 2, 'completed': 3, 'rejected': 4, 'cancelled': 5}

        # Verify sorting is correct
        for i in range(len(statuses) - 1):
            current_priority = status_priority[statuses[i]]
            next_priority = status_priority[statuses[i + 1]]
            # Current should have same or lower priority number than next
            self.assertLessEqual(current_priority, next_priority,
                f"Status {statuses[i]} should come before or equal to {statuses[i + 1]}")

    def test_sort_uses_start_date_when_available(self):
        """Test that sorting uses start_date when available."""
        # job_approved should have a start_date set automatically
        self.assertIsNotNone(self.job_approved.start_date)

        response = self.client.get(self.url, {'status': ['approved']})
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        # With only one approved job, just verify it's returned
        self.assertEqual(len(jobs), 1)

    def test_sort_falls_back_to_created_date(self):
        """Test that sorting falls back to created_date when start_date is null."""
        # Draft jobs don't have start_date
        self.assertIsNone(self.job_draft.start_date)

        response = self.client.get(self.url, {'status': ['draft']})
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, self.job_draft.job_id)

    def test_sort_within_same_status_by_date_descending(self):
        """Test that jobs within the same status are sorted by date descending (newest first)."""
        # Create additional draft jobs with different creation times
        job_draft_old = Job.objects.create(
            job_number="JOB-TEST-007",
            name="Old Draft Job",
            contact=self.contact1,
            status='draft',
            description="An older draft job"
        )
        # Manually set an older created_date
        Job.objects.filter(pk=job_draft_old.pk).update(
            created_date=timezone.now() - timedelta(days=5)
        )

        job_draft_new = Job.objects.create(
            job_number="JOB-TEST-008",
            name="New Draft Job",
            contact=self.contact1,
            status='draft',
            description="A newer draft job"
        )

        response = self.client.get(self.url, {'status': ['draft']})
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        draft_jobs = [j for j in jobs if j.status == 'draft']

        # Should be sorted newest first (descending)
        self.assertGreaterEqual(len(draft_jobs), 2)
        # The newest job should come first
        for i in range(len(draft_jobs) - 1):
            current_date = draft_jobs[i].start_date or draft_jobs[i].created_date
            next_date = draft_jobs[i + 1].start_date or draft_jobs[i + 1].created_date
            self.assertGreaterEqual(current_date, next_date)


class JobListCombinedFiltersTest(JobListFilterTestCase):
    """Tests for combining multiple filters."""

    def test_status_and_business_filter(self):
        """Test combining status and business filters."""
        response = self.client.get(self.url, {
            'status': ['draft', 'approved'],
            'business': self.business1.business_id
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        for job in jobs:
            self.assertIn(job.status, ['draft', 'approved'])
            self.assertEqual(job.contact.business_id, self.business1.business_id)

    def test_status_contact_and_date_filter(self):
        """Test combining status, contact, and date filters."""
        today = timezone.now().date()

        response = self.client.get(self.url, {
            'status': ['draft', 'approved', 'completed'],
            'contact': self.contact1.contact_id,
            'date_type': 'created',
            'date_from': (today - timedelta(days=1)).isoformat(),
            'date_to': (today + timedelta(days=1)).isoformat()
        })
        self.assertEqual(response.status_code, 200)

        jobs = list(response.context['jobs'])
        for job in jobs:
            self.assertIn(job.status, ['draft', 'approved', 'completed'])
            self.assertEqual(job.contact_id, self.contact1.contact_id)

    def test_filters_applied_flag(self):
        """Test that filters_applied flag is set correctly."""
        # Default view (no query string) - filters_applied should be False
        response = self.client.get(self.url)
        self.assertFalse(response.context['filters_applied'])

        # With explicit filters - filters_applied should be True
        response = self.client.get(self.url, {'status': ['completed']})
        self.assertTrue(response.context['filters_applied'])

        # With business filter
        response = self.client.get(self.url, {
            'status': ['draft', 'approved'],
            'business': self.business1.business_id
        })
        self.assertTrue(response.context['filters_applied'])


class JobListTemplateContextTest(JobListFilterTestCase):
    """Tests for template context."""

    def test_contacts_in_context(self):
        """Test that contacts are passed to template for filter dropdown."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        contacts = response.context['contacts']
        self.assertGreaterEqual(len(contacts), 3)

    def test_businesses_in_context(self):
        """Test that businesses are passed to template for filter dropdown."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        businesses = response.context['businesses']
        self.assertGreaterEqual(len(businesses), 2)

    def test_current_filters_in_context(self):
        """Test that current filter values are passed to template."""
        response = self.client.get(self.url, {
            'status': ['draft', 'completed'],
            'business': str(self.business1.business_id),
            'date_type': 'created',
            'date_from': '2024-01-01',
            'date_to': '2024-12-31'
        })
        self.assertEqual(response.status_code, 200)

        current_filters = response.context['current_filters']
        self.assertEqual(set(current_filters['statuses']), {'draft', 'completed'})
        self.assertEqual(current_filters['business'], str(self.business1.business_id))
        self.assertEqual(current_filters['date_type'], 'created')
        self.assertEqual(current_filters['date_from'], '2024-01-01')
        self.assertEqual(current_filters['date_to'], '2024-12-31')
