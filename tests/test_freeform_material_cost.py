from decimal import Decimal
from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService

User = get_user_model()


class FreeformMaterialCostServiceTest(TestCase):
    """A freeform (no-PLI) actual Material's cost is document-sourced, not typed."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='c@t.com')
        self.job = Job.objects.create(job_number='JOB-FF-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='PLI-1', description='cataloged', accounting_category=self.cat,
            purchase_price=Decimal('3.00'),
        )

    def test_create_freeform_with_manual_cost_rejected(self):
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=self.job, description='freeform', quantity=Decimal('1'),
                unit_cost=Decimal('5.00'), accounting_category=self.cat,
                inventory_item=None, cost_source='manual',
            )

    def test_create_freeform_document_cost_ok(self):
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat,
            inventory_item=None, cost_source='document',
        )
        self.assertEqual(mat.unit_cost, Decimal('5.00'))

    def test_create_freeform_zero_cost_manual_ok(self):
        # A freeform material with NO cost is fine to create manually.
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            unit_cost=Decimal('0.00'), accounting_category=self.cat,
            inventory_item=None, cost_source='manual',
        )
        self.assertEqual(mat.unit_cost, Decimal('0.00'))

    def test_create_pli_manual_cost_ok(self):
        mat = MaterialService.create_on_job(
            job=self.job, description='cataloged', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat,
            inventory_item=self.pli, cost_source='manual',
        )
        self.assertEqual(mat.unit_cost, Decimal('5.00'))

    def test_update_pricing_document_sets_freeform_cost(self):
        mat = MaterialService.create_on_job(
            job=self.job, description='freeform', quantity=Decimal('1'),
            accounting_category=self.cat, inventory_item=None,
        )
        MaterialService.update_pricing(mat, unit_cost=Decimal('9.00'), cost_source='document')
        mat.refresh_from_db()
        self.assertEqual(mat.unit_cost, Decimal('9.00'))


class FreeformMaterialCostApiTest(TestCase):
    """PATCH editing a freeform material's cost manually is rejected."""

    def setUp(self):
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

    def test_patch_freeform_manual_cost_rejected(self):
        r = self.client_http.patch(
            f'/api/materials/{self.freeform.material_id}/',
            data={'unit_cost': '7.00'}, content_type='application/json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_patch_freeform_description_ok(self):
        r = self.client_http.patch(
            f'/api/materials/{self.freeform.material_id}/',
            data={'description': 'renamed'}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_post_freeform_manual_cost_rejected(self):
        """Creating a freeform material with a manual unit_cost via the API is
        rejected (the same validate() guard as PATCH, on the create path)."""
        from apps.jobs.models import Task, ServiceItem
        scheme = ServiceItem.objects.create(
            name='ff-scheme', algorithm=ServiceItem.FLAT_FEE, rate=1,
            unit_label='ea', accounting_category=self.cat)
        task = Task.objects.create(job=self.job, name='t', service_item=scheme)
        r = self.client_http.post(
            f'/api/tasks/{task.pk}/materials/',
            data={'description': 'glue', 'quantity': '1.00',
                  'unit_cost': '5.00', 'accounting_category': self.cat.pk},
            content_type='application/json')
        self.assertEqual(r.status_code, 400, r.content)
