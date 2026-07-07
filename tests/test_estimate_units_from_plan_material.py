from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import InventoryItem, Material
from apps.estimates.services import EstimateWizardService
from apps.jobs.models import Job


# job-owns-atoms refactor (Task 3.1): the estimate now projects the Job's own
# Materials. These tests assert _atom_units reads the Material's units field.
class AtomUnitsFromMaterialTests(TestCase):
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

    def test_atom_units_returns_material_field_freeform(self):
        mat = Material.objects.create(
            job=self.job, task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            accounting_category=self.cat,
        )
        self.assertEqual(EstimateWizardService._atom_units(mat), 'lbs')

    def test_atom_units_returns_material_field_pli_linked(self):
        # Material linked to a PLI with units='sheets' inherits that on save
        # via _populate_from_pli, then _atom_units reads the field.
        mat = Material.objects.create(
            job=self.job, task=None,
            quantity=Decimal('1'), inventory_item=self.pli,
        )
        self.assertEqual(mat.units, 'sheets')
        self.assertEqual(EstimateWizardService._atom_units(mat), 'sheets')
