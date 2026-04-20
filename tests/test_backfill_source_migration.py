from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme


class BackFillSourceMigrationTest(TestCase):
    """Exercise the back-fill function directly by importing it from the migration module."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

    def _run_backfill(self):
        """Import and run the back-fill function from the migration."""
        from django.apps import apps as django_apps
        # Find the migration module dynamically
        import importlib, pkgutil
        import apps.estimates.migrations as mig_pkg
        backfill_fn = None
        for _, modname, _ in pkgutil.iter_modules(mig_pkg.__path__):
            if 'backfill_estimate_line_item_source' in modname:
                mod = importlib.import_module(f'apps.estimates.migrations.{modname}')
                backfill_fn = mod.back_fill_sources
                break
        assert backfill_fn is not None, 'Could not locate back_fill_sources in migrations'
        backfill_fn(django_apps, None)

    def test_backfill_creates_source_for_task_fk(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='hours',
            price=Decimal('100'), description='Setup', accounting_category=self.cat,
            task=self.pt,
        )
        # Ensure no source rows exist initially
        EstimateLineItemSource.objects.filter(estimate_line_item=li).delete()
        self._run_backfill()
        sources = EstimateLineItemSource.objects.filter(estimate_line_item=li)
        self.assertEqual(sources.count(), 1)
        src = sources.first()
        self.assertEqual(src.source_type, 'plan_charge')
        self.assertEqual(src.source_pk, self.pc.pk)

    def test_backfill_creates_source_for_material_fk(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('2'), units='each',
            price=Decimal('5'), description='steel', accounting_category=self.cat,
            material=self.pm,
        )
        EstimateLineItemSource.objects.filter(estimate_line_item=li).delete()
        self._run_backfill()
        sources = EstimateLineItemSource.objects.filter(estimate_line_item=li)
        self.assertEqual(sources.count(), 1)
        src = sources.first()
        self.assertEqual(src.source_type, 'plan_material')
        self.assertEqual(src.source_pk, self.pm.pk)

    def test_backfill_is_idempotent(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='hours',
            price=Decimal('100'), description='Setup', accounting_category=self.cat,
            task=self.pt,
        )
        EstimateLineItemSource.objects.filter(estimate_line_item=li).delete()
        self._run_backfill()
        self._run_backfill()  # run twice
        self.assertEqual(EstimateLineItemSource.objects.filter(estimate_line_item=li).count(), 1)

    def test_backfill_skips_line_items_with_no_fks(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('50'), description='manual', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.filter(estimate_line_item=li).delete()
        self._run_backfill()
        self.assertEqual(EstimateLineItemSource.objects.filter(estimate_line_item=li).count(), 0)
