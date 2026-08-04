"""`is_material` is retired (task-owned-money Phase 2 Task 2 introduced
freeform_kind as its replacement; Phase 3 Task 6 removed the compatibility
alias that used to translate the boolean into freeform_kind at the service
boundary). These tests originally exercised that alias — rewritten to
confirm a payload still sending `is_material` gets a clean 400 naming the
retired field, on both add and update, regardless of what else is in the
payload."""
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

    def test_add_bare_line_with_is_material_true_is_retired_field_400(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
                price=Decimal('400'), units='ea', accounting_category=self.cat.pk,
                is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_add_without_kind_or_alias_raises(self):
        # Task 4: the old silent bare->fee default at ENTRY is gone — a bare
        # add with no freeform_kind at all is a 400 (Task 6 removed the
        # is_material alias entirely, so there is no alias branch left to
        # supply a kind here).
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'), accounting_category=self.cat.pk,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_add_is_material_false_is_retired_field_400(self):
        # The alias's historical False->'fee' mapping is gone entirely —
        # sending is_material=False is a 400 same as True.
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25'), accounting_category=self.cat.pk,
                is_material=False,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_add_rejects_is_material_with_inventory_item(self):
        # Phase 3 Task 6: is_material is a hard 400 regardless of the rest
        # of the payload — the old alias's own "conflicts with an inventory
        # item" check no longer applies; the retired-field rejection fires
        # first, before the line is even constructed.
        pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='ply', qty=Decimal('1'),
                price=Decimal('1'), accounting_category=self.cat.pk,
                inventory_item=pli.pk, is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_add_rejects_is_material_with_adjustment_service(self):
        adj = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='rush', qty=Decimal('1'),
                price=Decimal('0'), accounting_category=self.cat.pk,
                adjustment_service=adj.pk, is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_update_with_is_material_is_retired_field_400(self):
        # Task 4: freeform_kind is immutable after creation — this used to
        # be the alias's "changing kind via is_material is rejected" case.
        # Task 6 removed the alias, so it's rejected as a retired field
        # before the immutability check ever runs.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS', qty=Decimal('1'),
            price=Decimal('400'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, is_material=True)
        self.assertIn('is_material', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)

    def test_update_rejects_is_material_on_inventory_line(self):
        pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
        )
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, pli.pk, Decimal('2'))
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, is_material=True)
        self.assertIn('is_material', ctx.exception.message_dict)
