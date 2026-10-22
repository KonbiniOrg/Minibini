"""Tests for ReorderService and domain-level reorder operations."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import models
from apps.estimates.models import (
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.estimates.services import WorkTemplateService
from apps.jobs.models import Job, Task, RateScheme
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
            email='test@test.com', phones=[{'number': '555-1234', 'label': 'work'}],
        )
        self.business = Business.objects.create(
            business_name='Test Biz', phones=[{'number': '555-1234', 'label': ''}],
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.lit, _ = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': True},
        )
        self.job = JobService.create_job(name='Test Job', contact=self.contact)


class ReorderServiceTest(BundlingTestBase):
    """Tests for ReorderService.reorder_container_items with flat Tasks."""

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture

    def test_unbundled_only_swap(self):
        """Simple swap with no bundles present."""
        a = Task(
            job=self.job, name='A', sort_order=1, est_qty=Decimal('1'),
        )
        a.stamp_from_scheme(self.scheme)
        a.save()
        b = Task(
            job=self.job, name='B', sort_order=2, est_qty=Decimal('1'),
        )
        b.stamp_from_scheme(self.scheme)
        b.save()
        c = Task(
            job=self.job, name='C', sort_order=3, est_qty=Decimal('1'),
        )
        c.stamp_from_scheme(self.scheme)
        c.save()

        items_qs = Task.objects.filter(job=self.job)
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
        t1 = Task(
            job=self.job, name='Only', sort_order=1, est_qty=Decimal('1'),
        )
        t1.stamp_from_scheme(self.scheme)
        t1.save()
        items_qs = Task.objects.filter(job=self.job)
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


class ReorderServiceSetOrderTest(BundlingTestBase):
    """ReorderService.set_order: the shared full-order reorder (issue #513).
    Every drag-and-drop list uses it; tasks are the first caller."""

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture
        self.tasks = []
        for n, name in enumerate(['A', 'B', 'C'], start=1):
            t = Task(job=self.job, name=name, sort_order=n, est_qty=Decimal('1'))
            t.stamp_from_scheme(self.scheme)
            t.save()
            self.tasks.append(t)
        self.a, self.b, self.c = self.tasks
        self.qs = Task.objects.filter(job=self.job)

    def names_in_order(self):
        return list(self.qs.order_by('sort_order', 'pk').values_list('name', flat=True))

    def test_applies_the_whole_order(self):
        BundlingService.set_order(self.qs, [self.c.pk, self.a.pk, self.b.pk])
        self.assertEqual(self.names_in_order(), ['C', 'A', 'B'])

    def test_numbers_from_start(self):
        BundlingService.set_order(self.qs, [self.c.pk, self.a.pk, self.b.pk], start=1)
        self.c.refresh_from_db()
        self.assertEqual(self.c.sort_order, 1)

    def test_saves_only_items_whose_position_changed(self):
        from unittest import mock
        with mock.patch.object(Task, 'save', autospec=True, side_effect=Task.save) as save:
            # Swap B and C; A stays at 1.
            BundlingService.set_order(self.qs, [self.a.pk, self.c.pk, self.b.pk])
        saved = {call.args[0].pk for call in save.call_args_list}
        self.assertEqual(saved, {self.b.pk, self.c.pk})

    def test_refuses_a_partial_list(self):
        with self.assertRaises(ValidationError) as ctx:
            BundlingService.set_order(self.qs, [self.b.pk, self.a.pk], error_field='task_ids')
        self.assertIn('task_ids', ctx.exception.message_dict)
        self.assertEqual(self.names_in_order(), ['A', 'B', 'C'])

    def test_refuses_a_foreign_id(self):
        other_job = JobService.create_job(name='Other', contact=self.contact)
        x = Task(job=other_job, name='X', sort_order=1, est_qty=Decimal('1'))
        x.stamp_from_scheme(self.scheme)
        x.save()
        with self.assertRaises(ValidationError):
            BundlingService.set_order(self.qs, [self.a.pk, self.b.pk, self.c.pk, x.pk])

    def test_refuses_duplicates(self):
        with self.assertRaises(ValidationError):
            BundlingService.set_order(self.qs, [self.a.pk, self.a.pk, self.b.pk, self.c.pk])

    def test_refuses_a_non_list(self):
        for bad in ('abc', None, [self.a.pk, 'b', self.c.pk], [True, self.b.pk, self.c.pk]):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                BundlingService.set_order(self.qs, bad)

    def test_custom_field(self):
        """Line items order by line_number; the field is a parameter."""
        BundlingService.set_order(self.qs, [self.b.pk, self.c.pk, self.a.pk], field='sort_order', start=10)
        self.b.refresh_from_db()
        self.assertEqual(self.b.sort_order, 10)
