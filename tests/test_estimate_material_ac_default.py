"""The old _apply_material_ac_default behavior (checkbox-driven material
lines defaulting their AC from config) is retired — is_material now DERIVES
from the chosen AC (RM 2026-08-11; see test_estimate_is_material_service).
What survives here: every bare hand line requires an accounting category at
add time, uniformly — there is no material exemption anymore."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job


class EstimateHandLineAcRequiredTest(TestCase):
    def setUp(self):
        self.mat_cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT',
        )
        Configuration.objects.create(
            key='default_material_accounting_category',
            value=str(self.mat_cat.pk),
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

    def test_hand_line_without_ac_raises(self):
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'),
            )

    def test_hand_line_without_ac_raises_even_with_stray_is_material(self):
        # The retired checkbox used to exempt material lines (AC defaulted
        # from config). No more: a stray is_material kwarg buys nothing.
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
                price=Decimal('400'), units='ea', is_material=True,
            )
