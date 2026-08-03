"""
Tests for compute_adjustment_amount helper in apps.core.adjustments,
and for auto-recompute of percentage-adjustment lines on every line-item mutation.

compute_adjustment_amount covers:
  (a) Empty target-category set -> sum ALL non-adjustment siblings (15% of 140 = 21.00)
  (b) Target-category set filters to one category (15% of 100 = 15.00)
  (c) Negative percent (discount) -> negative dollar amount (-10% of 140 = -14.00)
  (d) Other adjustment siblings must NOT be included in the subtotal base

Auto-recompute covers:
  - recompute_adjustments helper
  - EstimateService: add_line_item, update_line_item, delete_line_item, add_adjustment_line
  - InvoiceService: add_line_item, update_line_item, delete_line_item, add_adjustment_line
  - EstimateWizardService: add_atoms_to_new_line_item triggers recompute
"""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.core.adjustments import recompute_adjustments
from apps.jobs.models import RateScheme


class AdjustmentFieldsTest(TestCase):
    def test_estimate_line_can_hold_adjustment_service(self):
        from apps.estimates.models import EstimateLineItem
        # field presence is the assertion; construction covered in later tasks
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_target_categories'))

    def test_invoice_line_can_hold_adjustment_service(self):
        from apps.invoicing.models import InvoiceLineItem
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_target_categories'))


class ComputeAdjustmentAmountTest(TestCase):

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate, EstimateLineItem

        self.labor = AccountingCategory.objects.create(code='LAB-adj', name='Labor-adj', taxable=False)
        self.materials = AccountingCategory.objects.create(code='MAT-adj', name='Materials-adj', taxable=False)

        contact = Contact.objects.create(
            first_name='Test', last_name='Adj', email='adj@test.com',
        )
        job = Job.objects.create(
            name='Adj Test Job', job_number='ADJ-001', status='approved',
            contact=contact,
        )
        # Create a draft estimate directly (skip status transition guards)
        self.est = Estimate.objects.create(
            job=job,
            estimate_number='EST-ADJ-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )

        # Two base (non-adjustment) line items:
        #   line 1: qty=2, price=50 -> total 100 (labor)
        #   line 2: qty=1, price=40 -> total 40  (materials)
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1,
            qty=Decimal('2'), price=Decimal('50.00'),
            accounting_category=self.labor,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2,
            qty=Decimal('1'), price=Decimal('40.00'),
            accounting_category=self.materials,
        )

        # A 15% percentage RateScheme (rush surcharge)
        self.rush_svc = RateScheme.objects.create(
            name='Rush-adj', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.labor,
        )

        # A -10% percentage RateScheme (discount)
        self.discount_svc = RateScheme.objects.create(
            name='Discount-adj', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('-10.00'), unit_label='%',
            accounting_category=self.labor,
        )

    def _make_adj_line(self, svc, line_number):
        """Create an adjustment EstimateLineItem, snapshotting svc.rate onto
        adjustment_percent the way the real creation paths do."""
        from apps.estimates.models import EstimateLineItem
        return EstimateLineItem.objects.create(
            estimate=self.est, line_number=line_number,
            qty=Decimal('1'), price=Decimal('0.00'),
            accounting_category=self.labor,
            adjustment_service=svc,
            adjustment_percent=svc.rate,
        )

    def test_compute_adjustment_all_lines(self):
        """Empty target set -> 15% of all non-adjustment siblings (100+40=140) = 21.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.rush_svc, 3)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('21.00'))

    def test_compute_adjustment_category_filtered(self):
        """Target set = [labor] -> 15% of labor-only siblings (100) = 15.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.rush_svc, 3)
        adj.adjustment_target_categories.set([self.labor.pk])
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('15.00'))

    def test_compute_adjustment_negative_percent_discount(self):
        """-10% of all non-adjustment siblings (140) = -14.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.discount_svc, 3)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('-14.00'))

    def test_compute_adjustment_null_ac_sibling_excluded_by_target_set(self):
        """A sibling with NO accounting category is outside any non-empty
        target set (None is never in target_ids) — 15% of labor-only (100)."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        EstimateLineItem.objects.create(
            estimate=self.est, line_number=5, description='no AC',
            qty=Decimal('1'), price=Decimal('60.00'),
        )
        adj = self._make_adj_line(self.rush_svc, 3)
        adj.adjustment_target_categories.set([self.labor.pk])
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('15.00'))

    def test_compute_adjustment_skips_other_adjustments(self):
        """Another adjustment sibling must NOT be included in the subtotal base."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        # Add a first adjustment line (line 3) — also a sibling
        self._make_adj_line(self.rush_svc, 3)
        # The adjustment under test is line 4; all lines (1, 2, 3) are siblings
        adj = self._make_adj_line(self.rush_svc, 4)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        # line 3 is an adjustment so it must be excluded from the base; result = 15% of 140 = 21.00
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('21.00'))


# ---------------------------------------------------------------------------
# recompute_adjustments helper
# ---------------------------------------------------------------------------

class RecomputeAdjustmentsHelperTest(TestCase):
    """Direct tests of recompute_adjustments helper."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.estimates.models import Estimate, EstimateLineItem
        from apps.jobs.services import JobService

        self.cat = AccountingCategory.objects.create(
            code='LAB-RH', name='Labor-RH', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='RH', last_name='Test', email='rh@t.com', work_number='555-1111',
        )
        self.job = JobService.create_job(name='RH Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-RH-001', status=Estimate.STATUS_DRAFT,
        )
        self.base = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        self.pct_svc = RateScheme.objects.create(
            name='RushRH', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='%', description='Rush 10%', price=Decimal('0.00'),
            adjustment_service=self.pct_svc,
            adjustment_percent=self.pct_svc.rate,
        )

    def test_recompute_updates_stale_adjustment(self):
        """recompute_adjustments sets adj price to 10% of base (0 -> 10)."""
        updated = recompute_adjustments(
            __import__('apps.estimates.models', fromlist=['EstimateLineItem'])
            .EstimateLineItem.objects.filter(estimate=self.est)
        )
        self.assertEqual(updated, 1)
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('10.00'))

    def test_recompute_skips_already_correct_adjustment(self):
        """Returns 0 when adjustment is already at the correct price."""
        self.adj.price = Decimal('10.00')
        self.adj.save()
        updated = recompute_adjustments(
            __import__('apps.estimates.models', fromlist=['EstimateLineItem'])
            .EstimateLineItem.objects.filter(estimate=self.est)
        )
        self.assertEqual(updated, 0)


