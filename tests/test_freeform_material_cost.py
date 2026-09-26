"""Establishment via pricing (spec §establishment).

The old refusal — "a freeform material's cost comes from a document, never
manual entry" — is retired. Pricing a lot-less material now ESTABLISHES it:
a user-entered cost with no item pick mints a lot (born established); a
document-sourced cost (PO/expense) records the cost but stays provisional and
establishes through its own flow.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService

User = get_user_model()


class FreeformMaterialCostServiceTest(TestCase):
    """A user-entered cost with no item pick mints a lot (born established)."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='c@t.com')
        self.job = Job.objects.create(job_number='JOB-FF-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='PLI-1', description='cataloged', accounting_category=self.cat,
            purchase_price=Decimal('3.00'),
        )

    def test_create_freeform_with_cost_is_born_established(self):
        # Formerly rejected; now mints a lot and establishes.
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat,
            inventory_item=None,
        )
        self.assertIsNotNone(mat.inventory_item_id)
        self.assertEqual(mat.unit_cost, Decimal('5.00'))
        self.assertEqual(mat.cost_source, Material.COST_SOURCE_ENTERED)
        self.assertEqual(mat.inventory_item.code, f'LOT-{mat.pk}')

    def test_create_freeform_document_cost_stays_provisional(self):
        # A document-sourced (expense/PO) cost records the cost but does NOT
        # auto-mint — it establishes through its own flow (Tasks 7-9).
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat,
            inventory_item=None, cost_source=Material.COST_SOURCE_EXPENSE,
        )
        self.assertIsNone(mat.inventory_item_id)
        self.assertEqual(mat.unit_cost, Decimal('5.00'))

    def test_create_freeform_zero_cost_stays_provisional(self):
        # A freeform material with NO cost is provisional (no lot, NULL source).
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            unit_cost=Decimal('0.00'), accounting_category=self.cat,
            inventory_item=None,
        )
        self.assertIsNone(mat.inventory_item_id)
        self.assertIsNone(mat.cost_source)
        self.assertEqual(mat.unit_cost, Decimal('0.00'))

    def test_create_pli_backed_cost_ok(self):
        mat = MaterialService.create_on_job(
            job=self.job, description='cataloged', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat,
            inventory_item=self.pli,
        )
        self.assertEqual(mat.unit_cost, Decimal('5.00'))
        self.assertEqual(mat.cost_source, Material.COST_SOURCE_ENTERED)

    def test_update_pricing_sets_pli_backed_cost(self):
        mat = MaterialService.create_on_job(
            job=self.job, description='cataloged', quantity=Decimal('1'),
            accounting_category=self.cat, inventory_item=self.pli,
        )
        MaterialService.update_pricing(mat, unit_cost=Decimal('9.00'))
        mat.refresh_from_db()
        self.assertEqual(mat.unit_cost, Decimal('9.00'))


class FreeformMaterialCostApiTest(TestCase):
    """PATCH/POST pricing a lot-less material establishes it via the API."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        self.client_http = Client()
        self.user = User.objects.create_user(username='u', password='x')
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='c@t.com')
        self.job = Job.objects.create(job_number='JOB-FF-2', contact=self.contact)
        self.freeform = Material.objects.create(
            job=self.job, accounting_category=self.cat, description='ff',
            quantity=Decimal('1.00'),
        )
        self.client_http.force_login(self.user)

    def test_patch_freeform_cost_establishes(self):
        r = self.client_http.patch(
            f'/api/materials/{self.freeform.material_id}/',
            data={'unit_cost': '7.00'}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.freeform.refresh_from_db()
        self.assertIsNotNone(self.freeform.inventory_item_id)
        self.assertEqual(self.freeform.unit_cost, Decimal('7.00'))
        self.assertEqual(self.freeform.cost_source, Material.COST_SOURCE_ENTERED)

    def test_patch_freeform_description_ok(self):
        r = self.client_http.patch(
            f'/api/materials/{self.freeform.material_id}/',
            data={'description': 'renamed'}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_post_freeform_cost_is_born_established(self):
        """Creating a freeform material with a user-entered unit_cost via the API
        mints a lot and returns 201 (the old refusal is gone)."""
        from apps.jobs.models import Task, RateScheme
        scheme = RateScheme.objects.create(
            name='ff-scheme', algorithm=RateScheme.ENTERED_QTY, rate=1,
            unit_label='ea', accounting_category=self.cat)
        task = Task(job=self.job, name='t')
        task.stamp_from_scheme(scheme)
        task.save()
        r = self.client_http.post(
            f'/api/tasks/{task.pk}/materials/',
            data={'description': 'glue', 'quantity': '1.00',
                  'unit_cost': '5.00', 'accounting_category': self.cat.pk},
            content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        m = Material.objects.get(job=self.job, description='glue')
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)
