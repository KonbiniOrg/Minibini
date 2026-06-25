from decimal import Decimal
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, PlanMaterial, InventoryItem,
)
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job, Task, PlanTask, ServiceItem


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
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
        # Grant permissions used across test classes (individual tests may add more).
        from django.contrib.auth.models import Permission
        self.user.user_permissions.set([
            Permission.objects.get(codename='can_manage_jobs'),
        ])


class MaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_material_description_rejected(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('immutable', str(resp.json()).lower())

    def test_patch_pli_linked_material_units_rejected(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_material_unit_cost_allowed(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))

    def test_patch_pli_linked_material_sell_price_allowed(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'sell_price': '78.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.sell_price, Decimal('78.00'))

    def test_patch_freeform_material_description_allowed(self):
        m = Material.objects.create(
            job=self.job, inventory_item=None,
            description='start', quantity=Decimal('1'),
            accounting_category=self.cat,
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.description, 'NEW')

    def test_patch_freeform_material_units_allowed(self):
        m = Material.objects.create(
            job=self.job, inventory_item=None,
            description='x', quantity=Decimal('1'),
            accounting_category=self.cat,
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.units, 'lbs')


class PlanMaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_plan_material_description_rejected(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_plan_material_unit_cost_allowed(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_patch_freeform_plan_material_quantity_allowed(self):
        """PlanMaterial has no Restock/Draw-more state machine; quantity is
        PATCH-editable on freeform rows. (Material's quantity goes through
        Restock/Draw-more state-machine ops; not the case for PlanMaterial.)"""
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, inventory_item=None,
            description='loose', quantity=Decimal('1'),
            accounting_category=self.cat,
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        pm.refresh_from_db()
        self.assertEqual(pm.quantity, Decimal('5.00'))

    def test_patch_pli_linked_plan_material_quantity_rejected(self):
        """PLI-linked PlanMaterial still has the 'pricing-only' immutability
        rule — quantity is not in the carve-out."""
        ws = EstWorksheet.objects.create(job=self.job)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class PropagateFlagOnFreeformAndPostPathsTests(_Setup):
    """Defensive tests for the propagate_to_pli flag on edge paths."""

    def test_freeform_material_patch_with_propagate_flag_succeeds(self):
        # Freeform Material — no PLI to propagate to. Flag should be a no-op.
        m = Material.objects.create(
            job=self.job, inventory_item=None,
            description='start', quantity=Decimal('1'),
            accounting_category=self.cat,
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_post_taskless_material_with_propagate_flag_succeeds(self):
        # POST a Material with propagate_to_pli — flag is meaningless on create
        # but must not crash the service layer.
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {
                'description': 'x',
                'quantity': '1',
                'unit_cost': '5.00',
                'sell_price': '8.00',
                'propagate_to_pli': True,
            },
            format='json',
        )
        # We just need the request not to crash with TypeError. Either 200/201
        # or a meaningful 400 is acceptable; a 500 is not.
        self.assertNotEqual(resp.status_code, 500, resp.content)

    def test_post_plan_material_on_worksheet_with_propagate_flag_succeeds(self):
        ws = EstWorksheet.objects.create(job=self.job)
        resp = self.client.post(
            f'/api/est-worksheets/{ws.pk}/plan-materials/',
            {
                'description': 'x',
                'quantity': '1',
                'unit_cost': '5.00',
                'sell_price': '8.00',
                'propagate_to_pli': True,
            },
            format='json',
        )
        self.assertNotEqual(resp.status_code, 500, resp.content)

    def test_post_plan_material_on_plan_task_with_propagate_flag_succeeds(self):
        ws = EstWorksheet.objects.create(job=self.job)
        scheme_ac = AccountingCategory.objects.create(code='RS-AC', name='RS AC')
        scheme = ServiceItem.objects.create(
            name='RS', algorithm=ServiceItem.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=scheme_ac,
        )
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='T', sort_order=1, est_qty=Decimal('1'),
            service_item=scheme,
        )
        resp = self.client.post(
            f'/api/plan-tasks/{pt.pk}/materials/',
            {
                'description': 'x',
                'quantity': '1',
                'unit_cost': '5.00',
                'sell_price': '8.00',
                'propagate_to_pli': True,
            },
            format='json',
        )
        self.assertNotEqual(resp.status_code, 500, resp.content)