# ---------------------------------------------------------------------------
# EstimateService auto-recompute
# ---------------------------------------------------------------------------

class EstimateAutoRecomputeTest(TestCase):
    """Estimate service auto-recomputes adjustments on every line-item mutation."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.estimates.models import Estimate, EstimateLineItem
        from apps.estimates.services import EstimateService
        from apps.jobs.services import JobService

        self.cat = AccountingCategory.objects.create(
            code='LAB-EA', name='Labor-EA', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='EA', last_name='Test', email='ea@t.com', work_number='555-2222',
        )
        self.job = JobService.create_job(name='EA Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-EA-001', status=Estimate.STATUS_DRAFT,
        )
        self.base = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('200.00'),
            accounting_category=self.cat,
        )
        self.pct_svc = RateScheme.objects.create(
            name='Rush-EA', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        from apps.estimates.services import EstimateService
        self.adj = EstimateService.add_adjustment_line(
            self.est, adjustment_service_id=self.pct_svc.pk,
        )
        # 10% of 200 = 20
        self.assertEqual(self.adj.price, Decimal('20.00'))

    def test_add_line_item_updates_adjustment(self):
        """Adding a base line triggers recompute: adj = 10% of (200 + 50) = 25.
        (Phase 6 removed manual add_line_item; lines are saved via LineItemService —
        the same path the wizard/projection uses, which recomputes adjustments.)"""
        from apps.core.services import LineItemService
        from apps.estimates.models import EstimateLineItem
        li = EstimateLineItem(
            estimate=self.est, description='Extra', qty=Decimal('1'),
            units='ea', price=Decimal('50.00'), accounting_category=self.cat,
        )
        LineItemService.save_line_item(li)
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('25.00'))

    def test_update_line_item_updates_adjustment(self):
        """Updating a base line's price triggers recompute: adj = 10% of 300 = 30."""
        from apps.estimates.services import EstimateService
        EstimateService.update_line_item(self.base.pk, price=Decimal('300.00'))
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('30.00'))

    def test_delete_line_item_updates_adjustment(self):
        """Deleting the only base line triggers recompute: adj = 10% of 0 = 0."""
        from apps.estimates.services import EstimateService
        EstimateService.delete_line_item(self.base.pk)
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('0.00'))

    def test_add_adjustment_line_snapshots_percent(self):
        """add_adjustment_line stamps adjustment_percent from the scheme's
        rate at creation time — the line's own field, not a live pointer."""
        self.assertEqual(self.adj.adjustment_percent, Decimal('10.00'))

    def test_editing_percentage_preset_does_not_move_existing_adjustments(self):
        """Changing the preset's rate after the adjustment line exists must
        NOT move the line's amount on recompute — it reads its own snapshot
        (adjustment_percent), never the live RateScheme.rate."""
        from apps.core.adjustments import recompute_adjustments
        from apps.estimates.models import EstimateLineItem

        before = self.adj.price
        self.pct_svc.rate = Decimal('99.00')
        self.pct_svc.save()
        recompute_adjustments(EstimateLineItem.objects.filter(estimate=self.est))
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, before)
        self.assertEqual(self.adj.adjustment_percent, Decimal('10.00'))


