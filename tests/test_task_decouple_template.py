"""
Tests for decoupling PlanTask from TaskTemplate.
Part 1: PlanTask.accounting_category field, copying at creation points, use in estimate generation.
Part 2: Line item type review at estimate generation.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.db.models import ProtectedError

from apps.jobs.models import PlanBundle, Job, PlanTask, WorkOrder
from apps.estimates.models import TaskTemplate, WorkTemplate, TemplateTaskAssociation, TemplateBundle, EstWorksheet, Estimate, EstimateLineItem
from apps.estimates.services import EstimateGenerationService
from apps.jobs.services import TaskService
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact


class TaskAccountingCategoryFieldTests(TestCase):
    """Tests that PlanTask has a accounting_category FK field."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_task_can_have_accounting_category(self):
        """PlanTask should have a accounting_category FK field."""
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Sand Surface",
            accounting_category=self.lit,
        )
        task.refresh_from_db()
        self.assertEqual(task.accounting_category, self.lit)

    def test_task_accounting_category_nullable(self):
        """PlanTask.accounting_category can be null (manual tasks, work order tasks)."""
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Manual PlanTask",
        )
        self.assertIsNone(task.accounting_category)

    def test_task_accounting_category_protected(self):
        """Cannot delete AccountingCategory if a PlanTask references it."""
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Sand",
            accounting_category=self.lit,
        )
        with self.assertRaises(ProtectedError):
            self.lit.delete()


