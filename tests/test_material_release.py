"""Material `released` lifecycle — the named 'planned but not used' retirement.

Doctrine (docs/plans/2026-07-03-deletion-doctrine-named-events.md): a Material
leaves `pending` one of three ways — `consumed` (physical reality), `released`
(a named event said the job planned it and didn't use it: full restock while
referenced, job-completion loose release, PO sever, CO descope), or deleted
(mistake correction, only while nothing references it).

Release moves the quantity into `released_qty` (conservation:
quantity + released_qty == originally planned), so released rows sum to zero in
every aggregate consumer with no state filters needed. Claims survive release —
that's the point: the atom keeps supporting its estimate line as history.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class MaterialReleaseBase(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.pli = InventoryItem.objects.create(
            code='ACR', accounting_category=self.cat,
            qty_on_hand=Decimal('50'), units='ea',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED,
        )

    def _material(self, qty=Decimal('7')):
        return MaterialService.create_on_job(
            job=self.job, description='acrylic', quantity=qty,
            sell_price=Decimal('100.00'), inventory_item=self.pli,
            accounting_category=self.cat, units='ea',
        )

    def _claim(self, material):
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, description='acrylic',
            qty=material.quantity, price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        return line

    def _earmark_qty(self):
        earmark = Earmark.objects.filter(
            job=self.job, inventory_item=self.pli).first()
        return earmark.quantity if earmark else Decimal('0')


class ReleasePrimitiveTests(MaterialReleaseBase):

    def test_release_moves_quantity_and_backs_out_earmark(self):
        material = self._material()
        self.assertEqual(self._earmark_qty(), Decimal('7'))
        MaterialService.release(material)
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(material.quantity, Decimal('0'))
        self.assertEqual(material.released_qty, Decimal('7'))
        self.assertEqual(self._earmark_qty(), Decimal('0'))

    def test_release_requires_pending(self):
        material = self._material()
        MaterialService.consume(material)
        with self.assertRaises(ValidationError):
            MaterialService.release(material)

    def test_release_keeps_claims_resolvable(self):
        material = self._material()
        line = self._claim(material)
        MaterialService.release(material)
        src = line.sources.get()
        self.assertEqual(src.resolve().pk, material.pk)

    def test_released_material_refuses_consume(self):
        material = self._material()
        MaterialService.release(material)
        material.refresh_from_db()
        with self.assertRaises(ValidationError):
            MaterialService.consume(material)


class RestockToZeroRuleTests(MaterialReleaseBase):

    def test_partial_restock_tracks_released_qty_and_stays_pending(self):
        material = self._material()
        MaterialService.restock(material, Decimal('3'))
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(material.quantity, Decimal('4'))
        self.assertEqual(material.released_qty, Decimal('3'))
        self.assertEqual(self._earmark_qty(), Decimal('4'))

    def test_full_restock_unreferenced_deletes(self):
        material = self._material()
        MaterialService.restock(material, Decimal('7'))
        self.assertFalse(Material.objects.filter(pk=material.pk).exists())
        self.assertEqual(self._earmark_qty(), Decimal('0'))

    def test_full_restock_claimed_releases(self):
        material = self._material()
        line = self._claim(material)
        MaterialService.restock(material, Decimal('7'))
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(material.quantity, Decimal('0'))
        self.assertEqual(material.released_qty, Decimal('7'))
        self.assertTrue(line.sources.exists())

    def test_conservation_through_partial_then_full_restock(self):
        material = self._material()
        self._claim(material)
        MaterialService.restock(material, Decimal('2'))
        material.refresh_from_db()
        MaterialService.restock(material, Decimal('5'))
        material.refresh_from_db()
        self.assertEqual(material.quantity + material.released_qty, Decimal('7'))
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)

    def test_loose_release_on_job_completion_keeps_claimed_material(self):
        """The acrylic regression, upgraded: job-completion loose release now
        preserves a claimed material as history instead of deleting it."""
        material = self._material()
        line = self._claim(material)
        released = JobService.release_loose_materials(self.job)
        self.assertEqual(len(released), 1)
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        src = line.sources.get()
        self.assertEqual(src.resolve().pk, material.pk)

    def test_loose_release_deletes_unclaimed_scratch(self):
        material = self._material()
        JobService.release_loose_materials(self.job)
        self.assertFalse(Material.objects.filter(pk=material.pk).exists())

    def test_sever_delete_decision_releases_claimed_material(self):
        """PO sever's 'delete' decision retires a claimed material as released
        (the PO link itself is the thing being dissolved, so it doesn't count
        as a reference)."""
        material = self._material()
        line = self._claim(material)
        MaterialService.sever(material, 'delete')
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(self._earmark_qty(), Decimal('0'))
        self.assertTrue(line.sources.exists())

    def test_sever_delete_decision_deletes_unclaimed_material(self):
        material = self._material()
        MaterialService.sever(material, 'delete')
        self.assertFalse(Material.objects.filter(pk=material.pk).exists())


class ReleasedMaterialDisplayTests(MaterialReleaseBase):

    def test_released_material_out_of_estimate_wizard_pool(self):
        from apps.estimates.services import EstimateWizardService
        material = self._material()
        self._claim(material)
        draft = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0002',
            status=Estimate.STATUS_DRAFT,
        )
        MaterialService.release(material)
        pool = EstimateWizardService.get_source_pool(draft)
        material_ids = [
            a['id'] for a in pool['atoms'] if a['type'] == 'material']
        self.assertNotIn(material.pk, material_ids)