# ---------------------------------------------------------------------------
# InvoiceService auto-recompute
# ---------------------------------------------------------------------------

class InvoiceAutoRecomputeTest(TestCase):
    """Invoice service auto-recomputes adjustments on every line-item mutation."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.invoicing.models import Invoice, InvoiceLineItem
        from apps.invoicing.services import InvoiceService
        from apps.jobs.models import Job
        from apps.jobs.services import JobService

        self.cat = AccountingCategory.objects.create(
            code='LAB-IA', name='Labor-IA', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='IA', last_name='Test', email='ia@t.com', work_number='555-3333',
        )
        self.job = JobService.create_job(name='IA Job', contact=self.contact)
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()

        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )
        self.base = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('200.00'),
            accounting_category=self.cat,
        )
        self.pct_svc = RateScheme.objects.create(
            name='LateFee-IA', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('5.00'), unit_label='%',
            accounting_category=self.cat,
        )
        from apps.invoicing.services import InvoiceService
        self.adj = InvoiceService.add_adjustment_line(
            self.invoice, adjustment_service_id=self.pct_svc.pk,
        )
        # 5% of 200 = 10
        self.assertEqual(self.adj.price, Decimal('10.00'))

    def test_add_line_item_updates_adjustment(self):
        """Adding a base line triggers recompute: adj = 5% of (200 + 100) = 15."""
        from apps.invoicing.services import InvoiceService
        InvoiceService.add_line_item(
            self.invoice.pk, description='Extra', qty=Decimal('1'),
            units='ea', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('15.00'))

    def test_update_line_item_updates_adjustment(self):
        """Updating a base line's price triggers recompute: adj = 5% of 400 = 20."""
        from apps.invoicing.services import InvoiceService
        InvoiceService.update_line_item(self.base.pk, price=Decimal('400.00'))
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('20.00'))

    def test_delete_line_item_updates_adjustment(self):
        """Deleting the only base line triggers recompute: adj = 5% of 0 = 0."""
        from apps.invoicing.services import InvoiceService
        InvoiceService.delete_line_item(self.base.pk)
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('0.00'))

    def test_add_adjustment_line_snapshots_percent(self):
        """InvoiceService.add_adjustment_line stamps adjustment_percent from
        the scheme's rate at creation time — the line's own field."""
        self.assertEqual(self.adj.adjustment_percent, Decimal('5.00'))

    def test_editing_percentage_preset_does_not_move_existing_invoice_adjustment(self):
        """Changing the preset's rate after the invoice adjustment line exists
        must NOT move the line's amount on recompute."""
        from apps.core.adjustments import recompute_adjustments
        from apps.invoicing.models import InvoiceLineItem

        before = self.adj.price
        self.pct_svc.rate = Decimal('50.00')
        self.pct_svc.save()
        recompute_adjustments(InvoiceLineItem.objects.filter(invoice=self.invoice))
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, before)
        self.assertEqual(self.adj.adjustment_percent, Decimal('5.00'))


# ---------------------------------------------------------------------------
# EstimateWizardService auto-recompute
# ---------------------------------------------------------------------------

