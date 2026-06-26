"""Tests for ReorderService and domain-level reorder operations."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import models
from apps.estimates.models import (
    EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.estimates.services import WorkTemplateService, WorksheetService
from apps.jobs.models import Job, PlanTask, ServiceItem
from apps.jobs.services import JobService
from apps.core.services import NotFoundError, BundlingService
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact, Business


class BundlingTestBase(TestCase):
    """Shared setUp for bundling tests."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.lit, _ = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': True},
        )
        self.job = JobService.create_job(name='Test Job', contact=self.contact)


class ReorderServiceTest(BundlingTestBase):
    """Tests for ReorderService.reorder_container_items with flat PlanTasks."""

    def setUp(self):
        super().setUp()
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = ServiceItem.objects.get(pk=1)  # from fixture

    def test_unbundled_only_swap(self):
        """Simple swap with no bundles present."""
        a = PlanTask.objects.create(
            est_worksheet=self.ws, name='A', sort_order=1,
            service_item=self.scheme, est_qty=Decimal('1'),
        )
        b = PlanTask.objects.create(
            est_worksheet=self.ws, name='B', sort_order=2,
            service_item=self.scheme, est_qty=Decimal('1'),
        )
        c = PlanTask.objects.create(
            est_worksheet=self.ws, name='C', sort_order=3,
            service_item=self.scheme, est_qty=Decimal('1'),
        )

        items_qs = PlanTask.objects.filter(est_worksheet=self.ws)
        BundlingService.reorder_container_items(
            items_qs, 'task', b.pk, 'down',
        )
        b.refresh_from_db()
        c.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual(a.sort_order, 1)
        self.assertEqual(b.sort_order, 3)
        self.assertEqual(c.sort_order, 2)

    def test_cannot_move_past_boundary(self):
        """Moving beyond boundaries raises ValidationError."""
        t1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='Only', sort_order=1,
            service_item=self.scheme, est_qty=Decimal('1'),
        )
        items_qs = PlanTask.objects.filter(est_worksheet=self.ws)
        with self.assertRaises(ValidationError):
            BundlingService.reorder_container_items(
                items_qs, 'task', t1.pk, 'up',
            )


class WorksheetServiceReorderTest(BundlingTestBase):
    """Tests for WorksheetService reorder methods."""

    def setUp(self):
        super().setUp()
        self.ws = WorksheetService.create_worksheet(self.job.pk)
        self.scheme = ServiceItem.objects.get(pk=1)  # from fixture
        self.t1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
            service_item=self.scheme, est_qty=Decimal('1'),
        )
        self.t2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
            service_item=self.scheme, est_qty=Decimal('1'),
        )

    def test_reorder_items(self):
        """Reorder tasks at container level."""
        WorksheetService.reorder_items(
            self.ws.pk, 'task', self.t1.pk, 'down',
        )
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.t2.sort_order, 1)

    def test_reorder_refused_when_estimate_sent(self):
        """Cannot reorder once the job's estimate is sent (worksheet frozen)."""
        from apps.estimates.models import Estimate
        est = Estimate.objects.create(
            job=self.ws.job, estimate_number='EST-REORD-1',
            status=Estimate.STATUS_DRAFT,
        )
        Estimate.objects.filter(pk=est.pk).update(status=Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            WorksheetService.reorder_items(
                self.ws.pk, 'task', self.t1.pk, 'down',
            )


class TemplateServiceReorderTest(BundlingTestBase):
    """Tests for WorkTemplateService reorder methods."""

    def setUp(self):
        super().setUp()
        self.scheme = ServiceItem.objects.get(pk=1)  # from fixture
        self.tmpl = WorkTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkTemplateService.create_task_template(
            template_name='TT1',
            service_item=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.tt2 = WorkTemplateService.create_task_template(
            template_name='TT2',
            service_item=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt1, sort_order=1,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt2, sort_order=2,
        )

    def test_reorder_items(self):
        """Reorder associations at container level."""
        WorkTemplateService.reorder_items(
            self.tmpl.pk, 'task', self.a1.pk, 'down',
        )
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.sort_order, 2)
        self.assertEqual(self.a2.sort_order, 1)
