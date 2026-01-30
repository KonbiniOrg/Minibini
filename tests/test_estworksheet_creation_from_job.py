from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, EstWorksheet, WorkOrderTemplate
from apps.contacts.models import Contact


class EstWorksheetCreateFromJobTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB-2024-TEST",
            contact=self.contact,
            description="Test job for worksheet creation"
        )
        self.template = WorkOrderTemplate.objects.create(
            template_name="Test Template",
            description="Template for testing",
            is_active=True
        )
        self.url = reverse('jobs:estworksheet_create_for_job', args=[self.job.job_id])

    def test_estworksheet_create_for_job_get(self):
        """Test GET request to worksheet creation form from job"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/estworksheet_create_for_job.html')
        self.assertContains(response, self.job.job_number)
        self.assertContains(response, self.job.description)

        # Check that form has job pre-selected and hidden
        form = response.context['form']
        self.assertEqual(form.initial['job'], self.job)

    def test_estworksheet_create_for_job_post_success(self):
        """Test successful POST request to create worksheet for job"""
        post_data = {
            'job': self.job.job_id,
            # template is optional
            # status is not in form - always defaults to draft
        }

        response = self.client.post(self.url, data=post_data)

        # Check redirect
        self.assertEqual(response.status_code, 302)

        # Verify worksheet was created with draft status
        worksheet = EstWorksheet.objects.get(job=self.job)
        self.assertEqual(worksheet.job, self.job)
        self.assertEqual(worksheet.status, 'draft')  # Must always be draft
        self.assertIsNone(worksheet.template)
        self.assertEqual(worksheet.version, 1)

    def test_estworksheet_create_with_template(self):
        """Test creating worksheet with a template selected"""
        post_data = {
            'job': self.job.job_id,
            'template': self.template.template_id,
            # status not included - always defaults to draft
        }

        response = self.client.post(self.url, data=post_data)

        # Check redirect
        self.assertEqual(response.status_code, 302)

        # Verify worksheet was created with template and draft status
        worksheet = EstWorksheet.objects.get(job=self.job)
        self.assertEqual(worksheet.template, self.template)
        self.assertEqual(worksheet.status, 'draft')  # Always draft on creation

    def test_job_detail_has_create_worksheet_link(self):
        """Test that job detail page has the Create Worksheet link"""
        job_detail_url = reverse('jobs:detail', args=[self.job.job_id])
        response = self.client.get(job_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Worksheet')
        self.assertContains(response, self.url)

    def test_estworksheet_always_created_as_draft(self):
        """Test that new worksheet always starts in draft status"""
        post_data = {
            'job': self.job.job_id,
        }

        response = self.client.post(self.url, data=post_data)

        # Verify worksheet was created with draft status
        worksheet = EstWorksheet.objects.get(job=self.job)
        self.assertEqual(worksheet.status, 'draft')

    def test_status_field_not_in_form(self):
        """Test that status field is not present in the creation form"""
        response = self.client.get(self.url)
        form = response.context['form']

        # Status field should not be in the form
        self.assertNotIn('status', form.fields)

    def test_multiple_worksheets_for_same_job(self):
        """Test that multiple worksheets can be created for the same job"""
        # Create first worksheet
        post_data = {
            'job': self.job.job_id,
        }
        self.client.post(self.url, data=post_data)

        # Create second worksheet
        self.client.post(self.url, data=post_data)

        # Verify both were created with draft status
        worksheets = EstWorksheet.objects.filter(job=self.job)
        self.assertEqual(worksheets.count(), 2)
        for worksheet in worksheets:
            self.assertEqual(worksheet.status, 'draft')

    def test_template_selection_creates_tasks(self):
        """Test that selecting a template creates tasks from it"""
        # Create some task templates for the template
        from apps.jobs.models import TaskTemplate, TemplateTaskAssociation

        task_template1 = TaskTemplate.objects.create(
            template_name="Test Task 1",
            units="hours",
            rate=50.00,
            is_active=True
        )
        task_template2 = TaskTemplate.objects.create(
            template_name="Test Task 2",
            units="pieces",
            rate=25.00,
            is_active=True
        )

        # Associate tasks with the template
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=task_template1,
            est_qty=2.0,
            sort_order=1
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=task_template2,
            est_qty=5.0,
            sort_order=2
        )

        post_data = {
            'job': self.job.job_id,
            'template': self.template.template_id,
        }

        response = self.client.post(self.url, data=post_data)

        # Check redirect
        self.assertEqual(response.status_code, 302)

        # Verify worksheet was created with tasks
        from apps.jobs.models import Task
        worksheet = EstWorksheet.objects.get(job=self.job)
        tasks = Task.objects.filter(est_worksheet=worksheet)

        self.assertEqual(tasks.count(), 2)

        # Check task details
        task1 = tasks.get(template=task_template1)
        self.assertEqual(task1.name, "Test Task 1")
        self.assertEqual(task1.est_qty, 2.0)
        self.assertEqual(task1.rate, 50.00)

        task2 = tasks.get(template=task_template2)
        self.assertEqual(task2.name, "Test Task 2")
        self.assertEqual(task2.est_qty, 5.0)
        self.assertEqual(task2.rate, 25.00)

    def test_cancel_returns_to_job_detail(self):
        """Test that cancel link returns to job detail page"""
        response = self.client.get(self.url)

        job_detail_url = reverse('jobs:detail', args=[self.job.job_id])
        self.assertContains(response, job_detail_url)
        self.assertContains(response, 'Cancel')