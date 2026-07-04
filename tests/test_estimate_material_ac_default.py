from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job


class EstimateMaterialAcDefaultTest(TestCase):
    def setUp(self):
        self.default_cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT',
        )
        self.other_cat = AccountingCategory.objects.create(
            name='Freight', is_active=True, code='FRT',
        )
        # New config key — string value is an AccountingCategory pk.
        Configuration.objects.create(
            key='default_material_accounting_category',
            value=str(self.default_cat.pk),
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

    def test_material_without_ac_defaults_from_config(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea', is_material=True,
        )
        li.refresh_from_db()
        self.assertEqual(li.accounting_category, self.default_cat)

    def test_material_with_explicit_ac_is_respected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea', is_material=True,
            accounting_category=self.other_cat.pk,
        )
        li.refresh_from_db()
        self.assertEqual(li.accounting_category, self.other_cat)

    def test_material_without_ac_and_no_config_raises(self):
        Configuration.objects.filter(
            key='default_material_accounting_category',
        ).delete()
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
                price=Decimal('400'), units='ea', is_material=True,
            )

    def test_fee_without_ac_still_raises(self):
        # is_material=False (a fee) is unchanged: AC is still required.
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'),
            )

    def test_update_to_material_without_ac_defaults_from_config(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.other_cat.pk,
        )
        # Clear the AC and mark it a material in one update.
        EstimateService.update_line_item(
            li.pk, is_material=True, accounting_category=None,
        )
        li.refresh_from_db()
        self.assertTrue(li.is_material)
        self.assertEqual(li.accounting_category, self.default_cat)
