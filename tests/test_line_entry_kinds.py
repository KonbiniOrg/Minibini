"""TDD tests for task-owned-money Phase 2 Task 4: line-entry validation.

Covers the rules that only apply at entry (add_line_item / update_line_item),
on top of the freeform_kind field itself (Task 2) and acceptance's three-way
branch on it (Task 3):

1. Kind required on a bare freeform ADD — the old silent bare->fee default
   at ENTRY is gone. A direct freeform_kind (including 'work') is required;
   `is_material` is retired (Task 6 removed the compatibility alias) — any
   payload still sending it is a clean 400 naming `is_material`, regardless
   of what else (including a valid freeform_kind) is in the payload.
2. Sign rules: negative price only on a fee/credit line; a fee/credit line's
   price must never be zero (it would crystallize into a Fee with
   unit_rate=0, which FeeService forbids).
3. AC rules: fee and work lines require an accounting_category at entry
   (material keeps its config-default path) — this already falls out of the
   existing generic hand-line AC-required check once every hand-line has a
   determinate kind; covered here for kind-specific documentation.
4. freeform_kind is immutable after creation — an update attempting to
   change it directly is rejected; re-sending the same value is a no-op,
   not an error. A retired `is_material` key on an update is a 400 same as
   on add.

ChangeOrderService mirrors all of this, but "kind required on ADD" only
applies to action=ADD lines — REPLACE/REMOVE lines mirror the old atom's
type or don't crystallize a new one, so they carry no kind requirement.

is_material retired-field tests live in this file (the old alias-mapping
tests, rewritten) and in test_freeform_kind_write_guard.py.
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


class LineEntryKindsSetup(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='lek@test.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.estimate)
        self.pli = InventoryItem.objects.create(code='PLY', accounting_category=self.cat)


class EstimateKindRequiredOnAddTest(LineEntryKindsSetup):

    def test_bare_add_without_kind_or_alias_raises_400(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25.00'), accounting_category=self.cat.pk,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_direct_work_kind_honored_on_add(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('2'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_WORK)

    def test_bare_add_with_is_material_true_is_retired_field_400(self):
        # is_material is retired (Task 6 removed the compatibility alias
        # that used to translate True -> 'material').
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='ABS', qty=Decimal('1'),
                price=Decimal('400.00'), accounting_category=self.cat.pk,
                is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_bare_add_with_is_material_false_is_retired_field_400(self):
        # Same for the historical False -> 'fee' mapping.
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25.00'), accounting_category=self.cat.pk,
                is_material=False,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_is_material_alongside_direct_kind_is_still_retired_field_400(self):
        # Even when a valid freeform_kind is also present, sending
        # is_material at all is rejected — it no longer "loses" to a direct
        # kind; the retired field is a hard error regardless of payload
        # shape.
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Cutting', qty=Decimal('2'),
                price=Decimal('50.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_WORK, is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_non_bare_line_unaffected_by_kind_requirement(self):
        # Catalog (inventory_item) lines never carry freeform_kind — the
        # ADD-kind-required rule must not fire for them.
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, self.pli.pk, Decimal('2'))
        self.assertIsNone(li.freeform_kind)


class EstimatePriceSignTest(LineEntryKindsSetup):

    def test_negative_price_rejected_on_work_line(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Cutting', qty=Decimal('1'),
                price=Decimal('-10.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_WORK,
            )
        self.assertIn('price', ctx.exception.message_dict)

    def test_negative_price_rejected_on_material_line(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Foam', qty=Decimal('1'),
                price=Decimal('-10.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_MATERIAL,
            )
        self.assertIn('price', ctx.exception.message_dict)

    def test_negative_price_rejected_on_catalog_line_update(self):
        # Catalog (inventory_item) lines never take a user-supplied price at
        # add time (it's snapshotted off the InventoryItem) — the sign guard
        # is exercised on update instead, where price is user-editable.
        li = EstimateService.add_line_item_from_pli(self.estimate.pk, self.pli.pk, Decimal('2'))
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, price=Decimal('-5.00'))
        self.assertIn('price', ctx.exception.message_dict)

    def test_negative_price_allowed_on_fee_line(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Credit', qty=Decimal('1'),
            price=Decimal('-10.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        self.assertEqual(li.price, Decimal('-10.00'))

    def test_zero_price_rejected_on_fee_line(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Free', qty=Decimal('1'),
                price=Decimal('0.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('price', ctx.exception.message_dict)

    def test_zero_price_allowed_on_material_line(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Sample', qty=Decimal('1'),
            price=Decimal('0.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        self.assertEqual(li.price, Decimal('0.00'))

    def test_negative_price_allowed_on_adjustment_line(self):
        adj = RateScheme.objects.create(
            name='Discount', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('-10'), unit_label='%', accounting_category=self.cat,
        )
        # Adjustment lines carry their percent on adjustment_percent, not
        # price — this just confirms the sign guard doesn't fire on them.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Discount', qty=Decimal('1'),
            price=Decimal('0.00'), accounting_category=self.cat.pk,
            adjustment_service=adj.pk, adjustment_percent=adj.rate,
        )
        self.assertEqual(li.price, Decimal('0.00'))

    # ── I1 review finding: update-path sign rules ──────────────────
    # A bare hand-line still enforces the sign rules on PATCH; a
    # wizard-composed (source-bearing) line is exempt — its price derives
    # from the atoms it claims, not a freeform_kind the caller chose.

    def test_update_bare_work_line_to_negative_price_rejected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, price=Decimal('-5.00'))
        self.assertIn('price', ctx.exception.message_dict)

    def test_update_bare_fee_line_to_zero_price_rejected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Credit', qty=Decimal('1'),
            price=Decimal('-10.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, price=Decimal('0.00'))
        self.assertIn('price', ctx.exception.message_dict)

    def test_update_sourced_negative_line_description_succeeds(self):
        """A wizard-composed line built from atoms (e.g. a bundle including
        a negative Fee atom) carries a negative price with no freeform_kind
        at all — editing its description must not 400 on the sign rules
        meant for hand-authored lines."""
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import Fee

        fee = Fee.objects.create(
            job=self.job, description='Bundled credit',
            unit_rate=Decimal('-15.00'), accounting_category=self.cat,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, description='Bundle', qty=Decimal('1'),
            price=Decimal('-15.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        updated = EstimateService.update_line_item(li.pk, description='Bundle (renamed)')
        self.assertEqual(updated.description, 'Bundle (renamed)')
        self.assertEqual(updated.price, Decimal('-15.00'))


class EstimateQtySignTest(LineEntryKindsSetup):
    """Final review of task-owned-money Phase 3, Finding 2: a fee/credit
    line's qty must be > 0 — mirrors EstimatePriceSignTest's zero-price rule
    (amount = qty * price, so a zero/negative qty is just as much a
    billed-money bug as a zero/negative price)."""

    def test_zero_qty_rejected_on_fee_line(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Free', qty=Decimal('0.00'),
                price=Decimal('25.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('qty', ctx.exception.message_dict)

    def test_negative_qty_rejected_on_fee_line(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('-1.00'),
                price=Decimal('25.00'), accounting_category=self.cat.pk,
                freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('qty', ctx.exception.message_dict)

    def test_zero_qty_allowed_on_work_line(self):
        # The qty>0 rule is scoped to fee/credit lines — other kinds are a
        # pre-existing, separately-scoped concern.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('0.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        self.assertEqual(li.qty, Decimal('0.00'))

    def test_update_bare_fee_line_to_zero_qty_rejected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Credit', qty=Decimal('1'),
            price=Decimal('-10.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, qty=Decimal('0.00'))
        self.assertIn('qty', ctx.exception.message_dict)

    def test_update_sourced_zero_qty_line_succeeds(self):
        """A wizard-composed line built from atoms is exempt from the
        qty>0 rule meant for hand-authored lines — same exemption
        EstimatePriceSignTest.test_update_sourced_negative_line_description_succeeds
        exercises for price."""
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import Fee

        fee = Fee.objects.create(
            job=self.job, description='Bundled credit', quantity=Decimal('1'),
            unit_rate=Decimal('-15.00'), accounting_category=self.cat,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, description='Bundle', qty=Decimal('1'),
            price=Decimal('-15.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        updated = EstimateService.update_line_item(li.pk, qty=Decimal('0.00'))
        self.assertEqual(updated.qty, Decimal('0.00'))


class EstimateFeeWorkACRequiredTest(LineEntryKindsSetup):

    def test_fee_line_without_ac_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Rush', qty=Decimal('1'),
                price=Decimal('25.00'), freeform_kind=EstimateLineItem.KIND_FEE,
            )
        self.assertIn('accounting_category', ctx.exception.message_dict)

    def test_work_line_without_ac_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.add_line_item(
                self.estimate.pk, description='Cutting', qty=Decimal('1'),
                price=Decimal('50.00'), freeform_kind=EstimateLineItem.KIND_WORK,
            )
        self.assertIn('accounting_category', ctx.exception.message_dict)


class EstimateKindImmutableOnUpdateTest(LineEntryKindsSetup):

    def test_update_changing_kind_directly_rejected(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, freeform_kind=EstimateLineItem.KIND_MATERIAL)
        self.assertIn('freeform_kind', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_WORK)

    def test_update_with_is_material_is_retired_field_400(self):
        # is_material is retired on update too (Task 6) — this used to be
        # the alias's "changing kind via is_material is rejected" case;
        # now it's rejected up front as a retired field, before the
        # immutability check even runs.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, is_material=True)
        self.assertIn('is_material', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_WORK)

    def test_update_resending_same_kind_is_a_noop_success(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        updated = EstimateService.update_line_item(
            li.pk, freeform_kind=EstimateLineItem.KIND_WORK, description='Cutting (edited)',
        )
        self.assertEqual(updated.freeform_kind, EstimateLineItem.KIND_WORK)
        self.assertEqual(updated.description, 'Cutting (edited)')

    def test_update_resending_is_material_false_is_still_retired_field_400(self):
        # Even "False", and even when it would have been a no-op under the
        # old alias, is_material is a hard 400 now — there is no meaningful
        # value for the retired key any more.
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Rush', qty=Decimal('1'),
            price=Decimal('25.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.update_line_item(li.pk, is_material=False, qty=Decimal('2'))
        self.assertIn('is_material', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_FEE)
        self.assertEqual(li.qty, Decimal('1'))

    def test_update_other_fields_without_touching_kind_leaves_it_unchanged(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Cutting', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        updated = EstimateService.update_line_item(li.pk, qty=Decimal('3'))
        self.assertEqual(updated.freeform_kind, EstimateLineItem.KIND_WORK)
        self.assertEqual(updated.qty, Decimal('3'))


class ChangeOrderKindRequiredOnAddTest(LineEntryKindsSetup):

    def test_bare_add_without_kind_or_alias_raises_400(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Extra scope', qty=Decimal('1'), price=Decimal('25.00'),
                accounting_category=self.cat.pk,
            )
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_direct_work_kind_honored_on_add(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra cutting', qty=Decimal('2'), price=Decimal('50.00'),
            accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        self.assertEqual(li.freeform_kind, ChangeOrderLineItem.KIND_WORK)

    def test_is_material_alongside_direct_kind_is_retired_field_400(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Extra cutting', qty=Decimal('2'), price=Decimal('50.00'),
                accounting_category=self.cat.pk,
                freeform_kind=ChangeOrderLineItem.KIND_WORK, is_material=True,
            )
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_replace_line_without_kind_is_not_required(self):
        # REPLACE/REMOVE lines mirror the old atom or retire it — the
        # kind-required rule is scoped to ACTION_ADD only.
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Base',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.cat,
        )
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=line.pk, description='Replacement',
            qty=Decimal('1'), price=Decimal('120.00'),
        )
        self.assertIsNone(li.freeform_kind)

    def test_remove_line_without_kind_is_not_required(self):
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Base',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.cat,
        )
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=line.pk,
        )
        self.assertIsNone(li.freeform_kind)


class ChangeOrderPriceSignTest(LineEntryKindsSetup):

    def test_negative_price_rejected_on_work_add_line(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Cutting', qty=Decimal('1'), price=Decimal('-10.00'),
                accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_WORK,
            )
        self.assertIn('price', ctx.exception.message_dict)

    def test_negative_price_allowed_on_fee_add_line(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Credit', qty=Decimal('1'), price=Decimal('-10.00'),
            accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_FEE,
        )
        self.assertEqual(li.price, Decimal('-10.00'))

    def test_zero_price_rejected_on_fee_add_line(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Free', qty=Decimal('1'), price=Decimal('0.00'),
                accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_FEE,
            )
        self.assertIn('price', ctx.exception.message_dict)


class ChangeOrderQtySignTest(LineEntryKindsSetup):
    """CO twin of EstimateQtySignTest — ChangeOrderService.add_line_item /
    update_line_item share EstimateService._validate_qty."""

    def test_zero_qty_rejected_on_fee_add_line(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Free', qty=Decimal('0.00'), price=Decimal('25.00'),
                accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_FEE,
            )
        self.assertIn('qty', ctx.exception.message_dict)

    def test_negative_qty_rejected_on_fee_add_line(self):
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
                description='Rush', qty=Decimal('-1.00'), price=Decimal('25.00'),
                accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_FEE,
            )
        self.assertIn('qty', ctx.exception.message_dict)


class ChangeOrderKindImmutableOnUpdateTest(LineEntryKindsSetup):

    def test_update_changing_kind_directly_rejected(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Cutting', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.update_line_item(li.pk, freeform_kind=ChangeOrderLineItem.KIND_MATERIAL)
        self.assertIn('freeform_kind', ctx.exception.message_dict)

    def test_update_resending_same_kind_is_a_noop_success(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_ADD,
            description='Cutting', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat.pk, freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        updated = ChangeOrderService.update_line_item(
            li.pk, freeform_kind=ChangeOrderLineItem.KIND_WORK, qty=Decimal('4'),
        )
        self.assertEqual(updated.freeform_kind, ChangeOrderLineItem.KIND_WORK)
        self.assertEqual(updated.qty, Decimal('4'))
