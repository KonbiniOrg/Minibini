from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, RateScheme


class EstimateServiceIsMaterialTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )

    def test_add_bare_line_persists_is_material(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea', accounting_category=self.cat.pk,
            is_material=True,
        )
        li.refresh_from_db()
        self.assertTrue(li.is_material)

    def test_add_defaults_is_material_false(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.cat.pk,
        )
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_add_rejects_is_material_with_inventory_item(self):
        pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='ply', qty=Decimal('1'),
                price=Decimal('1'), accounting_category=self.cat.pk,
                inventory_item=pli.pk, is_material=True,
            )

    def test_add_rejects_is_material_with_adjustment_service(self):
        adj = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='rush', qty=Decimal('1'),
                price=Decimal('0'), accounting_category=self.cat.pk,
                adjustment_service=adj.pk, is_material=True,
            )

    def test_update_toggles_is_material(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.cat.pk,
        )
        EstimateService.update_line_item(li.pk, is_material=True)
        li.refresh_from_db()
        self.assertTrue(li.is_material)

    def test_update_rejects_is_material_on_inventory_line(self):
        pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
        )
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, pli.pk, Decimal('2'))
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(li.pk, is_material=True)