class EstimateWizardAutoRecomputeTest(TestCase):
    """EstimateWizardService.add_atoms_to_new_line_item recomputes adjustments."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.estimates.models import Estimate
        from apps.estimates.services import EstimateService
        from apps.jobs.models import Task
        from apps.jobs.services import JobService

        self.cat = AccountingCategory.objects.create(
            code='LAB-WZ', name='Labor-WZ', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='WZ', last_name='Test', email='wz@t.com', work_number='555-4444',
        )
        self.job = JobService.create_job(name='WZ Job', contact=self.contact)

        flat_svc = RateScheme.objects.create(
            name='FlatWZ', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100.00'), unit_label='hr',
            accounting_category=self.cat,
        )
        # job-owns-atoms refactor (Task 3.1): estimate projects the Job's Tasks.
        # task-owned-money Phase 1 (Task 1/3): Task no longer takes rate_scheme
        # directly — stamp_from_scheme() copies the preset's money fields on.
        self.pt = Task(name='Wiring', job=self.job, est_qty=Decimal('1'))
        self.pt.stamp_from_scheme(flat_svc)
        self.pt.save()

        self.est = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

        pct_svc = RateScheme.objects.create(
            name='WizRush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        self.adj = EstimateService.add_adjustment_line(
            self.est, adjustment_service_id=pct_svc.pk,
        )
        # No base lines yet -> adj = 0
        self.assertEqual(self.adj.price, Decimal('0.00'))

    def test_add_atoms_to_new_line_item_recomputes_adjustment(self):
        """Adding an atom via the wizard recomputes existing adjustment lines."""
        from apps.estimates.services import EstimateWizardService
        line_item = EstimateWizardService.add_atoms_to_new_line_item(
            self.est, [{'type': 'task', 'id': self.pt.pk}],
        )
        self.assertIsNotNone(line_item.pk)
        self.adj.refresh_from_db()
        # 10% of $100 (flat fee)
        self.assertEqual(self.adj.price, Decimal('10.00'))


# ---------------------------------------------------------------------------
# LineItemService.save_line_item chokepoint
# ---------------------------------------------------------------------------

class SaveLineItemChokePointTest(TestCase):
    """LineItemService.save_line_item is the single write path: it saves the
    line item and then recomputes percentage-adjustment siblings."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.estimates.models import Estimate, EstimateLineItem
        from apps.core.services import LineItemService

        self.cat = AccountingCategory.objects.create(
            code='LAB-CK', name='Labor-CK', taxable=False,
        )
        contact = Contact.objects.create(
            first_name='CK', last_name='Test', email='ck@t.com', work_number='555-9999',
        )
        from apps.jobs.services import JobService
        job = JobService.create_job(name='CK Job', contact=contact)
        self.est = Estimate.objects.create(
            job=job, estimate_number='EST-CK-001', status=Estimate.STATUS_DRAFT,
        )
        # A base line at $100
        self.base = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        # A 10% adjustment line (price=0 initially)
        pct_svc = RateScheme.objects.create(
            name='Rush-CK', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='%', description='Rush-CK', price=Decimal('0.00'),
            accounting_category=self.cat, adjustment_service=pct_svc,
            adjustment_percent=pct_svc.rate,
        )

    def test_save_line_item_recomputes_adjustments(self):
        """Writing a line item via LineItemService.save_line_item recomputes adjustments."""
        from apps.estimates.models import EstimateLineItem
        from apps.core.services import LineItemService

        new_line = EstimateLineItem(
            estimate=self.est, line_number=3, qty=Decimal('1'),
            units='ea', description='Extra', price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        LineItemService.save_line_item(new_line)
        self.assertIsNotNone(new_line.pk)

        # Adjustment should now be 10% of (100 + 50) = 15
        self.adj.refresh_from_db()
        self.assertEqual(self.adj.price, Decimal('15.00'))


# ---------------------------------------------------------------------------
# adjustment_percent backfill migrations (0044/estimates, 0022/invoicing)
# ---------------------------------------------------------------------------

class AdjustmentPercentBackfillMigrationTest(TestCase):
    """Direct tests of the migrations' forwards() backfill functions against
    rows that predate adjustment_percent (adjustment_service set, percent
    left null — simulates pre-migration data)."""

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.estimates.models import Estimate, EstimateLineItem
        from apps.invoicing.models import Invoice, InvoiceLineItem
        from apps.jobs.services import JobService

        self.cat = AccountingCategory.objects.create(
            code='LAB-BF', name='Labor-BF', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='BF', last_name='Test', email='bf@t.com', work_number='555-5555',
        )
        self.job = JobService.create_job(name='BF Job', contact=self.contact)

        self.svc = RateScheme.objects.create(
            name='Rush-BF', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('12.50'), unit_label='%',
            accounting_category=self.cat,
        )

        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-BF-001', status=Estimate.STATUS_DRAFT,
        )
        # Pre-migration-shaped row: adjustment_service set, adjustment_percent
        # left at its default (null) — exactly what existing rows look like
        # before the backfill runs.
        self.est_adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='%', description='Rush-BF', price=Decimal('0.00'),
            adjustment_service=self.svc,
        )

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.inv_adj = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='%', description='Rush-BF', price=Decimal('0.00'),
            adjustment_service=self.svc,
        )

    def test_estimate_migration_backfills_adjustment_percent(self):
        import importlib
        from django.apps import apps as real_apps

        self.assertIsNone(self.est_adj.adjustment_percent)
        mod = importlib.import_module(
            'apps.estimates.migrations.0044_estimatelineitem_adjustment_percent'
        )
        mod.forwards(real_apps, None)
        self.est_adj.refresh_from_db()
        self.assertEqual(self.est_adj.adjustment_percent, Decimal('12.50'))

    def test_invoice_migration_backfills_adjustment_percent(self):
        import importlib
        from django.apps import apps as real_apps

        self.assertIsNone(self.inv_adj.adjustment_percent)
        mod = importlib.import_module(
            'apps.invoicing.migrations.0022_invoicelineitem_adjustment_percent'
        )
        mod.forwards(real_apps, None)
        self.inv_adj.refresh_from_db()
        self.assertEqual(self.inv_adj.adjustment_percent, Decimal('12.50'))
