from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem
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
            price=Decimal('400'), units='ea',
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        li.refresh_from_db()
        self.assertEqual(li.accounting_category, self.default_cat)

    def test_material_with_explicit_ac_is_respected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea',
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
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
                price=Decimal('400'), units='ea',
                freeform_kind=EstimateLineItem.KIND_MATERIAL,
            )

    def test_bare_add_without_kind_raises_kind_required_not_ac(self):
        # Task 4: the old silent bare->fee default at ENTRY is gone — a bare
        # add with no kind at all now fails on the *kind* requirement before
        # ever reaching the AC check (this line has no AC either, but that's
        # no longer the reason it 400s).
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'),
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_fee_without_ac_still_raises(self):
        # freeform_kind='fee' is unchanged: AC is still required.
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'), freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('accounting_category', ctx.exception.message_dict)

    def test_update_cannot_change_kind_even_to_apply_material_default(self):
        # Task 4: freeform_kind is immutable after creation — a fee line
        # can no longer be turned into a material (with its AC default) via
        # update. The line must be created as a material from the start.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.other_cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(
                li.pk, freeform_kind=EstimateLineItem.KIND_MATERIAL, accounting_category=None,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)
        self.assertEqual(li.accounting_category, self.other_cat)

    def test_update_with_is_material_is_retired_field_400(self):
        # Phase 3 Task 6: is_material is retired outright on update too —
        # this used to be the alias's "can't use is_material to sneak past
        # the immutability guard" case; now it 400s as a retired field
        # before the immutability check even runs.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.other_cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(
                li.pk, is_material=True, accounting_category=None,
            )
        self.assertIn('is_material', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)
        self.assertEqual(li.accounting_category, self.other_cat)
