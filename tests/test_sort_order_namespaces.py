"""Tests for sort_order namespace separation on PlanTasks and template reordering."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import PlanTask, Job
from apps.estimates.models import EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation
from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory


class SortOrderAutoGenerationTest(TestCase):
    """PlanTask.save() auto-generation should place tasks sequentially."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit, _ = AccountingCategory.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_new_task_gets_sequential_sort_order(self):
        """Tasks without an explicit sort_order get next sequential value."""
        t1 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task 1', rate=10
        )
        t2 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task 2', rate=20
        )
        t3 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task 3', rate=30
        )
        self.assertEqual(t1.sort_order, 1)
        self.assertEqual(t2.sort_order, 2)
        self.assertEqual(t3.sort_order, 3)

    def test_explicit_sort_order_preserved(self):
        """Tasks with explicit sort_order are not auto-reassigned."""
        t = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task', rate=10, sort_order=42
        )
        self.assertEqual(t.sort_order, 42)


class GenerateTaskSortOrderTest(TestCase):
    """generate_tasks_for_worksheet should pass association sort_order through."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.lit_labor, _ = AccountingCategory.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_generated_tasks_get_association_sort_order(self):
        """Tasks should get the association's sort_order."""
        wot = WorkTemplate.objects.create(template_name='Test Template')
        tt1 = TaskTemplate.objects.create(
            template_name='Sand', rate=50, accounting_category=self.lit_labor
        )
        tt2 = TaskTemplate.objects.create(
            template_name='Clean', rate=25, accounting_category=self.lit_labor
        )
        # Use non-sequential sort_orders to verify they pass through
        TemplateTaskAssociation.objects.create(
            work_template=wot, task_template=tt1,
            est_qty=1, sort_order=5
        )
        TemplateTaskAssociation.objects.create(
            work_template=wot, task_template=tt2,
            est_qty=1, sort_order=10
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        sand = next(t for t in tasks if t.name == 'Sand')
        clean = next(t for t in tasks if t.name == 'Clean')
        self.assertEqual(sand.sort_order, 5)
        self.assertEqual(clean.sort_order, 10)
