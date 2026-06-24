"""
Tests for Task description field and decoupling task data from templates.

Tasks should have their own description field. When created from a template,
the description is copied from the template. After creation, the task's
description is independent of the template.

NOTE: HTML-view subclasses (TaskDescriptionInViewsTests,
WorksheetDescriptionFromTaskTests, TaskAddManualDescriptionTests, and the
view test inside TaskDescriptionFromTemplateTests) have been removed —
those views are being deleted as part of the broader HTML-view sunset.
"""

from django.test import TestCase
from apps.jobs.models import Job, PlanTask, ServicePrice
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from decimal import Decimal


def _make_scheme(suffix, ac):
    return ServicePrice.objects.create(
        name=f'S-td-{suffix}', algorithm=ServicePrice.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class TaskDescriptionModelTests(TestCase):
    """Test that Task has its own description field."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-DESC-001', contact=self.contact, status=Job.STATUS_APPROVED
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.tdm_ac = AccountingCategory.objects.create(name='tdm-ac', code='TDM-AC')
        self.scheme = _make_scheme('tdm', self.tdm_ac)

    def test_task_can_have_description(self):
        """Task should have a description field that can be set directly."""
        task = PlanTask.objects.create(
            name='Described Task',
            description='This is a task description',
            est_worksheet=self.worksheet,
            service_price=self.scheme,
            est_qty=Decimal('1'),
        )
        task.refresh_from_db()
        self.assertEqual(task.description, 'This is a task description')

    def test_task_description_defaults_to_blank(self):
        """Task description should default to empty string."""
        task = PlanTask.objects.create(
            name='No Description Task',
            est_worksheet=self.worksheet,
            service_price=self.scheme,
            est_qty=Decimal('1'),
        )
        task.refresh_from_db()
        self.assertEqual(task.description, '')


class TaskDescriptionFromTemplateTests(TestCase):
    """Test that description is copied from template when creating tasks."""

    def setUp(self):
        self.accounting_category = AccountingCategory.objects.create(name='Labor')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-DESC-002', contact=self.contact, status=Job.STATUS_APPROVED
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme = _make_scheme('dft', self.accounting_category)
        self.task_template = TaskTemplate.objects.create(
            template_name='Painting',
            description='Apply two coats of primer and paint',
            service_price=self.scheme,
            default_billable_qty=Decimal('1.00'),
        )

    def test_generate_task_copies_description_from_template(self):
        """TaskTemplate.generate_task() should copy description to the new task."""
        task = self.task_template.generate_task(
            self.worksheet, est_qty=Decimal('100.00')
        )
        self.assertEqual(task.description, 'Apply two coats of primer and paint')
