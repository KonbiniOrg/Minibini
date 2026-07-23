from decimal import Decimal
from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.inventory.models import Material, InventoryItem
from apps.jobs.models import Job


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.update_or_create(key='units_list', defaults={'value': '["none","sheets","ea"]'})
        cls.user = User.objects.create_user(username='u', password='p')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        cls.user.user_permissions.add(perm)
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


class MaterialPropagateTests(_Setup):
    def test_propagate_true_updates_pli(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'sell_price': '78.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))
        self.assertEqual(m.sell_price, Decimal('78.00'))
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))
        self.assertEqual(self.pli.selling_price, Decimal('78.00'))

    def test_propagate_false_leaves_pli_alone(self):
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))
        self.assertEqual(self.pli.purchase_price, Decimal('40.00'))  # unchanged

    def test_propagate_only_changed_field(self):
        # User edits only unit_cost; sell_price stays the same as the PLI.
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))
        self.assertEqual(self.pli.selling_price, Decimal('60.00'))  # unchanged

    def test_propagate_works_for_user_without_can_manage_financials(self):
        # Permission carve-out: any authenticated user can propagate.
        self.assertFalse(self.user.has_perm('core.can_manage_financials'))
        m = Material.objects.create(
            job=self.job, inventory_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))