class GenerateTaskCopiesAccountingCategoryTests(TestCase):
    """Tests that TaskTemplate.generate_task() copies accounting_category to the PlanTask."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_generate_task_copies_accounting_category(self):
        """generate_task() should copy accounting_category from template to task."""
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), accounting_category=self.lit
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("2.00"))
        self.assertEqual(task.accounting_category, self.lit)

    def test_generate_task_null_accounting_category(self):
        """generate_task() with template having no accounting_category produces task with null."""
        tt = TaskTemplate.objects.create(
            template_name="Check", rate=Decimal("0.00"), accounting_category=None
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("1.00"))
        self.assertIsNone(task.accounting_category)

    def test_generate_tasks_for_worksheet_copies_accounting_category(self):
        """Full template generation copies accounting_category to each task."""
        wot = WorkTemplate.objects.create(template_name="Cabinet")
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), accounting_category=self.lit
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt,
            est_qty=Decimal("2.00"), mapping_strategy='direct'
        )
        tasks = wot.generate_tasks_for_worksheet(self.worksheet)
        self.assertEqual(tasks[0].accounting_category, self.lit)


class CopyPointsPreserveAccountingCategoryTests(TestCase):
    """Tests that all task-copying code preserves accounting_category."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter', defaults={'value': '0'}
        )
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_create_new_version_copies_accounting_category(self):
        """EstWorksheet.create_new_version() should copy accounting_category to new tasks."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit,
        )
        # Generate estimate so worksheet can create new version
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        ws.status = EstWorksheet.STATUS_FINAL
        ws.save()

        new_ws = ws.create_new_version()
        new_task = new_ws.plan_tasks.first()
        self.assertEqual(new_task.accounting_category, self.lit)

    def test_copy_worksheet_tasks_copies_accounting_category(self):
        """_copy_worksheet_tasks should copy accounting_category to work order tasks."""
        ws = EstWorksheet.objects.create(job=self.job)
        source_task = PlanTask.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit,
        )
        # Create estimate + line item referencing the task
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()

        wo = WorkOrder.objects.create(job=self.job)
        tasks = TaskService._copy_worksheet_tasks(line_item, wo)
        self.assertEqual(tasks[0].accounting_category, self.lit)


class EstimateGenerationUsesTaskAccountingCategoryTests(TestCase):
    """Tests that estimate generation reads task.accounting_category directly."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter', defaults={'value': '0'}
        )
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = AccountingCategory.objects.get_or_create(code="LBR", defaults={"name": "Labor"})
        self.lit_material, _ = AccountingCategory.objects.get_or_create(code="MAT", defaults={"name": "Material"})

    def test_direct_task_uses_own_accounting_category(self):
        """Direct task's accounting_category (not template's) should be used in estimate generation."""
        ws = EstWorksheet.objects.create(job=self.job)
        # Create task with accounting_category directly - no template needed
        PlanTask.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit_labor,
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()
        self.assertEqual(line_item.accounting_category, self.lit_labor)

    def test_task_without_accounting_category_gets_default(self):
        """PlanTask without accounting_category should get default type during estimate generation."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Manual PlanTask", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()
        # Should have a accounting_category (the default fallback)
        self.assertIsNotNone(line_item.accounting_category)


# =============================================================================
# Part 2: Line item type review at estimate generation
# =============================================================================


class EstimateGenerationReviewPageTests(TestCase):
    """Tests for the estimate generation confirmation page with accounting_category review."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter', defaults={'value': '0'}
        )
        self.user = User.objects.create_user(username='testuser', password='testpass', is_superuser=True)
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = AccountingCategory.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit_material, _ = AccountingCategory.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )

    def test_get_shows_untyped_tasks(self):
        """GET should identify direct tasks missing accounting_category."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Typed PlanTask", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit_labor,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name="Untyped PlanTask", rate=Decimal("30.00"),
            est_qty=Decimal("1.00"),
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('untyped_tasks', response.context)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 1)
        self.assertEqual(untyped[0].name, "Untyped PlanTask")

    def test_get_passes_accounting_categories(self):
        """GET should pass available accounting_categories to template."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="PlanTask", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"),
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        self.assertIn('accounting_categories', response.context)

    def test_excluded_tasks_not_in_untyped(self):
        """Excluded tasks should not appear in untyped_tasks even if they lack accounting_category."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Excluded PlanTask", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"), mapping_strategy='exclude',
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 0)

    def test_bundled_tasks_not_in_untyped(self):
        """Bundled tasks should not appear in untyped_tasks (bundle has its own accounting_category)."""
        ws = EstWorksheet.objects.create(job=self.job)
        bundle = PlanBundle.objects.create(
            est_worksheet=ws, name="Bundle", accounting_category=self.lit_labor,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name="Bundled PlanTask", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"), mapping_strategy='bundle', bundle=bundle,
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 0)

    def test_post_saves_accounting_categories_and_generates(self):
        """POST with task_accounting_category assignments should save them then generate estimate."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=ws, name="Untyped PlanTask", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"),
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.post(url, {
            f'task_accounting_category_{task.pk}': self.lit_labor.pk,
        })

        # Should redirect to the new estimate
        self.assertEqual(response.status_code, 302)

        # PlanTask should now have accounting_category saved
        task.refresh_from_db()
        self.assertEqual(task.accounting_category, self.lit_labor)

        # Estimate should have been generated
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)

    def test_post_blocks_when_untyped_direct_tasks_remain(self):
        """POST without assigning all untyped tasks should not generate estimate."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Untyped PlanTask", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"),
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        # POST without any task_accounting_category assignments
        response = self.client.post(url)

        # Should redirect back with error (no estimate created)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Estimate.objects.filter(job=self.job).count(), 0)

    def test_all_typed_tasks_generates_without_assignments(self):
        """POST with all tasks already typed should generate estimate normally."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Typed PlanTask", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit_labor,
        )

        url = reverse('estimates:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.post(url)

        # Should redirect to new estimate
        self.assertEqual(response.status_code, 302)
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)


class TaskDetailAccountingCategoryTests(TestCase):
    """Tests that task_detail shows accounting_category."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass', is_superuser=True)
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_task_detail_shows_accounting_category(self):
        """PlanTask detail should display accounting_category when set."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=ws, name="Sand", accounting_category=self.lit,
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Labor")

    def test_task_detail_no_accounting_category(self):
        """PlanTask detail should handle missing accounting_category gracefully."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=ws, name="Manual PlanTask",
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
