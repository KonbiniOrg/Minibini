"""
Tests that accounting_category is displayed and editable in all relevant UI views.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.jobs.models import Job, PlanTask
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory

User = get_user_model()


class TaskDetailAccountingCategoryDisplayTests(TestCase):
    """Test that task_detail always shows accounting_category row."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com',
            is_superuser=True
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-001', contact=self.contact, status=Job.STATUS_APPROVED
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status=Job.STATUS_DRAFT, version=1
        )
        self.lit, _ = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_detail_shows_accounting_category_when_set(self):
        """Task detail should display the line item type name when set."""
        task = PlanTask.objects.create(
            name='Task With Type', est_worksheet=self.worksheet,
            accounting_category=self.lit,
        )
        url = reverse('jobs:task_detail', args=[task.plan_task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Accounting Category')
        self.assertContains(response, 'Service')

    def test_detail_shows_accounting_category_row_when_null(self):
        """Task detail should always show the Accounting Category row, even when null."""
        task = PlanTask.objects.create(
            name='Task No Type', est_worksheet=self.worksheet,
        )
        url = reverse('jobs:task_detail', args=[task.plan_task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Accounting Category')


class TaskEditAccountingCategoryTests(TestCase):
    """Test that task edit form includes accounting_category field."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com',
            is_superuser=True
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-002', contact=self.contact, status=Job.STATUS_APPROVED
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status=Job.STATUS_DRAFT, version=1
        )
        self.lit_svc, _ = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service'})
        self.lit_prd, _ = AccountingCategory.objects.get_or_create(code='PRD', defaults={'name': 'Product'})

    def test_edit_form_shows_accounting_category_field(self):
        """Task edit form should include a accounting_category dropdown."""
        task = PlanTask.objects.create(
            name='Editable Task', est_worksheet=self.worksheet,
        )
        url = reverse('jobs:task_edit', args=[task.plan_task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')

    def test_edit_post_can_set_accounting_category(self):
        """POST on task edit should be able to set accounting_category."""
        task = PlanTask.objects.create(
            name='Task', est_worksheet=self.worksheet,
        )
        url = reverse('jobs:task_edit', args=[task.plan_task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'accounting_category': self.lit_svc.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.plan_task_id]))
        task.refresh_from_db()
        self.assertEqual(task.accounting_category, self.lit_svc)

    def test_edit_post_can_change_accounting_category(self):
        """POST on task edit should be able to change accounting_category."""
        task = PlanTask.objects.create(
            name='Task', est_worksheet=self.worksheet,
            accounting_category=self.lit_svc,
        )
        url = reverse('jobs:task_edit', args=[task.plan_task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'accounting_category': self.lit_prd.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.plan_task_id]))
        task.refresh_from_db()
        self.assertEqual(task.accounting_category, self.lit_prd)

    def test_edit_post_can_clear_accounting_category(self):
        """POST on task edit should be able to clear accounting_category."""
        task = PlanTask.objects.create(
            name='Task', est_worksheet=self.worksheet,
            accounting_category=self.lit_svc,
        )
        url = reverse('jobs:task_edit', args=[task.plan_task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'accounting_category': '',
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.plan_task_id]))
        task.refresh_from_db()
        self.assertIsNone(task.accounting_category)


class TaskAddManualAccountingCategoryTests(TestCase):
    """Test that the manual task add form includes accounting_category."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com',
            is_superuser=True
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-003', contact=self.contact, status=Job.STATUS_APPROVED
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status=Job.STATUS_DRAFT, version=1
        )
        self.lit, _ = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_add_manual_form_shows_accounting_category(self):
        """Manual task add form should include accounting_category field."""
        url = reverse('estimates:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')

    def test_add_manual_post_with_accounting_category(self):
        """POST on manual add should create task with accounting_category."""
        url = reverse('estimates:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'name': 'New Manual Task',
            'units': 'hours',
            'rate': '40.00',
            'est_qty': '3.00',
            'accounting_category': self.lit.pk,
        })
        self.assertRedirects(
            response,
            reverse('estimates:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )
        task = PlanTask.objects.get(name='New Manual Task')
        self.assertEqual(task.accounting_category, self.lit)


class TaskTemplateFormAccountingCategoryTests(TestCase):
    """Test that TaskTemplate create/edit forms include accounting_category."""

    def setUp(self):
        self.client = Client()
        self.lit, _ = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service'})
        self.lit2, _ = AccountingCategory.objects.get_or_create(code='PRD', defaults={'name': 'Product'})

    def test_create_form_shows_accounting_category(self):
        """TaskTemplate create form should include accounting_category field."""
        url = reverse('estimates:add_task_template_standalone')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')

    def test_create_post_with_accounting_category(self):
        """POST to create TaskTemplate should save accounting_category."""
        url = reverse('estimates:add_task_template_standalone')
        response = self.client.post(url, {
            'template_name': 'New Template',
            'description': 'Test',
            'units': 'hours',
            'rate': '50.00',
            'accounting_category': self.lit.pk,
        })
        self.assertRedirects(response, reverse('estimates:task_template_list'))
        tt = TaskTemplate.objects.get(template_name='New Template')
        self.assertEqual(tt.accounting_category, self.lit)

    def test_edit_form_shows_accounting_category(self):
        """TaskTemplate edit form should include accounting_category field."""
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.create(
            name='S-acu1', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit,
        )
        tt = TaskTemplate.objects.create(
            template_name='Existing', units='hours', rate=Decimal('50.00'),
            accounting_category=self.lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        url = reverse('estimates:task_template_edit', args=[tt.template_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')

    def test_edit_post_can_change_accounting_category(self):
        """POST on TaskTemplate edit should update accounting_category."""
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.create(
            name='S-acu2', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit,
        )
        tt = TaskTemplate.objects.create(
            template_name='Existing', units='hours', rate=Decimal('50.00'),
            accounting_category=self.lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        url = reverse('estimates:task_template_edit', args=[tt.template_id])
        response = self.client.post(url, {
            'template_name': 'Existing',
            'description': '',
            'units': 'hours',
            'rate': '50.00',
            'accounting_category': self.lit2.pk,
        })
        self.assertRedirects(response, reverse('estimates:task_template_list'))
        tt.refresh_from_db()
        self.assertEqual(tt.accounting_category, self.lit2)


class TaskTemplateListAccountingCategoryTests(TestCase):
    """Test that TaskTemplate list shows accounting_category column."""

    def setUp(self):
        self.client = Client()
        self.lit, _ = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_list_shows_accounting_category_column(self):
        """TaskTemplate list should have a Accounting Category column header."""
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.create(
            name='S-acu3', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit,
        )
        TaskTemplate.objects.create(
            template_name='Test Template', units='hours',
            rate=Decimal('50.00'), accounting_category=self.lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        url = reverse('estimates:task_template_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Accounting Category')

    def test_list_shows_accounting_category_value(self):
        """TaskTemplate list should display the line item type name."""
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.create(
            name='S-acu4', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit,
        )
        TaskTemplate.objects.create(
            template_name='Test Template', units='hours',
            rate=Decimal('50.00'), accounting_category=self.lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        url = reverse('estimates:task_template_list')
        response = self.client.get(url)
        self.assertContains(response, 'Service')
