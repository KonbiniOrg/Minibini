"""
Tests for automatic earmarking behaviour across job lifecycle.

Key rule: earmarks are only created immediately when a material is added to a
*committed* (approved or later) job.  Pre-approval jobs (draft / submitted) do
NOT earmark on create; their materials get earmarked in bulk when the estimate
is accepted via InventoryService.create_earmarks_for_job().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, RateScheme
from apps.estimates.models import (
    Estimate, EstimateLineItem, WorkTemplate,
    ServiceItem, TemplateTaskAssociation,
)
from apps.inventory.models import Material, InventoryItem, Earmark
from apps.inventory.services import MaterialService, InventoryService
from apps.jobs.services import JobService


def _make_scheme(suffix):
    from apps.core.models import AccountingCategory
    ac = AccountingCategory.objects.create(code=f'AEM-{suffix}', name=f'aem-{suffix}')
    return RateScheme.objects.create(
        name=f'S-aem-{suffix}', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


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

    def _add_material_to_template(self):
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.get_or_create(
            code='TMPL_MAT', defaults={'name': 'Template Material'},
        )[0]
        item = InventoryItem.objects.create(
            code='TMPL-ITEM', description='sheet',
            accounting_category=cat, qty_on_hand=Decimal('10.00'),
        )
        from apps.inventory.models import TemplateMaterialAssociation
        TemplateMaterialAssociation.objects.create(
            work_template=self.template,
            inventory_item=item,
            quantity=Decimal('2.00'),
        )
        return item

    def test_template_on_draft_job_creates_no_earmarks(self):
        """Materials landed by a template on a PRE-APPROVAL job must not
        reserve stock — earmarks are generated at estimate (or CO)
        acceptance, never at plan-population time (RM design,
        confirmed 2026-07-10)."""
        self._add_material_to_template()
        JobService.populate_from_template(self.job, self.template)  # job is draft
        self.assertGreater(
            Material.objects.filter(job=self.job).count(), 0,
            'fixture must actually land a material',
        )
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_template_on_committed_job_earmarks(self):
        """A template applied to an already-approved job reserves stock
        immediately (same rule as ad-hoc material creation)."""
        item = self._add_material_to_template()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        JobService.populate_from_template(self.job, self.template)
        em = Earmark.objects.filter(job=self.job, inventory_item=item)
        self.assertEqual(em.count(), 1)
        self.assertEqual(em.first().quantity, Decimal('2.00'))


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
            accounting_category=self.category,
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


class PreApprovalNoEarmarkTest(TestCase):
    """Gate: MaterialService.create_on_job must NOT earmark on pre-approval jobs.

    Earmarks are created in bulk at acceptance via create_earmarks_for_job.
    Materials added to an already-committed (approved / in_progress) job still
    earmark immediately, as before.
    """

    def setUp(self):
        from apps.core.models import AccountingCategory
        self.contact = Contact.objects.create(
            first_name='Gate', last_name='Test',
            email='gate@example.com', work_number='555-0200',
        )
        self.category = AccountingCategory.objects.create(
            name='GateMat', code='GM01',
        )
        self.item = InventoryItem.objects.create(
            code='GATE.PLY', description='Gate Plywood',
            units='sheets', qty_on_hand=Decimal('30.00'),
            purchase_price=Decimal('50.00'), selling_price=Decimal('100.00'),
            accounting_category=self.category,
        )

    def _draft_job(self, suffix):
        return Job.objects.create(
            job_number=f'J-GATE-{suffix}', contact=self.contact,
        )

    def test_create_on_draft_job_no_earmark(self):
        """Adding a material to a DRAFT job must not create an earmark."""
        job = self._draft_job('D1')
        self.assertEqual(job.status, Job.STATUS_DRAFT)
        MaterialService.create_on_job(
            job=job, inventory_item=self.item,
            quantity=Decimal('3.00'), units='sheets',
            accounting_category=self.category,
        )
        self.assertEqual(
            Earmark.objects.filter(job=job, inventory_item=self.item).count(), 0,
            'No earmark expected for a DRAFT job',
        )

    def test_create_on_submitted_job_no_earmark(self):
        """Adding a material to a SUBMITTED job must not create an earmark."""
        job = self._draft_job('S1')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        MaterialService.create_on_job(
            job=job, inventory_item=self.item,
            quantity=Decimal('2.00'), units='sheets',
            accounting_category=self.category,
        )
        self.assertEqual(
            Earmark.objects.filter(job=job, inventory_item=self.item).count(), 0,
            'No earmark expected for a SUBMITTED job',
        )

    def test_create_on_approved_job_earmarks_immediately(self):
        """Adding a material to an APPROVED job must earmark right away."""
        job = Job.objects.create(
            job_number='J-GATE-A1', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        MaterialService.create_on_job(
            job=job, inventory_item=self.item,
            quantity=Decimal('4.00'), units='sheets',
            accounting_category=self.category,
        )
        earmark = Earmark.objects.get(job=job, inventory_item=self.item)
        self.assertEqual(earmark.quantity, Decimal('4.00'))

    def test_create_on_in_progress_job_earmarks_immediately(self):
        """Adding a material to an IN_PROGRESS job must earmark right away."""
        job = Job.objects.create(
            job_number='J-GATE-IP1', contact=self.contact,
            status=Job.STATUS_IN_PROGRESS,
        )
        MaterialService.create_on_job(
            job=job, inventory_item=self.item,
            quantity=Decimal('1.00'), units='sheets',
            accounting_category=self.category,
        )
        earmark = Earmark.objects.get(job=job, inventory_item=self.item)
        self.assertEqual(earmark.quantity, Decimal('1.00'))

    def test_acceptance_earmarks_pre_approval_materials(self):
        """Full flow: draft job + create_on_job (no earmark) → accept → earmark appears.

        This exercises the integration between the gate (no earmark on draft) and
        EstimateAcceptanceService which calls create_earmarks_for_job at accept time.
        """
        job = self._draft_job('ACC1')
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-GATE-001', version=1,
        )
        # Create material via the service on the DRAFT job — should NOT earmark yet.
        MaterialService.create_on_job(
            job=job, inventory_item=self.item,
            quantity=Decimal('6.00'), units='sheets',
            accounting_category=self.category,
        )
        self.assertEqual(
            Earmark.objects.filter(job=job).count(), 0,
            'No earmark before acceptance',
        )
        # Accept the estimate — this triggers signals that approve the job then
        # call EstimateAcceptanceService.on_accept → create_earmarks_for_job.
        EstimateLineItem.objects.create(
            estimate=estimate, description='Hand line',
            price=Decimal('200.00'), accounting_category=self.category,
        )
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        earmark = Earmark.objects.get(job=job, inventory_item=self.item)
        self.assertEqual(
            earmark.quantity, Decimal('6.00'),
            'Earmark must appear after estimate acceptance',
        )
