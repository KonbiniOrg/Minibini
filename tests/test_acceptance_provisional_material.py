from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.jobs.models import Fee, Job


class AcceptanceProvisionalMaterialTest(TestCase):
    """A bare line marked is_material=True crystallizes into an ESTABLISHED
    Material: a QOH-0 lot minted at a reverse-markup provisional cost, with the
    accepted sell price locked and cost_source='estimated'. An unmarked bare
    line is a plain line and crystallizes nothing."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        Configuration.objects.create(key='default_material_markup_percent', value='25')
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_OPEN,
        )

    def _add_line(self, **kw):
        defaults = dict(
            estimate=self.estimate, qty=Decimal('1'), units='ea',
            accounting_category=self.cat,
        )
        defaults.update(kw)
        return EstimateLineItem.objects.create(**defaults)

    def test_marked_line_establishes_with_reverse_markup(self):
        """Spec §provisional cost: sell $400, 25% markup → cost $320, estimated."""
        line = self._add_line(
            line_number=1, description='M77 ABS', qty=Decimal('2'),
            price=Decimal('400.00'), is_material=True,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        mat = Material.objects.get(job=self.job, description='M77 ABS')
        self.assertIsNotNone(mat.inventory_item_id)            # established — minted lot
        self.assertEqual(mat.quantity, Decimal('2'))
        self.assertEqual(mat.sell_price, Decimal('400.00'))    # quoted sell, locked
        self.assertEqual(mat.unit_cost, Decimal('320.00'))     # 400 / 1.25 reverse-markup
        self.assertEqual(mat.cost_source, Material.COST_SOURCE_ESTIMATED)
        self.assertEqual(mat.inventory_item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(mat.accounting_category, self.cat)
        self.assertEqual(result['materials_created'], 1)

        # It did NOT become a Fee.
        self.assertFalse(Fee.objects.filter(job=self.job, description='M77 ABS').exists())

        # Source-linked as a Material.
        src = EstimateLineItemSource.objects.get(estimate_line_item=line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)

    def test_zero_price_marked_line_mints_at_zero_estimated(self):
        """A $0 marked line still establishes: lot at cost 0, sell 0, estimated."""
        self._add_line(
            line_number=1, description='Freebie stock', qty=Decimal('1'),
            price=Decimal('0.00'), is_material=True,
        )

        EstimateAcceptanceService.on_accept(self.estimate)

        mat = Material.objects.get(job=self.job, description='Freebie stock')
        self.assertIsNotNone(mat.inventory_item_id)
        self.assertEqual(mat.unit_cost, Decimal('0.00'))
        self.assertEqual(mat.sell_price, Decimal('0.00'))
        self.assertEqual(mat.cost_source, Material.COST_SOURCE_ESTIMATED)

    def test_unmarked_bare_line_crystallizes_nothing(self):
        line = self._add_line(
            line_number=1, description='Rush handling', qty=Decimal('3'),
            price=Decimal('25.00'), is_material=False,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        self.assertNotIn('fees_created', result)
        self.assertEqual(result['materials_created'], 0)
        self.assertFalse(Fee.objects.filter(job=self.job, description='Rush handling').exists())
        self.assertFalse(Material.objects.filter(job=self.job, description='Rush handling').exists())
        self.assertFalse(line.sources.exists())
