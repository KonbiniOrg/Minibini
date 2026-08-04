from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.jobs.models import Fee, Job, RateScheme, Task


class AcceptanceCrystallizesFeesTest(TestCase):
    """Acceptance turns hand-lines (no source row, not adjustments) into Fees on
    the job, then earmarks the job. Atom-backed lines (with a source) are already
    on the job and must NOT become Fees; adjustment lines are document-only."""

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

        # 2) Hand-line — no source, not an adjustment. Should become a Fee.
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Rush handling',
            qty=Decimal('3'), price=Decimal('25.00'), accounting_category=self.cat,
        )

        # 3) Adjustment line — document-only, must NOT become a Fee.
        self.adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category=self.cat,
        )
        self.adj_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
            adjustment_service=self.adj_scheme,
        )

    def test_only_hand_line_becomes_a_fee(self):
        result = EstimateAcceptanceService.on_accept(self.estimate)

        fees = Fee.objects.filter(job=self.job)
        self.assertEqual(fees.count(), 1)
        self.assertEqual(result['fees_created'], 1)

        fee = fees.first()
        self.assertEqual(fee.description, 'Rush handling')
        self.assertEqual(fee.quantity, Decimal('3'))
        self.assertEqual(fee.unit_rate, Decimal('25.00'))
        self.assertEqual(fee.accounting_category, self.cat)
        self.assertEqual(fee.sort_order, 2)

    def test_catalog_hand_line_becomes_a_material_not_a_fee(self):
        # A hand-line with an inventory_item (added via "From Inventory") is a
        # material, so acceptance crystallizes it into a Material atom — not a Fee.
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
        # It did NOT become a Fee.
        self.assertFalse(
            Fee.objects.filter(job=self.job, description='Plywood sheets').exists()
        )
        # The estimate line is now source-linked to the Material (for copy_from_estimate).
        src = EstimateLineItemSource.objects.get(estimate_line_item=cat_line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)

    def test_atom_backed_and_adjustment_lines_do_not_become_fees(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        descriptions = set(Fee.objects.filter(job=self.job).values_list('description', flat=True))
        self.assertNotIn('Setup labor', descriptions)
        self.assertNotIn('Rush surcharge', descriptions)

    def test_earmarks_created_on_accept(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        earmark = Earmark.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(earmark.quantity, Decimal('7'))

    def test_zero_qty_legacy_hand_line_raises_not_crystallized(self):
        """Final review of task-owned-money Phase 3, Finding 2: a hand-line
        with no explicit freeform_kind (legacy default, None — see the
        freeform_kind field's own docstring) skips EstimateService._validate_qty
        at entry the same way it skips the zero-price check, since
        `is_fee`/the fee-kind check requires freeform_kind == KIND_FEE. This
        line is built directly via the ORM (bypassing the service layer
        entirely, as this whole file's fixtures do) with qty=0 to exercise
        that gap. Acceptance's direct Fee.objects.create() call must refuse
        to mint a zero-quantity Fee rather than silently coercing it to 1."""
        self.hand_line.qty = Decimal('0.00')
        self.hand_line.save()

        with self.assertRaises(ValidationError):
            EstimateAcceptanceService.on_accept(self.estimate)

        self.assertFalse(
            Fee.objects.filter(job=self.job, description='Rush handling').exists()
        )
