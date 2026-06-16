# tests/test_material_units_field.py
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APITestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, User
from apps.inventory.models import Material, PlanMaterial, InventoryItem
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class MaterialUnitsFieldTests(TestCase):
    """Phase 1: units field added to MaterialBase."""

    def test_material_has_units_field(self):
        f = Material._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

    def test_plan_material_has_units_field(self):
        f = PlanMaterial._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

class PopulateFromPliCopiesUnitsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = InventoryItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.contact = Contact.objects.create(first_name='Test', last_name='Customer', email='test@example.com')
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact)

    def test_material_pulls_units_from_pli(self):
        m = Material(
            job=self.job, inventory_item=self.pli,
            quantity=Decimal('1'),
        )
        m.save()
        self.assertEqual(m.units, 'sheets')

    def test_material_keeps_explicit_units_when_set(self):
        # Override case: caller supplies a non-default 'units'; PLI does not overwrite.
        m = Material(
            job=self.job, inventory_item=self.pli,
            quantity=Decimal('1'), units='lbs',
        )
        m.save()
        self.assertEqual(m.units, 'lbs')

    def test_freeform_material_keeps_default_units(self):
        m = Material(
            job=self.job, inventory_item=None,
            quantity=Decimal('1'), accounting_category=self.cat,
        )
        m.save()
        self.assertEqual(m.units, 'none')

    def test_plan_material_pulls_units_from_pli(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial(
            est_worksheet=ws, inventory_item=self.pli, quantity=Decimal('1'),
        )
        pm.save()
        self.assertEqual(pm.units, 'sheets')

class MaterialSerializerUnitsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.pli = InventoryItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_material_get_returns_units_from_field(self):
        # Create a Material whose units field has been overridden to differ
        # from its PLI's units. The GET response must reflect the field value,
        # not the PLI's value.
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        Material.objects.filter(pk=m.pk).update(units='lbs')
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['units'], 'lbs')

    def test_freeform_material_get_returns_units_field(self):
        m = Material.objects.create(
            job=self.job, inventory_item=None,
            description='custom', quantity=Decimal('1'), units='ea',
            accounting_category=self.cat,
        )
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.json()['units'], 'ea')


class MaterialStrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.cat = AccountingCategory.objects.create(code='MATSTR', name='MaterialsStr')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j2@d.com')
        cls.job = Job.objects.create(
            name='Js', job_number='J-STR', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_material_str_includes_units_when_not_none(self):
        m = Material.objects.create(
            job=self.job, description='Steel', quantity=Decimal('5'), units='sheets',
            accounting_category=self.cat,
        )
        self.assertEqual(str(m), 'Steel (qty: 5.00 sheets)')

    def test_material_str_omits_units_when_none(self):
        m = Material.objects.create(
            job=self.job, description='Misc', quantity=Decimal('1'),
            accounting_category=self.cat,
        )
        self.assertEqual(str(m), 'Misc (qty: 1.00)')

    def test_plan_material_str_includes_units_when_not_none(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, description='Plan Steel',
            quantity=Decimal('3'), units='ea',
            accounting_category=self.cat,
        )
        self.assertEqual(str(pm), 'Plan Steel (qty: 3.00 ea)')

    def test_plan_material_str_omits_units_when_none(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, description='Plan Misc',
            quantity=Decimal('2'),
            accounting_category=self.cat,
        )
        self.assertEqual(str(pm), 'Plan Misc (qty: 2.00)')
