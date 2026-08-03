"""freeform_kind is a real writable model field now that is_material is
gone (task-owned-money Phase 2 Task 2 review fix). The generic
LineItemMixin (apps/api/mixins.py) passes raw request.data straight through
to add_line_item/update_line_item, so a caller could set freeform_kind
directly on a catalog/service/adjustment line without ever touching the
is_material alias — violating the mapping invariant this task establishes
(freeform_kind non-null IFF the line is a bare freeform line). These tests
cover the write-time guard (_reject_freeform_kind_on_non_bare_line) added to
close that gap, plus confirm the existing is_material alias paths are
unaffected.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, RateScheme


class FreeformKindWriteGuardSetup(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='fk-guard@test.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )
        self.co = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate,
        )
        self.pli = InventoryItem.objects.create(
            code='PLY', accounting_category=self.cat,
        )


class EstimateFreeformKindWriteGuardTest(FreeformKindWriteGuardSetup):

    def test_add_catalog_line_with_direct_freeform_kind_rejected(self):
        """A client sending freeform_kind directly on an inventory_item line
        (no is_material) must be rejected — the old is_material alias never
        even sees this field, so nothing else would have caught it."""
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='ply', qty=Decimal('1'),
                price=Decimal('1'), accounting_category=self.cat.pk,
                inventory_item=self.pli.pk,
                freeform_kind=EstimateLineItem.KIND_MATERIAL,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_add_adjustment_line_with_direct_freeform_kind_rejected(self):
        adj = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='rush', qty=Decimal('1'),
                price=Decimal('0'), accounting_category=self.cat.pk,
                adjustment_service=adj.pk,
                freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_update_catalog_line_with_direct_freeform_kind_rejected(self):
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, self.pli.pk, Decimal('2'))
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, freeform_kind=EstimateLineItem.KIND_MATERIAL)
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_add_bare_line_with_direct_freeform_kind_honored(self):
        """No is_material sent at all — freeform_kind set directly on a bare
        line is a legitimate write (this is the shape Task 4 formalizes) and
        must not be rejected by the new guard."""
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush handling', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)

    def test_update_bare_line_kind_is_immutable(self):
        # Task 4: freeform_kind is immutable after creation — supersedes the
        # earlier "update honors a direct freeform_kind" expectation this
        # test previously asserted (that also required a bare add with no
        # kind at all, which Task 4's kind-required-on-add rule now 400s
        # before this even reaches update).
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush handling', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(
                li.pk, freeform_kind=EstimateLineItem.KIND_MATERIAL,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)

    def test_update_bare_line_resending_same_kind_succeeds(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush handling', qty=Decimal('1'),
            price=Decimal('25'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        updated = EstimateService.update_line_item(
            li.pk, freeform_kind=EstimateLineItem.KIND_FEE, description='Rush (edited)',
        )
        self.assertEqual(updated.freeform_kind, EstimateLineItem.KIND_FEE)
        self.assertEqual(updated.description, 'Rush (edited)')

    # -- is_material alias paths still green (unaffected by the new guard) --

    def test_is_material_alias_add_bare_material_line_still_works(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
            price=Decimal('400'), units='ea', accounting_category=self.cat.pk,
            is_material=True,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_MATERIAL)

    def test_is_material_alias_rejects_inventory_item_line(self):
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item(
                self.estimate.pk, description='ply', qty=Decimal('1'),
                price=Decimal('1'), accounting_category=self.cat.pk,
                inventory_item=self.pli.pk, is_material=True,
            )


class ChangeOrderFreeformKindWriteGuardTest(FreeformKindWriteGuardSetup):

    def test_add_catalog_line_with_direct_freeform_kind_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='ply', qty=Decimal('1'), price=Decimal('1'),
                accounting_category=self.cat.pk, inventory_item=self.pli.pk,
                freeform_kind=ChangeOrderLineItem.KIND_MATERIAL,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_update_catalog_line_with_direct_freeform_kind_rejected(self):
        li = ChangeOrderService.add_line_item_from_pli(self.co.pk, self.pli.pk, Decimal('2'))
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.update_line_item(li.pk, freeform_kind=ChangeOrderLineItem.KIND_MATERIAL)
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_add_bare_line_with_direct_freeform_kind_honored(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Rush handling', qty=Decimal('1'), price=Decimal('25'),
            accounting_category=self.cat.pk,
            freeform_kind=ChangeOrderLineItem.KIND_FEE,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, ChangeOrderLineItem.KIND_FEE)

    # -- is_material alias path still green --

    def test_is_material_alias_add_bare_material_line_still_works(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='ABS sheet', qty=Decimal('1'), price=Decimal('400'),
            units='ea', accounting_category=self.cat.pk, is_material=True,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, ChangeOrderLineItem.KIND_MATERIAL)
