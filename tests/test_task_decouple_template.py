"""
Tests for decoupling Task from TaskTemplate.
Part 1: Task.line_item_type field, copying at creation points, use in estimate generation.
Part 2: Line item type review at estimate generation.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.db.models import ProtectedError

from apps.jobs.models import (
    TaskTemplate, WorkOrderTemplate, TemplateTaskAssociation, TemplateBundle,
    TaskBundle, Job, EstWorksheet, Task, Estimate, EstimateLineItem, WorkOrder
)
from apps.jobs.services import EstimateGenerationService, TaskService, LineItemTaskService
from apps.core.models import LineItemType, Configuration, User
from apps.contacts.models import Contact


class TaskLineItemTypeFieldTests(TestCase):
    """Tests that Task has a line_item_type FK field."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = LineItemType.objects.create(name="Labor", code="LBR")

    def test_task_can_have_line_item_type(self):
        """Task should have a line_item_type FK field."""
        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name="Sand Surface",
            line_item_type=self.lit,
        )
        task.refresh_from_db()
        self.assertEqual(task.line_item_type, self.lit)

    def test_task_line_item_type_nullable(self):
        """Task.line_item_type can be null (manual tasks, work order tasks)."""
        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name="Manual Task",
        )
        self.assertIsNone(task.line_item_type)

    def test_task_line_item_type_protected(self):
        """Cannot delete LineItemType if a Task references it."""
        Task.objects.create(
            est_worksheet=self.worksheet,
            name="Sand",
            line_item_type=self.lit,
        )
        with self.assertRaises(ProtectedError):
            self.lit.delete()


class GenerateTaskCopiesLineItemTypeTests(TestCase):
    """Tests that TaskTemplate.generate_task() copies line_item_type to the Task."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = LineItemType.objects.create(name="Labor", code="LBR")

    def test_generate_task_copies_line_item_type(self):
        """generate_task() should copy line_item_type from template to task."""
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), line_item_type=self.lit
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("2.00"))
        self.assertEqual(task.line_item_type, self.lit)

    def test_generate_task_null_line_item_type(self):
        """generate_task() with template having no line_item_type produces task with null."""
        tt = TaskTemplate.objects.create(
            template_name="Check", rate=Decimal("0.00"), line_item_type=None
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("1.00"))
        self.assertIsNone(task.line_item_type)

    def test_generate_tasks_for_worksheet_copies_line_item_type(self):
        """Full template generation copies line_item_type to each task."""
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet")
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), line_item_type=self.lit
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt,
            est_qty=Decimal("2.00"), mapping_strategy='direct'
        )
        tasks = wot.generate_tasks_for_worksheet(self.worksheet)
        self.assertEqual(tasks[0].line_item_type, self.lit)


class CopyPointsPreserveLineItemTypeTests(TestCase):
    """Tests that all task-copying code preserves line_item_type."""

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
        self.lit = LineItemType.objects.create(name="Labor", code="LBR")

    def test_create_new_version_copies_line_item_type(self):
        """EstWorksheet.create_new_version() should copy line_item_type to new tasks."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), line_item_type=self.lit,
        )
        # Generate estimate so worksheet can create new version
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        ws.status = 'final'
        ws.save()

        new_ws = ws.create_new_version()
        new_task = new_ws.task_set.first()
        self.assertEqual(new_task.line_item_type, self.lit)

    def test_copy_worksheet_tasks_copies_line_item_type(self):
        """_copy_worksheet_tasks should copy line_item_type to work order tasks."""
        ws = EstWorksheet.objects.create(job=self.job)
        source_task = Task.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), line_item_type=self.lit,
        )
        # Create estimate + line item referencing the task
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()

        wo = WorkOrder.objects.create(job=self.job)
        tasks = LineItemTaskService._copy_worksheet_tasks(line_item, wo)
        self.assertEqual(tasks[0].line_item_type, self.lit)


