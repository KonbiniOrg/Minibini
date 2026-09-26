"""is_material is DERIVED, never client-sent (RM 2026-08-11): a bare hand
line is a material exactly when its accounting category is the configured
`default_material_accounting_category`. The old "Is this a material?"
checkbox is retired — choosing the Materials AC is the gesture."""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, RateScheme


class EstimateServiceIsMaterialTest(TestCase):
    def setUp(self):
        self.mat_cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.lab_cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        Configuration.objects.update_or_create(
            key='default_material_accounting_category',
            defaults={'value': str(self.mat_cat.pk)},
        )
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )

    def test_bare_line_with_material_ac_derives_is_material_true(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea', accounting_category=self.mat_cat.pk,
        )
        li.refresh_from_db()
        self.assertTrue(li.is_material)

    def test_bare_line_with_other_ac_derives_is_material_false(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.lab_cat.pk,
        )
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_client_sent_is_material_is_ignored(self):
        # The server is authoritative: a stray is_material=True with a
        # non-material AC does not stick.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.lab_cat.pk,
            is_material=True,
        )
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_inventory_line_with_material_ac_stays_false(self):
        pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.mat_cat,
        )
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, pli.pk, Decimal('2'))
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_adjustment_line_with_material_ac_stays_false(self):
        adj = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.mat_cat,
        )
        li = EstimateService.add_line_item(
            self.estimate.pk, description='rush', qty=Decimal('1'),
            price=Decimal('0'), accounting_category=self.mat_cat.pk,
            adjustment_service=adj.pk, adjustment_percent=Decimal('10'),
        )
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_update_rederives_when_ac_changes(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.lab_cat.pk,
        )
        self.assertFalse(li.is_material)
        EstimateService.update_line_item(li.pk, accounting_category=self.mat_cat.pk)
        li.refresh_from_db()
        self.assertTrue(li.is_material)
        EstimateService.update_line_item(li.pk, accounting_category=self.lab_cat.pk)
        li.refresh_from_db()
        self.assertFalse(li.is_material)

    def test_no_configured_default_means_never_material(self):
        Configuration.objects.filter(
            key='default_material_accounting_category').delete()
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.mat_cat.pk,
        )
        li.refresh_from_db()
        self.assertFalse(li.is_material)
