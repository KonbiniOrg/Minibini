"""Tests for estimates app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.estimates.models import (
    Estimate, EstimateLineItem,
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService
from apps.inventory.models import Material
from apps.core.services import NotFoundError
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact, Business


class EstimatesTestBase(TestCase):
    """Shared setUp for estimates service tests."""
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
        self.scheme, _ = RateScheme.objects.get_or_create(
            name='Test Hourly Default', defaults={
                'algorithm': RateScheme.ENTERED_QTY,
                'rate': Decimal('50.00'), 'unit_label': 'hour',
                'accounting_category': self.lit,
            },
        )
        from apps.jobs.services import JobService
        self.job = JobService.create_job(name='Test Job', contact=self.contact)


# --- WorkTemplate CRUD ---

class WorkTemplateServiceCreateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.create_template."""

    def test_create_template(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(
            template_name='Test Template', description='A template',
        )
        self.assertIsNotNone(tmpl.pk)
        self.assertEqual(tmpl.template_name, 'Test Template')

    def test_create_template_minimal(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='Min')
        self.assertIsNotNone(tmpl.pk)


class WorkTemplateServiceUpdateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.update_template."""

    def test_update_template(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='Old')
        updated = WorkTemplateService.update_template(
            tmpl.pk, template_name='New',
        )
        self.assertEqual(updated.template_name, 'New')

    def test_update_template_not_found(self):
        from apps.estimates.services import WorkTemplateService
        with self.assertRaises(NotFoundError):
            WorkTemplateService.update_template(99999, template_name='X')


class WorkTemplateServiceDeleteTest(EstimatesTestBase):
    """Tests for WorkTemplateService.delete_template."""

    def test_delete_template(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='Del')
        pk = tmpl.pk
        WorkTemplateService.delete_template(pk)
        self.assertFalse(WorkTemplate.objects.filter(pk=pk).exists())

    def test_delete_template_not_found(self):
        from apps.estimates.services import WorkTemplateService
        with self.assertRaises(NotFoundError):
            WorkTemplateService.delete_template(99999)


# --- ServiceItem CRUD ---

class ServiceItemServiceCreateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.create_service_item."""

    def test_create_service_item(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_service_item(
            template_name='Welding',
            rate_scheme=self.scheme,
        )
        self.assertIsNotNone(tt.pk)
        self.assertEqual(tt.template_name, 'Welding')
        self.assertEqual(tt.rate_scheme, self.scheme)


class ServiceItemServiceUpdateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.update_service_item."""

    def test_update_service_item(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_service_item(
            template_name='Old',
            rate_scheme=self.scheme,
        )
        updated = WorkTemplateService.update_service_item(
            tt.pk, template_name='New',
        )
        self.assertEqual(updated.template_name, 'New')

    def test_update_service_item_not_found(self):
        from apps.estimates.services import WorkTemplateService
        with self.assertRaises(NotFoundError):
            WorkTemplateService.update_service_item(99999, template_name='X')


class ServiceItemServiceDeleteTest(EstimatesTestBase):
    """Tests for WorkTemplateService.delete_service_item."""

    def test_delete_unused_service_item(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_service_item(
            template_name='Del',
            rate_scheme=self.scheme,
        )
        pk = tt.pk
        WorkTemplateService.delete_service_item(pk)
        self.assertFalse(ServiceItem.objects.filter(pk=pk).exists())

    def test_delete_used_service_item_raises(self):
        """Cannot delete a task template used in a work order template."""
        from apps.estimates.services import WorkTemplateService
        wo_tmpl = WorkTemplateService.create_template(template_name='WO')
        tt = WorkTemplateService.create_service_item(
            template_name='Used',
            rate_scheme=self.scheme,
        )
        TemplateTaskAssociation.objects.create(
            work_template=wo_tmpl, service_item=tt,
        )
        with self.assertRaises(ValidationError):
            WorkTemplateService.delete_service_item(tt.pk)


# --- EstimateService CRUD/status ---

class EstimateServiceCreateTest(EstimatesTestBase):
    """Tests for EstimateService.create_for_job."""

    def test_create_for_job(self):
        est = EstimateService.create_for_job(self.job.pk)
        self.assertIsNotNone(est.pk)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)

    def test_create_for_job_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.create_for_job(99999)

    def test_estimate_number_is_just_the_job_number(self):
        """The estimate_number IS the job number; the revision lives in the
        separate `version` field, not baked into the number."""
        est = EstimateService.create_for_job(self.job.pk)
        self.assertEqual(est.estimate_number, self.job.job_number)
        self.assertEqual(est.version, 1)

    def test_revision_keeps_number_and_increments_version(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='x', price=Decimal('1.00'))
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(est.pk)
        # Number is unchanged (same job); the revision is in `version`.
        self.assertEqual(new_est.estimate_number, self.job.job_number)
        self.assertEqual(new_est.version, 2)


class EstimateServiceStatusTest(EstimatesTestBase):
    """Tests for EstimateService.update_status."""

    def test_update_status_draft_to_open(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        updated = EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        self.assertEqual(updated.status, Estimate.STATUS_OPEN)

    def test_update_status_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.update_status(99999, Estimate.STATUS_OPEN)

    def test_update_status_invalid_transition(self):
        est = EstimateService.create_for_job(self.job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.update_status(est.pk, Estimate.STATUS_ACCEPTED)


class EstimateServiceMarkOpenTest(EstimatesTestBase):
    """Tests for EstimateService.mark_open."""

    def test_mark_open(self):
        from apps.deliverables.models import Deliverable
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        # mark_open requires the job to have at least one Deliverable.
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'), units='ea',
        )
        updated = EstimateService.mark_open(est.pk)
        self.assertEqual(updated.status, Estimate.STATUS_OPEN)

    def test_mark_open_non_draft_raises(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateService.mark_open(est.pk)


class EstimateServiceReviseTest(EstimatesTestBase):
    """Tests for EstimateService.revise_estimate."""

    def test_revise_estimate(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        # Must be non-draft to revise
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(est.pk)
        self.assertEqual(new_est.version, 2)
        self.assertEqual(new_est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(new_est.parent_id, est.pk)
        est.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_SUPERSEDED)

    def test_revise_copies_line_items(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=est, description='Item 1', line_number=1,
            qty=Decimal('1.00'), price=Decimal('10.00'),
            accounting_category=self.lit,
        )
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(est.pk)
        new_items = EstimateLineItem.objects.filter(estimate=new_est)
        self.assertEqual(new_items.count(), 1)
        self.assertEqual(new_items.first().description, 'Item 1')

    def test_revise_draft_raises(self):
        est = EstimateService.create_for_job(self.job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.revise_estimate(est.pk)

    def test_revise_moves_line_item_sources(self):
        """Atom sources MOVE to the revision's copied line items — not
        copied (the unique_together on the atom forbids two claims) and not
        dropped. The atom stays claimed exactly once; the superseded parent's
        line loses the claim."""
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import Task
        task = Task.objects.create(
            job=self.job, name='Mill', rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        est = EstimateService.create_for_job(self.job.pk)
        li = EstimateLineItem.objects.create(
            estimate=est, description='Mill', line_number=1,
            qty=Decimal('2.00'), price=Decimal('50.00'), accounting_category=self.lit,
        )
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)

        new_est = EstimateService.revise_estimate(est.pk)

        # The source row moved onto the revision's copied line item.
        src.refresh_from_db()
        new_li = EstimateLineItem.objects.get(estimate=new_est)
        self.assertEqual(src.estimate_line_item_id, new_li.line_item_id)
        # Parent's line item still exists (frozen) but no longer holds the claim.
        old_li = EstimateLineItem.objects.get(estimate=est)
        self.assertEqual(old_li.sources.count(), 0)
        # Exactly one claim on the atom (unique_together still satisfied).
        self.assertEqual(
            EstimateLineItemSource.objects.filter(
                source_type=EstimateLineItemSource.SOURCE_TASK,
                source_pk=task.pk,
            ).count(),
            1,
        )

    def test_revise_preserves_adjustment_lines(self):
        """revise_estimate must copy adjustment_service (FK) and
        adjustment_target_categories (M2M) onto the revision's copy of
        each percentage-adjustment line item."""
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme

        cat = AccountingCategory.objects.get_or_create(
            code='RUSH', defaults={'name': 'Rush', 'taxable': False},
        )[0]
        rush = RateScheme.objects.create(
            name='Rush Fee', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=cat,
        )
        est = EstimateService.create_for_job(self.job.pk)
        # Base line so the estimate has something to adjust
        EstimateLineItem.objects.create(
            estimate=est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base work', price=Decimal('200.00'),
            accounting_category=cat,
        )
        # Adjustment line with a target category
        EstimateService.add_adjustment_line(
            est,
            adjustment_service_id=rush.pk,
            target_category_ids=[cat.pk],
        )
        # Must be non-draft to revise
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)

        new_est = EstimateService.revise_estimate(est.pk)

        adj_lines = EstimateLineItem.objects.filter(
            estimate=new_est,
            adjustment_service__isnull=False,
        )
        self.assertEqual(adj_lines.count(), 1, 'Revision should have one adjustment line')
        new_adj = adj_lines.first()
        self.assertEqual(new_adj.adjustment_service_id, rush.pk)
        target_cats = list(new_adj.adjustment_target_categories.values_list('pk', flat=True))
        self.assertIn(cat.pk, target_cats)


# EstimateServiceAddLineItemTest removed in Phase 6 — EstimateService.add_line_item /
# add_line_item_from_pli are gone (estimate lines come only from atoms).


class EstimateServiceReorderLineItemTest(EstimatesTestBase):
    """Tests for EstimateService.reorder_line_item."""

    def setUp(self):
        super().setUp()
        self.est = EstimateService.create_for_job(self.job.pk)
        self.li1 = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Item 1',
            qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        self.li2 = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, description='Item 2',
            qty=1, price=Decimal('20.00'), accounting_category=self.lit,
        )

    def test_reorder_down(self):
        EstimateService.reorder_line_item(self.li1.pk, 'down')
        self.li1.refresh_from_db()
        self.li2.refresh_from_db()
        self.assertEqual(self.li1.line_number, 2)
        self.assertEqual(self.li2.line_number, 1)

    def test_reorder_non_draft_raises(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateService.reorder_line_item(self.li1.pk, 'down')

    def test_reorder_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.reorder_line_item(99999, 'down')


class EstimateServiceDeleteLineItemTest(EstimatesTestBase):
    """Tests for EstimateService.delete_line_item."""

    def setUp(self):
        super().setUp()
        self.est = EstimateService.create_for_job(self.job.pk)
        self.li1 = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Item 1',
            qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        self.li2 = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, description='Item 2',
            qty=1, price=Decimal('20.00'), accounting_category=self.lit,
        )

    def test_delete_and_renumber(self):
        EstimateService.delete_line_item(self.li1.pk)
        self.assertFalse(EstimateLineItem.objects.filter(pk=self.li1.pk).exists())
        self.li2.refresh_from_db()
        self.assertEqual(self.li2.line_number, 1)

    def test_delete_non_draft_raises(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateService.delete_line_item(self.li1.pk)

    def test_delete_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.delete_line_item(99999)


# --- WorkTemplateService.delete_association ---

class WorkTemplateServiceDeleteAssociationTest(EstimatesTestBase):
    """Tests for WorkTemplateService.delete_association."""

    def test_delete_unbundled_association(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='T')
        tt = WorkTemplateService.create_service_item(
            template_name='Task',
            rate_scheme=self.scheme,
        )
        assoc = TemplateTaskAssociation.objects.create(
            work_template=tmpl, service_item=tt,
            sort_order=1,
        )
        pk = assoc.pk
        WorkTemplateService.delete_association(tmpl.pk, pk)
        self.assertFalse(TemplateTaskAssociation.objects.filter(pk=pk).exists())

    def test_delete_association_not_found(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='T')
        with self.assertRaises(NotFoundError):
            WorkTemplateService.delete_association(tmpl.pk, 99999)

    def test_delete_association_wrong_template(self):
        from apps.estimates.services import WorkTemplateService
        tmpl1 = WorkTemplateService.create_template(template_name='T1')
        tmpl2 = WorkTemplateService.create_template(template_name='T2')
        tt = WorkTemplateService.create_service_item(
            template_name='Task',
            rate_scheme=self.scheme,
        )
        assoc = TemplateTaskAssociation.objects.create(
            work_template=tmpl1, service_item=tt,
            sort_order=1,
        )
        with self.assertRaises(NotFoundError):
            WorkTemplateService.delete_association(tmpl2.pk, assoc.pk)


class EstimateServiceDiscardDraftTest(EstimatesTestBase):
    """Tests for EstimateService.discard_draft."""

    def _make_estimate_with_sources(self):
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        task = Task.objects.create(
            job=self.job, name='T1',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        material = Material.objects.create(
            job=self.job, description='steel',
            quantity=Decimal('2'), sell_price=Decimal('5'),
            accounting_category=self.lit,
        )
        estimate = EstimateService.create_for_job(self.job.pk)
        line_item = EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('1'), units='each',
            price=Decimal('10'), description='', accounting_category=self.lit,
        )
        src1 = EstimateLineItemSource.objects.create(
            estimate_line_item=line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        src2 = EstimateLineItemSource.objects.create(
            estimate_line_item=line_item,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        return estimate, line_item, src1, src2

    def test_discard_draft_cascades_estimate_line_items_and_sources(self):
        from apps.estimates.models import EstimateLineItemSource
        estimate, line_item, src1, src2 = self._make_estimate_with_sources()

        EstimateService.discard_draft(estimate)

        self.assertFalse(Estimate.objects.filter(pk=estimate.pk).exists())
        self.assertFalse(EstimateLineItem.objects.filter(pk=line_item.pk).exists())
        self.assertFalse(
            EstimateLineItemSource.objects.filter(pk__in=[src1.pk, src2.pk]).exists()
        )

    def test_discard_draft_rejects_non_draft(self):
        estimate = EstimateService.create_for_job(self.job.pk)
        Estimate.objects.filter(pk=estimate.pk).update(status=Estimate.STATUS_OPEN)
        estimate.refresh_from_db()
        with self.assertRaises(ValidationError):
            EstimateService.discard_draft(estimate)


# --- Adjustment line service methods ---

class EstimateAdjustmentLineServiceTest(EstimatesTestBase):
    """Tests for EstimateService.add_adjustment_line and auto-recompute."""

    def setUp(self):
        super().setUp()
        # Create a draft estimate with two base lines totaling 140
        self.labor = AccountingCategory.objects.get(pk=901)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Line A', price=Decimal('100.00'),
            accounting_category=self.labor,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='ea', description='Line B', price=Decimal('40.00'),
            accounting_category=self.labor,
        )

    def test_add_adjustment_line_computes_price(self):
        rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.labor,
        )
        line = EstimateService.add_adjustment_line(
            self.est, adjustment_service_id=rush.pk, target_category_ids=[])
        self.assertEqual(line.price, Decimal('21.00'))
        self.assertEqual(line.description, 'Rush')
        self.assertEqual(line.adjustment_service_id, rush.pk)

    def test_add_adjustment_rejects_non_draft(self):
        rush = RateScheme.objects.create(
            name='Rush2', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.labor,
        )
        Estimate.objects.filter(pk=self.est.pk).update(status=Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        with self.assertRaises(ValidationError):
            EstimateService.add_adjustment_line(
                self.est, adjustment_service_id=rush.pk)

    def test_add_adjustment_rejects_non_percentage_service(self):
        non_pct = RateScheme.objects.create(
            name='NonPct', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hr',
            accounting_category=self.labor,
        )
        with self.assertRaises(ValidationError):
            EstimateService.add_adjustment_line(
                self.est, adjustment_service_id=non_pct.pk)