class EstimateGenerationUsesTaskLineItemTypeTests(TestCase):
    """Tests that estimate generation reads task.line_item_type directly."""

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
        self.lit_labor, _ = LineItemType.objects.get_or_create(code="LBR", defaults={"name": "Labor"})
        self.lit_material, _ = LineItemType.objects.get_or_create(code="MAT", defaults={"name": "Material"})

    def test_direct_task_uses_own_line_item_type(self):
        """Direct task's line_item_type (not template's) should be used in estimate generation."""
        ws = EstWorksheet.objects.create(job=self.job)
        # Create task with line_item_type directly - no template needed
        Task.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), line_item_type=self.lit_labor,
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()
        self.assertEqual(line_item.line_item_type, self.lit_labor)

    def test_task_without_line_item_type_gets_default(self):
        """Task without line_item_type should get default type during estimate generation."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Manual Task", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(ws)
        line_item = estimate.estimatelineitem_set.first()
        # Should have a line_item_type (the default fallback)
        self.assertIsNotNone(line_item.line_item_type)


# =============================================================================
# Part 2: Line item type review at estimate generation
# =============================================================================


class EstimateGenerationReviewPageTests(TestCase):
    """Tests for the estimate generation confirmation page with line_item_type review."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter', defaults={'value': '0'}
        )
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit_material, _ = LineItemType.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )

    def test_get_shows_untyped_tasks(self):
        """GET should identify direct tasks missing line_item_type."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Typed Task", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), line_item_type=self.lit_labor,
        )
        Task.objects.create(
            est_worksheet=ws, name="Untyped Task", rate=Decimal("30.00"),
            est_qty=Decimal("1.00"),
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('untyped_tasks', response.context)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 1)
        self.assertEqual(untyped[0].name, "Untyped Task")

    def test_get_passes_line_item_types(self):
        """GET should pass available line_item_types to template."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Task", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"),
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        self.assertIn('line_item_types', response.context)

    def test_excluded_tasks_not_in_untyped(self):
        """Excluded tasks should not appear in untyped_tasks even if they lack line_item_type."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Excluded Task", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"), mapping_strategy='exclude',
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 0)

    def test_bundled_tasks_not_in_untyped(self):
        """Bundled tasks should not appear in untyped_tasks (bundle has its own line_item_type)."""
        ws = EstWorksheet.objects.create(job=self.job)
        bundle = TaskBundle.objects.create(
            est_worksheet=ws, name="Bundle", line_item_type=self.lit_labor,
        )
        Task.objects.create(
            est_worksheet=ws, name="Bundled Task", rate=Decimal("10.00"),
            est_qty=Decimal("1.00"), mapping_strategy='bundle', bundle=bundle,
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.get(url)
        untyped = response.context['untyped_tasks']
        self.assertEqual(len(untyped), 0)

    def test_post_saves_line_item_types_and_generates(self):
        """POST with task_line_item_type assignments should save them then generate estimate."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = Task.objects.create(
            est_worksheet=ws, name="Untyped Task", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"),
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.post(url, {
            f'task_line_item_type_{task.pk}': self.lit_labor.pk,
        })

        # Should redirect to the new estimate
        self.assertEqual(response.status_code, 302)

        # Task should now have line_item_type saved
        task.refresh_from_db()
        self.assertEqual(task.line_item_type, self.lit_labor)

        # Estimate should have been generated
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)

    def test_post_blocks_when_untyped_direct_tasks_remain(self):
        """POST without assigning all untyped tasks should not generate estimate."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Untyped Task", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"),
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        # POST without any task_line_item_type assignments
        response = self.client.post(url)

        # Should redirect back with error (no estimate created)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Estimate.objects.filter(job=self.job).count(), 0)

    def test_all_typed_tasks_generates_without_assignments(self):
        """POST with all tasks already typed should generate estimate normally."""
        ws = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=ws, name="Typed Task", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), line_item_type=self.lit_labor,
        )

        url = reverse('jobs:estworksheet_generate_estimate', args=[ws.pk])
        response = self.client.post(url)

        # Should redirect to new estimate
        self.assertEqual(response.status_code, 302)
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)


class TaskDetailLineItemTypeTests(TestCase):
    """Tests that task_detail shows line_item_type."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit = LineItemType.objects.create(name="Labor", code="LBR")

    def test_task_detail_shows_line_item_type(self):
        """Task detail should display line_item_type when set."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = Task.objects.create(
            est_worksheet=ws, name="Sand", line_item_type=self.lit,
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Labor")

    def test_task_detail_no_line_item_type(self):
        """Task detail should handle missing line_item_type gracefully."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = Task.objects.create(
            est_worksheet=ws, name="Manual Task",
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
