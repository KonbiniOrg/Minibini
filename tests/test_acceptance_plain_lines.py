from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.jobs.models import Job, RateScheme, Task


class AcceptancePlainLinesTest(TestCase):
    """Acceptance crystallizes only typed hand-lines (service_item → Task,
    inventory_item / is_material → Material). Plain hand-lines — bare lines with
    no atom type — stay document-only: no atom, no EstimateLineItemSource row.
    Atom-backed lines (with a source) are already on the job; adjustment lines
    are document-only."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        # An atom that already lives on the Job (work created directly).
        self.task = Task(
            job=self.job, name='Setup', est_qty=Decimal('2'),
        )
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        # An inventoried material on the job so earmarking has something to do.
        self.pli = InventoryItem.objects.create(
            code='STEEL', accounting_category=self.cat,
            qty_on_hand=Decimal('50'),
        )
        self.material = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('7'),
            units='ea', accounting_category=self.cat, inventory_item=self.pli,
        )

        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_OPEN,
        )

        # 1) Atom-backed line — points at the Task via a source row.
        self.atom_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Setup labor',
            qty=Decimal('2'), price=Decimal('200.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.atom_line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

        # 2) Plain hand-line — no source, not an adjustment, no atom type.
        #    Stays a document line: crystallizes NOTHING.
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Rush handling',
            qty=Decimal('3'), price=Decimal('25.00'), accounting_category=self.cat,
        )

        # 3) Adjustment line — document-only, crystallizes nothing.
        self.adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category=self.cat,
        )
        self.adj_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
            adjustment_service=self.adj_scheme,
        )

    def test_plain_hand_line_crystallizes_nothing(self):
        result = EstimateAcceptanceService.on_accept(self.estimate)

        # No source row of any kind for the plain line.
        self.assertFalse(self.hand_line.sources.exists())

        # The line itself is untouched — still present on the document.
        self.hand_line.refresh_from_db()
        self.assertEqual(self.hand_line.description, 'Rush handling')
        self.assertEqual(self.hand_line.qty, Decimal('3'))
        self.assertEqual(self.hand_line.price, Decimal('25.00'))

        # The counts dict no longer reports fees.
        self.assertNotIn('fees_created', result)
        self.assertEqual(result['materials_created'], 0)
        self.assertEqual(result['tasks_created'], 0)

    def test_acceptance_is_idempotent_for_plain_lines(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        result = EstimateAcceptanceService.on_accept(self.estimate)

        self.assertFalse(self.hand_line.sources.exists())
        self.assertEqual(result['materials_created'], 0)
        self.assertEqual(result['tasks_created'], 0)

    def test_plain_hand_line_without_ac_is_skipped_not_rejected(self):
        # A null-AC plain line (bad historical data — entry-time send guard
        # normally prevents it) is simply skipped: nothing crystallizes.
        no_cat = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=None,
        )
        result = EstimateAcceptanceService.on_accept(self.estimate)
        self.assertFalse(no_cat.sources.exists())
        self.assertEqual(result['materials_created'], 0)

    def test_catalog_hand_line_becomes_a_material(self):
        # A hand-line with an inventory_item (added via "From Inventory") is a
        # material, so acceptance crystallizes it into a Material atom.
        pli2 = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
            qty_on_hand=Decimal('20'), purchase_price=Decimal('80'),
            selling_price=Decimal('100'),
        )
        cat_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='Plywood sheets',
            qty=Decimal('5'), price=Decimal('114.00'), units='ea',
            accounting_category=self.cat, inventory_item=pli2,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        mat = Material.objects.get(job=self.job, description='Plywood sheets')
        self.assertEqual(mat.quantity, Decimal('5'))
        self.assertEqual(mat.sell_price, Decimal('114.00'))  # estimate's quoted price
        self.assertEqual(mat.inventory_item, pli2)
        self.assertEqual(mat.accounting_category, self.cat)
        self.assertEqual(result['materials_created'], 1)
        # The estimate line is now source-linked to the Material (for copy_from_estimate).
        src = EstimateLineItemSource.objects.get(estimate_line_item=cat_line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)

    def test_atom_backed_and_adjustment_lines_crystallize_nothing(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        # Only the atom_line's pre-existing source row exists; the adjustment
        # line gained nothing.
        self.assertFalse(self.adj_line.sources.exists())

    def test_earmarks_created_on_accept(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        earmark = Earmark.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(earmark.quantity, Decimal('7'))
