"""
Tests for automatic earmarking when a Job is populated with tasks.

Earmarks are created at job-population time (not on estimate acceptance).
The trigger is inside JobService's population methods, which call
InventoryService.create_earmarks_for_job().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet, WorkTemplate,
    ServiceItem, TemplateTaskAssociation,
)
from apps.inventory.models import Material, PlanMaterial, InventoryItem, Earmark
from apps.jobs.services import JobService


def _make_scheme(suffix):
    from apps.core.models import AccountingCategory
    ac = AccountingCategory.objects.create(code=f'AEM-{suffix}', name=f'aem-{suffix}')
    return RateScheme.objects.create(
        name=f'S-aem-{suffix}', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class EarmarkOnCopyFromWorksheetTest(TestCase):
    """Earmarks created when WO is created via copy_from_worksheet (workflow 3)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number='J-AEM-001', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        from apps.core.models import AccountingCategory
        self.category = AccountingCategory.objects.create(name='Material', code='MAT')
        self.plywood = InventoryItem.objects.create(
            code='PLY.75', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_catalog=True, accounting_category=self.category,
        )
        self.screws = InventoryItem.objects.create(
            code='SCR.100', description='Screws',
            units='ea', qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'), selling_price=Decimal('12.00'),
            is_catalog=True, accounting_category=self.category,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme = _make_scheme('cfw')
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinets', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )

    def test_earmarks_created_on_copy_from_worksheet(self):
        PlanMaterial.objects.create(
            plan_task=self.plan_task, est_worksheet=self.worksheet,
            inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task, est_worksheet=self.worksheet,
            inventory_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'),
            sell_price=Decimal('12.00'),
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 2)
        self.assertEqual(
            Earmark.objects.get(inventory_item=self.plywood, job=self.job).quantity,
            Decimal('5.00'),
        )
        self.assertEqual(
            Earmark.objects.get(inventory_item=self.screws, job=self.job).quantity,
            Decimal('2.00'),
        )

    def test_aggregates_across_tasks(self):
        plan_task_b = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install trim', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task, est_worksheet=self.worksheet,
            inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            plan_task=plan_task_b, est_worksheet=self.worksheet,
            inventory_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        earmark = Earmark.objects.get(inventory_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_no_earmarks_without_inventoried_materials(self):
        PlanMaterial.objects.create(
            plan_task=self.plan_task, est_worksheet=self.worksheet,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
            accounting_category=self.category,
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_earmarks_when_no_materials(self):
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class EarmarkOnCreateFromTemplateTest(TestCase):
    """Earmarks created (if any materials exist) after create_from_template."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-002', contact=self.contact,
        )
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(name='Labor')
        scheme = _make_scheme('eoct')
        self.template = WorkTemplate.objects.create(
            template_name='Quick',
        )
        tt = ServiceItem.objects.create(
            template_name='Countertop', is_active=True,
            rate_scheme=scheme,
        )
        TemplateTaskAssociation.objects.create(
            work_template=self.template,
            service_item=tt, est_qty=1, sort_order=1,
        )

    def test_no_earmarks_from_template_with_no_materials(self):
        """Template -> WO has no materials, so no earmarks."""
        JobService.populate_from_template(self.job, self.template)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class EstimateAcceptanceCreatesEarmarksTest(TestCase):
    """Accepting an estimate earmarks the job's inventoried materials.

    In the job-owns-atoms model, materials live directly on the Job (created up
    front, not carried over from a worksheet at accept time). Acceptance's
    crystallization hook (EstimateAcceptanceService.on_accept) calls
    create_earmarks_for_job, so accepting an estimate still earmarks the job's
    inventoried materials."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-004', contact=self.contact,
        )
        from apps.core.models import AccountingCategory
        self.category = AccountingCategory.objects.create(name='Material', code='MAT2')
        self.plywood = InventoryItem.objects.create(
            code='PLY.99', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_catalog=True, accounting_category=self.category,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-AEM-005', version=1,
        )
        # Material lives directly on the Job in the job-owns-atoms model.
        Material.objects.create(
            job=self.job, description='Plywood', inventory_item=self.plywood,
            quantity=Decimal('5.00'), units='sheets',
            accounting_category=self.category,
        )

    def test_accepting_estimate_creates_earmarks(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'), accounting_category=self.category,
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        earmark = Earmark.objects.get(job=self.job, inventory_item=self.plywood)
        self.assertEqual(earmark.quantity, Decimal('5.00'))
