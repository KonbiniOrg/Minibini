"""B-group service extraction (2026-07-04): viewsets own no persistence.

The metadata tails moved into services; two behaviors CHANGED to match the
deletion doctrine and the earmark rules, pinned here:

- MaterialService.remove refuses consumed/released rows (actuals/history are
  never hard-deleted; the old endpoint would delete them), and applies the
  restock-to-zero rule to qty-0 pending rows (referenced → released,
  unreferenced → deleted).
- Quantity writes are refused by MaterialService.update_fields on BOTH
  material PATCH endpoints (the /api/materials/{id}/ one previously saved a
  bare quantity without any earmark math).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from tests.base import grant_atoms
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


class MaterialRemoveDoctrineTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='sow', code='SOW')
        contact = Contact.objects.create(first_name='S', last_name='W')
        self.job = Job.objects.create(
            job_number='JOB-SOW-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)

    def _material(self, state=Material.CONSUMPTION_STATE_PENDING, qty='2.00'):
        m = Material(
            job=self.job, description='m', quantity=Decimal(qty),
            accounting_category=self.cat, consumption_state=state)
        m.save()
        return m

    def _claim(self, material):
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SOW-1',
            status=Estimate.STATUS_ACCEPTED)
        line = EstimateLineItem.objects.create(
            estimate=est, line_number=1, description='c',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk)

    def test_consumed_material_cannot_be_removed(self):
        m = self._material(state=Material.CONSUMPTION_STATE_CONSUMED)
        with self.assertRaises(ValidationError):
            MaterialService.remove(m)
        self.assertTrue(Material.objects.filter(pk=m.pk).exists())

    def test_released_material_cannot_be_removed(self):
        m = self._material(state=Material.CONSUMPTION_STATE_RELEASED, qty='0.00')
        with self.assertRaises(ValidationError):
            MaterialService.remove(m)

    def test_pending_zero_qty_referenced_is_released_not_deleted(self):
        m = self._material(qty='0.00')
        self._claim(m)
        result = MaterialService.remove(m)
        self.assertIsNotNone(result)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state,
                         Material.CONSUMPTION_STATE_RELEASED)

    def test_pending_zero_qty_unreferenced_is_deleted(self):
        m = self._material(qty='0.00')
        self.assertIsNone(MaterialService.remove(m))
        self.assertFalse(Material.objects.filter(pk=m.pk).exists())

    def test_pending_with_qty_routes_through_restock(self):
        m = self._material(qty='3.00')
        self._claim(m)
        MaterialService.remove(m)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state,
                         Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(m.released_qty, Decimal('3.00'))
        self.assertEqual(m.quantity, Decimal('0.00'))


class MaterialQuantityPatchRefusedTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='sqp', code='SQP')
        contact = Contact.objects.create(first_name='Q', last_name='P')
        self.job = Job.objects.create(
            job_number='JOB-SQP-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)
        self.material = Material(
            job=self.job, description='m', quantity=Decimal('2.00'),
            accounting_category=self.cat)
        self.material.save()
        self.client = APIClient()
        self.client.force_authenticate(user=grant_atoms(
            User.objects.create_user(username='sqp_u', password='x'),
            'can_manage_jobs'))

    def test_materials_endpoint_refuses_bare_quantity_write(self):
        # Previously saved straight through with no earmark math.
        resp = self.client.patch(
            f'/api/materials/{self.material.pk}/',
            {'quantity': '9.00'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('2.00'))

    def test_metadata_patch_still_works(self):
        resp = self.client.patch(
            f'/api/materials/{self.material.pk}/',
            {'description': 'renamed'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.material.refresh_from_db()
        self.assertEqual(self.material.description, 'renamed')
