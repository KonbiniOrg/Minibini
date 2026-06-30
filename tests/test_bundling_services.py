"""Tests for ReorderService and domain-level reorder operations."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import models
from apps.estimates.models import (
    EstWorksheet, WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.estimates.services import WorkTemplateService
from apps.jobs.models import Job, PlanTask, RateScheme
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
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture

    def test_unbundled_only_swap(self):
        """Simple swap with no bundles present."""
        a = PlanTask.objects.create(
            est_worksheet=self.ws, name='A', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        b = PlanTask.objects.create(
            est_worksheet=self.ws, name='B', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        c = PlanTask.objects.create(
            est_worksheet=self.ws, name='C', sort_order=3,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
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
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        items_qs = PlanTask.objects.filter(est_worksheet=self.ws)
        with self.assertRaises(ValidationError):
            BundlingService.reorder_container_items(
                items_qs, 'task', t1.pk, 'up',
            )


class TemplateServiceReorderTest(BundlingTestBase):
    """Tests for WorkTemplateService reorder methods."""

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture
        self.tmpl = WorkTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkTemplateService.create_service_item(
            template_name='TT1',
            rate_scheme=self.scheme,
        )
        self.tt2 = WorkTemplateService.create_service_item(
            template_name='TT2',
            rate_scheme=self.scheme,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, service_item=self.tt1, sort_order=1,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, service_item=self.tt2, sort_order=2,
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
