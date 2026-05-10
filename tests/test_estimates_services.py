"""Tests for estimates app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.jobs.services import JobService
from apps.inventory.models import Material, PlanMaterial
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


# --- TaskTemplate CRUD ---

class TaskTemplateServiceCreateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.create_task_template."""

    def test_create_task_template(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_task_template(
            template_name='Welding',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.assertIsNotNone(tt.pk)
        self.assertEqual(tt.template_name, 'Welding')
        self.assertEqual(tt.rate_scheme, self.scheme)


class TaskTemplateServiceUpdateTest(EstimatesTestBase):
    """Tests for WorkTemplateService.update_task_template."""

    def test_update_task_template(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_task_template(
            template_name='Old',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        updated = WorkTemplateService.update_task_template(
            tt.pk, template_name='New',
        )
        self.assertEqual(updated.template_name, 'New')

    def test_update_task_template_not_found(self):
        from apps.estimates.services import WorkTemplateService
        with self.assertRaises(NotFoundError):
            WorkTemplateService.update_task_template(99999, template_name='X')


class TaskTemplateServiceDeleteTest(EstimatesTestBase):
    """Tests for WorkTemplateService.delete_task_template."""

    def test_delete_unused_task_template(self):
        from apps.estimates.services import WorkTemplateService
        tt = WorkTemplateService.create_task_template(
            template_name='Del',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        pk = tt.pk
        WorkTemplateService.delete_task_template(pk)
        self.assertFalse(TaskTemplate.objects.filter(pk=pk).exists())

    def test_delete_used_task_template_raises(self):
        """Cannot delete a task template used in a work order template."""
        from apps.estimates.services import WorkTemplateService
        wo_tmpl = WorkTemplateService.create_template(template_name='WO')
        tt = WorkTemplateService.create_task_template(
            template_name='Used',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        TemplateTaskAssociation.objects.create(
            work_template=wo_tmpl, task_template=tt,
        )
        with self.assertRaises(ValidationError):
            WorkTemplateService.delete_task_template(tt.pk)


# --- EstimateService CRUD/status ---

class EstimateServiceCreateTest(EstimatesTestBase):
    """Tests for EstimateService.create_for_job."""

    def test_create_for_job(self):
        est = EstimateService.create_for_job(self.job.pk)
        self.assertIsNotNone(est.pk)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)
        self.assertTrue(est.estimate_number.startswith('EST'))

    def test_create_for_job_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.create_for_job(99999)


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
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        updated = EstimateService.mark_open(est.pk)
        self.assertEqual(updated.status, Estimate.STATUS_OPEN)

    def test_mark_open_updates_worksheet(self):
        est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(estimate=est, description='Test item', price=Decimal('100.00'))
        ws = EstWorksheet.objects.create(
            job=self.job, estimate=est, status=Job.STATUS_DRAFT,
        )
        EstimateService.mark_open(est.pk)
        ws.refresh_from_db()
        self.assertEqual(ws.status, EstWorksheet.STATUS_FINAL)

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


class EstimateServiceAddLineItemTest(EstimatesTestBase):
    """Tests for EstimateService.add_line_item and add_line_item_from_pli."""

    def setUp(self):
        super().setUp()
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_add_line_item_manual(self):
        li = EstimateService.add_line_item(
            self.est.pk, description='Custom work',
            qty=Decimal('2.00'), units='hours',
            price=Decimal('50.00'), accounting_category=self.lit,
        )
        self.assertEqual(li.estimate, self.est)
        self.assertEqual(li.description, 'Custom work')

    def test_add_line_item_from_pli(self):
        from apps.inventory.models import PriceListItem
        pli = PriceListItem.objects.create(
            code='WLD-001', description='Welding rod', units='ea',
            purchase_price=Decimal('5.00'), selling_price=Decimal('10.00'),
            accounting_category=self.lit,
        )
        li = EstimateService.add_line_item_from_pli(
            self.est.pk, pli.pk, qty=Decimal('20.00'),
        )
        self.assertEqual(li.price_list_item, pli)
        self.assertEqual(li.price, Decimal('10.00'))
        self.assertEqual(li.description, 'Welding rod')

    def test_add_line_item_to_non_draft_raises(self):
        EstimateLineItem.objects.create(estimate=self.est, description='Test item', price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.est.pk, description='X', qty=1, units='ea',
                price=Decimal('1.00'), accounting_category=self.lit,
            )


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


# --- WorksheetService ---

class WorksheetServiceCreateTest(EstimatesTestBase):
    """Tests for WorksheetService.create_worksheet."""

    def test_create_worksheet(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        self.assertIsNotNone(ws.pk)
        self.assertEqual(ws.job, self.job)
        self.assertEqual(ws.status, EstWorksheet.STATUS_DRAFT)

    def test_create_worksheet_from_template(self):
        from apps.estimates.services import WorksheetService, WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='Tmpl')
        ws = WorksheetService.create_worksheet(self.job.pk, template=tmpl)
        self.assertEqual(ws.template, tmpl)

    def test_create_worksheet_job_not_found(self):
        from apps.estimates.services import WorksheetService
        with self.assertRaises(NotFoundError):
            WorksheetService.create_worksheet(99999)


class WorksheetServiceReviseTest(EstimatesTestBase):
    """Tests for WorksheetService.revise_worksheet."""

    def test_revise_worksheet(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        # Add a task to make it non-empty
        PlanTask.objects.create(
            est_worksheet=ws, name='Task 1', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        new_ws = WorksheetService.revise_worksheet(ws.pk)
        self.assertEqual(new_ws.version, 2)
        self.assertEqual(new_ws.status, EstWorksheet.STATUS_DRAFT)
        ws.refresh_from_db()
        self.assertEqual(ws.status, EstWorksheet.STATUS_SUPERSEDED)

    def test_revise_copies_tasks(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        PlanTask.objects.create(
            est_worksheet=ws, name='Task A', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='Task B', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        new_ws = WorksheetService.revise_worksheet(ws.pk)
        new_tasks = PlanTask.objects.filter(est_worksheet=new_ws)
        self.assertEqual(new_tasks.count(), 2)


class WorksheetServiceDeleteTest(EstimatesTestBase):
    """Tests for WorksheetService.delete_worksheet."""

    def test_deletes_worksheet_with_no_estimate(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        ws_pk = ws.pk
        WorksheetService.delete_worksheet(ws)
        self.assertFalse(EstWorksheet.objects.filter(pk=ws_pk).exists())

    def test_refuses_when_estimate_linked(self):
        from apps.estimates.services import WorksheetService, EstimateWizardService
        from django.core.exceptions import ValidationError
        ws = WorksheetService.create_worksheet(self.job.pk)
        EstimateWizardService.open_for_worksheet(ws)
        ws.refresh_from_db()
        self.assertIsNotNone(ws.estimate_id)
        with self.assertRaises(ValidationError):
            WorksheetService.delete_worksheet(ws)
        # Worksheet survives
        self.assertTrue(EstWorksheet.objects.filter(pk=ws.pk).exists())


class WorksheetServiceAddTaskTest(EstimatesTestBase):
    """Tests for WorksheetService task-adding methods."""

    def setUp(self):
        super().setUp()
        from apps.estimates.services import WorksheetService
        self.ws = WorksheetService.create_worksheet(self.job.pk)

    def test_add_task_from_template(self):
        from apps.estimates.services import WorksheetService, WorkTemplateService
        tt = WorkTemplateService.create_task_template(
            template_name='Welding',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        task = WorksheetService.add_task_from_template(
            self.ws.pk, tt.pk, est_qty=Decimal('4.00'),
        )
        self.assertEqual(task.name, 'Welding')
        self.assertEqual(task.est_qty, Decimal('4.00'))
        self.assertEqual(task.est_worksheet, self.ws)

    def test_add_task_manual(self):
        from apps.estimates.services import WorksheetService
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.create(code='X-atm', name='X-atm')
        scheme = RateScheme.objects.create(
            name='S-atm', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        task = WorksheetService.add_task_manual(
            self.ws.pk, name='Custom task', rate_scheme_id=scheme.pk,
            est_qty=Decimal('1.00'),
        )
        self.assertEqual(task.name, 'Custom task')
        self.assertEqual(task.est_worksheet, self.ws)

    def test_add_task_to_non_draft_raises(self):
        from apps.estimates.services import WorksheetService
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
        with self.assertRaises(ValidationError):
            WorksheetService.add_task_manual(
                self.ws.pk, name='X',
            )


# --- WorkTemplateService.delete_association ---

class WorkTemplateServiceDeleteAssociationTest(EstimatesTestBase):
    """Tests for WorkTemplateService.delete_association."""

    def test_delete_unbundled_association(self):
        from apps.estimates.services import WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='T')
        tt = WorkTemplateService.create_task_template(
            template_name='Task',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        assoc = TemplateTaskAssociation.objects.create(
            work_template=tmpl, task_template=tt,
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
        tt = WorkTemplateService.create_task_template(
            template_name='Task',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        assoc = TemplateTaskAssociation.objects.create(
            work_template=tmpl1, task_template=tt,
            sort_order=1,
        )
        with self.assertRaises(NotFoundError):
            WorkTemplateService.delete_association(tmpl2.pk, assoc.pk)


# --- WorksheetService.finalize ---

class WorksheetServiceFinalizeTest(EstimatesTestBase):
    """Tests for WorksheetService.finalize."""

    def test_finalize_draft_worksheet(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        updated = WorksheetService.finalize(ws.pk)
        self.assertEqual(updated.status, EstWorksheet.STATUS_FINAL)

    def test_finalize_non_draft_raises(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        ws.status = EstWorksheet.STATUS_FINAL
        ws.save()
        with self.assertRaises(ValidationError):
            WorksheetService.finalize(ws.pk)

    def test_finalize_not_found(self):
        from apps.estimates.services import WorksheetService
        with self.assertRaises(NotFoundError):
            WorksheetService.finalize(99999)


# --- JobService.copy_from_worksheet ---

class JobServiceCopyFromWorksheetTest(EstimatesTestBase):
    """Tests for JobService.copy_from_worksheet."""

    def test_copy_tasks(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        PlanTask.objects.create(
            est_worksheet=ws, name='Task A', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='Task B', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )

        JobService.copy_from_worksheet(self.job.pk, ws.pk)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 2)

    def test_copy_materials(self):
        from apps.estimates.services import WorksheetService
        ws = WorksheetService.create_worksheet(self.job.pk)
        task = PlanTask.objects.create(
            est_worksheet=ws, name='Task', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            est_worksheet=ws,
            plan_task=task, description='Steel', quantity=Decimal('5.00'),
            accounting_category=self.lit,
        )

        JobService.copy_from_worksheet(self.job.pk, ws.pk)
        job_task = Task.objects.get(job=self.job)
        self.assertEqual(job_task.materials.count(), 1)
        self.assertEqual(job_task.materials.first().description, 'Steel')

    def test_copy_with_template_sets_template(self):
        """Template arg should be linked onto the job."""
        from apps.estimates.services import WorksheetService, WorkTemplateService
        tmpl = WorkTemplateService.create_template(template_name='Tmpl')
        ws = WorksheetService.create_worksheet(self.job.pk, template=tmpl)
        JobService.copy_from_worksheet(self.job.pk, ws.pk, template=tmpl)
        self.job.refresh_from_db()
        self.assertEqual(self.job.template, tmpl)

class EstimateServiceDiscardDraftTest(EstimatesTestBase):
    """Tests for EstimateService.discard_draft."""

    def _make_estimate_with_sources(self):
        from apps.estimates.models import EstimateLineItemSource
        worksheet = EstWorksheet.objects.create(job=self.job)
        plan_task = PlanTask.objects.create(
            est_worksheet=worksheet, name='T1',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        plan_material = PlanMaterial.objects.create(
            est_worksheet=worksheet, description='steel',
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
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=plan_task.pk,
        )
        src2 = EstimateLineItemSource.objects.create(
            estimate_line_item=line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
            source_pk=plan_material.pk,
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
        self.assertTrue(Estimate.objects.filter(pk=estimate.pk).exists())
