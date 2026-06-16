from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import InventoryItem, PlanMaterial
from apps.estimates.models import EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.jobs.models import Job


class AtomUnitsFromPlanMaterialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        cls.pli = InventoryItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_atom_units_returns_plan_material_field_freeform(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            accounting_category=self.cat,
        )
        self.assertEqual(EstimateWizardService._atom_units(pm), 'lbs')

    def test_atom_units_returns_plan_material_field_pli_linked(self):
        # PlanMaterial linked to a PLI with units='sheets' inherits that on save
        # via _populate_from_pli, then _atom_units reads the field.
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            quantity=Decimal('1'), inventory_item=self.pli,
        )
        self.assertEqual(pm.units, 'sheets')
        self.assertEqual(EstimateWizardService._atom_units(pm), 'sheets')

    def test_send_all_atoms_to_estimate_carries_pm_units(self):
        # End-to-end: a freeform PlanMaterial on a worksheet → bulk-converted
        # to an EstimateLineItem; the line item's units mirrors the PM's.
        ws = EstWorksheet.objects.create(job=self.job)
        PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            accounting_category=self.cat,
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(ws)
        self.assertEqual(result['created_count'], 1)
        li = EstimateLineItem.objects.get(estimate=result['estimate'])
        self.assertEqual(li.units, 'lbs')


class SendAllAtomsCarriesQtyAndPriceTests(TestCase):
    """Regression: send_all_atoms_to_estimate must carry the PlanMaterial's
    own qty and sell_price (not collapse to qty=1, price=total)."""

    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs"]')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        from apps.contacts.models import Contact
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j3@d.com')
        cls.pli = InventoryItem.objects.create(
            code='PLI-Q', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-Q', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_freeform_plan_material_carries_qty_and_sell_price(self):
        ws = EstWorksheet.objects.create(job=self.job)
        PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            accounting_category=self.cat,
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(ws)
        li = EstimateLineItem.objects.get(estimate=result['estimate'])
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.units, 'lbs')
        self.assertEqual(li.price, Decimal('2.00'))

    def test_pli_linked_plan_material_carries_qty_and_sell_price(self):
        ws = EstWorksheet.objects.create(job=self.job)
        PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            quantity=Decimal('3'), inventory_item=self.pli,
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(ws)
        li = EstimateLineItem.objects.get(estimate=result['estimate'])
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.units, 'sheets')
        self.assertEqual(li.price, Decimal('60.00'))
