"""Tests for BundlingService and domain-level bundling operations."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import models
from apps.estimates.models import (
    EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.estimates.services import WorkTemplateService, WorksheetService
from apps.jobs.models import Job, PlanTask
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


class BundlingServiceReorderContainerFlatTest(BundlingTestBase):
    """Tests for BundlingService.reorder_container_items with flat (no-bundle) PlanTasks."""

    def setUp(self):
        super().setUp()
        self.ws = EstWorksheet.objects.create(job=self.job, status=Job.STATUS_DRAFT)

    def test_unbundled_only_swap(self):
        """Simple swap with no bundles present."""
        a = PlanTask.objects.create(est_worksheet=self.ws, name='A', sort_order=1)
        b = PlanTask.objects.create(est_worksheet=self.ws, name='B', sort_order=2)
        c = PlanTask.objects.create(est_worksheet=self.ws, name='C', sort_order=3)

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
        t1 = PlanTask.objects.create(est_worksheet=self.ws, name='Only', sort_order=1)
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
        self.t1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
        )
        self.t2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
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

    def test_reorder_non_draft_raises(self):
        """Cannot reorder on non-draft worksheet."""
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
        with self.assertRaises(ValidationError):
            WorksheetService.reorder_items(
                self.ws.pk, 'task', self.t1.pk, 'down',
            )


# --- WorkTemplateService domain bundling tests ---

class TemplateServiceBundleTest(BundlingTestBase):
    """Tests for WorkTemplateService.bundle_associations."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkTemplateService.create_task_template(
            template_name='TT1', accounting_category=self.lit,
        )
        self.tt2 = WorkTemplateService.create_task_template(
            template_name='TT2', accounting_category=self.lit,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt1, sort_order=1,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt2, sort_order=2,
        )

    def test_bundle_associations(self):
        """Bundle associations on a template."""
        bundle = WorkTemplateService.bundle_associations(
            self.tmpl.pk, [self.a1.pk, self.a2.pk],
            bundle_name='My Bundle', accounting_category=self.lit,
        )
        self.assertIsNotNone(bundle.pk)
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.mapping_strategy, 'bundle')
        self.assertEqual(self.a2.mapping_strategy, 'bundle')
        self.assertEqual(self.a1.bundle, bundle)

    def test_bundle_requires_two(self):
        """Cannot bundle fewer than 2 associations."""
        with self.assertRaises(ValidationError):
            WorkTemplateService.bundle_associations(
                self.tmpl.pk, [self.a1.pk],
                bundle_name='Solo', accounting_category=self.lit,
            )


class TemplateServiceUnbundleTest(BundlingTestBase):
    """Tests for WorkTemplateService.unbundle_association."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkTemplateService.create_task_template(
            template_name='TT1', accounting_category=self.lit,
        )
        self.tt2 = WorkTemplateService.create_task_template(
            template_name='TT2', accounting_category=self.lit,
        )
        self.tt3 = WorkTemplateService.create_task_template(
            template_name='TT3', accounting_category=self.lit,
        )
        self.bundle = TemplateBundle.objects.create(
            work_template=self.tmpl, name='Bundle',
            accounting_category=self.lit, sort_order=5,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt1,
            sort_order=1, mapping_strategy='bundle', bundle=self.bundle,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt2,
            sort_order=2, mapping_strategy='bundle', bundle=self.bundle,
        )
        self.a3 = TemplateTaskAssociation.objects.create(
            work_template=self.tmpl, task_template=self.tt3,
            sort_order=3, mapping_strategy='bundle', bundle=self.bundle,
        )

    def test_unbundle_association(self):
        """Unbundle an association from a template bundle."""
        WorkTemplateService.unbundle_association(self.tmpl.pk, self.a1.pk)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.mapping_strategy, 'direct')
        self.assertIsNone(self.a1.bundle)

    def test_unbundle_dissolves_single_remaining(self):
        """Auto-dissolves bundle when only 1 association remains."""
        WorkTemplateService.unbundle_association(self.tmpl.pk, self.a1.pk)
        WorkTemplateService.unbundle_association(self.tmpl.pk, self.a2.pk)
        self.a3.refresh_from_db()
        self.assertEqual(self.a3.mapping_strategy, 'direct')
        self.assertFalse(TemplateBundle.objects.filter(pk=self.bundle.pk).exists())


class TemplateServiceReorderTest(BundlingTestBase):
    """Tests for WorkTemplateService reorder methods."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkTemplateService.create_task_template(
            template_name='TT1', accounting_category=self.lit,
        )
        self.tt2 = WorkTemplateService.create_task_template(
            template_name='TT2', accounting_category=self.lit,
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

    def test_reorder_in_bundle(self):
        """Reorder associations within a bundle."""
        bundle = TemplateBundle.objects.create(
            work_template=self.tmpl, name='B',
            accounting_category=self.lit, sort_order=10,
        )
        self.a1.mapping_strategy = 'bundle'
        self.a1.bundle = bundle
        self.a1.sort_order = 1
        self.a1.save()
        self.a2.mapping_strategy = 'bundle'
        self.a2.bundle = bundle
        self.a2.sort_order = 2
        self.a2.save()

        WorkTemplateService.reorder_in_bundle(
            self.tmpl.pk, self.a1.pk, 'down',
        )
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.sort_order, 2)
        self.assertEqual(self.a2.sort_order, 1)
