from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.jobs.models import Fee, Job


class AcceptanceProvisionalMaterialTest(TestCase):
    """A bare line marked is_material=True crystallizes into a provisional
    Material (no inventory_item, sell price only, cost unset) — not a Fee.
    An unmarked bare line still becomes a Fee (unchanged)."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

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

    def test_marked_bare_line_becomes_provisional_material(self):
        line = self._add_line(
            line_number=1, description='M77 ABS', qty=Decimal('2'),
            price=Decimal('400.00'), is_material=True,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        mat = Material.objects.get(job=self.job, description='M77 ABS')
        self.assertIsNone(mat.inventory_item)                 # provisional — no lot
        self.assertEqual(mat.quantity, Decimal('2'))
        self.assertEqual(mat.sell_price, Decimal('400.00'))    # quoted sell, locked
        self.assertEqual(mat.unit_cost, Decimal('0.00'))       # cost unset (out of scope: reverse-markup)
        self.assertEqual(mat.accounting_category, self.cat)
        self.assertEqual(result['materials_created'], 1)

        # It did NOT become a Fee.
        self.assertFalse(Fee.objects.filter(job=self.job, description='M77 ABS').exists())

        # Source-linked as a Material.
        src = EstimateLineItemSource.objects.get(estimate_line_item=line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_MATERIAL)
        self.assertEqual(src.source_pk, mat.pk)

    def test_unmarked_bare_line_still_becomes_a_fee(self):
        self._add_line(
            line_number=1, description='Rush handling', qty=Decimal('3'),
            price=Decimal('25.00'), is_material=False,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        self.assertEqual(result['fees_created'], 1)
        self.assertEqual(result['materials_created'], 0)
        self.assertTrue(Fee.objects.filter(job=self.job, description='Rush handling').exists())
        self.assertFalse(Material.objects.filter(job=self.job, description='Rush handling').exists())
