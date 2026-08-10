"""
Tests for Task 6 (CO amend-in-place plan): the adjustment-amendment service
path.

A ChangeOrder REPLACE line whose target is itself an EstimateLineItem
percentage-adjustment (e.g. a 10% rush fee) carries the target's adjustment
provenance (adjustment_service, adjustment_target_categories) and has its
price recomputed against the AMENDED agreement basis —
compose_amended_agreement(co)'s surviving non-adjustment rows — after every
CO line mutation (ChangeOrderService.recompute_adjustment_replaces).

Covers (brief Step 1 a-g):
  (a) replace of a 10% rush fee to 5% -> copied service/targets, price = 5%
      of the amended non-adjustment total
  (b) targeted categories respected
  (c) adding a CO add-line afterwards re-raises the adjustment-replace price
  (d) removing an estimate line via CO lowers it
  (e) percent-less replace copies the target's percent
  (f) API create with adjustment_percent round-trips
  (g) acceptance of the adjustment-replace changes no atoms and the composed
      agreement carries the new percent/price
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
)
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task
from tests.base import FixtureTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_can_manage_jobs(user):
    perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
    user.user_permissions.add(perm)
    from apps.core.models import User
    return User.objects.get(pk=user.pk)


def _make_accepted_estimate(job, number='EST-ADJ-CO-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _make_co(job, estimate):
    return ChangeOrder.objects.create(job=job, estimate=estimate)


# ---------------------------------------------------------------------------
# Base fixture shared by the service-level tests: an accepted estimate with
# two non-adjustment base lines (labor 100, materials 40 -> 140 total) and a
# 10% rush-fee adjustment line targeting ALL non-adjustment lines (14.00).
# ---------------------------------------------------------------------------

class AdjustmentReplaceBase(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

        self.labor = AccountingCategory.objects.create(
            code='LAB-COADJ', name='Labor-COADJ', taxable=False)
        self.materials = AccountingCategory.objects.create(
            code='MAT-COADJ', name='Materials-COADJ', taxable=False)

        self.est = _make_accepted_estimate(self.job)
        self.li_labor = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Labor',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.labor,
        )
        self.li_materials = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, description='Materials',
            qty=Decimal('1'), price=Decimal('40.00'),
            accounting_category=self.materials,
        )

        self.scheme = RateScheme.objects.create(
            name='Rush-COADJ', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.labor,
        )
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=3, description='Rush 10%',
            qty=Decimal('1'), price=Decimal('14.00'),
            units='pct',
            accounting_category=self.labor,
            adjustment_service=self.scheme, adjustment_percent=Decimal('10.00'),
        )

        self.co = _make_co(self.job, self.est)


# ---------------------------------------------------------------------------
# (a) Replace of a 10% rush fee to 5%
# ---------------------------------------------------------------------------

class AdjustmentReplaceBasicTests(AdjustmentReplaceBase):
    def test_replace_copies_provenance_and_computes_amended_price(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        li.refresh_from_db()

        self.assertEqual(li.adjustment_service_id, self.scheme.pk)
        self.assertEqual(li.adjustment_percent, Decimal('5.00'))
        self.assertEqual(li.qty, Decimal('1.00'))
        self.assertEqual(li.units, self.adj.units)
        self.assertEqual(li.accounting_category_id, self.adj.accounting_category_id)
        self.assertEqual(li.description, self.adj.description)
        self.assertEqual(
            list(li.adjustment_target_categories.all()),
            list(self.adj.adjustment_target_categories.all()),
        )
        # 5% of (100 + 40) = 7.00
        self.assertEqual(li.price, Decimal('7.00'))


# ---------------------------------------------------------------------------
# (b) Targeted categories respected
# ---------------------------------------------------------------------------

class AdjustmentReplaceTargetedCategoriesTests(AdjustmentReplaceBase):
    def setUp(self):
        super().setUp()
        # Narrow the original adjustment to labor only: 10% of 100 = 10.00.
        self.adj.adjustment_target_categories.set([self.labor])
        self.adj.price = Decimal('10.00')
        self.adj.save()

    def test_replace_respects_copied_target_categories(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        li.refresh_from_db()
        self.assertEqual(
            {c.pk for c in li.adjustment_target_categories.all()}, {self.labor.pk},
        )
        # 5% of labor-only (100) = 5.00, materials (40) excluded.
        self.assertEqual(li.price, Decimal('5.00'))


# ---------------------------------------------------------------------------
# (c) Adding a CO add-line afterwards re-raises the adjustment-replace price
# ---------------------------------------------------------------------------

class AdjustmentReplaceRecomputeOnAddTests(AdjustmentReplaceBase):
    def test_later_add_line_recomputes_the_adjustment_replace(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertEqual(li.price, Decimal('7.00'))  # 5% of 140

        ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope',
            qty='1', price='60.00',
            accounting_category=self.labor.pk,
        )

        li.refresh_from_db()
        # basis now 100 + 40 + 60 = 200 -> 5% = 10.00
        self.assertEqual(li.price, Decimal('10.00'))


# ---------------------------------------------------------------------------
# (d) Removing an estimate line via CO lowers it
# ---------------------------------------------------------------------------

class AdjustmentReplaceRecomputeOnRemoveTests(AdjustmentReplaceBase):
    def test_later_remove_line_lowers_the_adjustment_replace(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertEqual(li.price, Decimal('7.00'))  # 5% of 140

        ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.li_materials.pk,
        )

        li.refresh_from_db()
        # basis now 100 only -> 5% = 5.00
        self.assertEqual(li.price, Decimal('5.00'))


# ---------------------------------------------------------------------------
# (e) Percent-less replace copies the target's percent
# ---------------------------------------------------------------------------

class AdjustmentReplacePercentLessTests(AdjustmentReplaceBase):
    def test_percent_less_replace_copies_target_percent(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            description='Rush 10% (relabeled)',
        )
        li.refresh_from_db()
        self.assertEqual(li.adjustment_percent, Decimal('10.00'))
        self.assertEqual(li.description, 'Rush 10% (relabeled)')
        # 10% of 140 = 14.00 (unchanged basis, unchanged percent)
        self.assertEqual(li.price, Decimal('14.00'))


# ---------------------------------------------------------------------------
# (f) API create with adjustment_percent round-trips
# ---------------------------------------------------------------------------

class AdjustmentReplaceAPITests(AdjustmentReplaceBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_adj_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.client.force_authenticate(user=self.manager)

    def test_create_with_adjustment_percent_round_trips(self):
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items/',
            {
                'action': ChangeOrderLineItem.ACTION_REPLACE,
                'target_line_item': self.adj.pk,
                'adjustment_percent': '5.00',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['adjustment_percent']), Decimal('5.00'))
        self.assertEqual(resp.data['adjustment_service'], self.scheme.pk)
        self.assertEqual(Decimal(resp.data['price']), Decimal('7.00'))

        li = ChangeOrderLineItem.objects.get(pk=resp.data['line_item_id'])
        self.assertEqual(li.adjustment_percent, Decimal('5.00'))
        self.assertEqual(li.price, Decimal('7.00'))


# ---------------------------------------------------------------------------
# (g) Acceptance of the adjustment-replace changes no atoms and the composed
# agreement carries the new percent/price
# ---------------------------------------------------------------------------

class AdjustmentReplaceAcceptanceTests(AdjustmentReplaceBase):
    def test_acceptance_touches_no_atoms_and_composed_agreement_updates(self):
        from apps.estimates.agreement import compose_agreement

        li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertEqual(li.price, Decimal('7.00'))

        tasks_before = Task.objects.filter(job=self.job).count()
        materials_before = Material.objects.filter(job=self.job).count()

        ChangeOrderService.mark_open(self.co.pk)
        ChangeOrderService.update_status(self.co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.assertEqual(Task.objects.filter(job=self.job).count(), tasks_before)
        self.assertEqual(Material.objects.filter(job=self.job).count(), materials_before)

        result = compose_agreement(self.job)
        adj_line = next(
            l for l in result['lines'] if l['description'] == self.adj.description)
        self.assertEqual(adj_line['percent'], Decimal('5.00'))
        self.assertEqual(adj_line['price'], Decimal('7.00'))
        self.assertEqual(adj_line['amount'], Decimal('7.00'))


# ---------------------------------------------------------------------------
# Fix round 1 — review findings on the initial Task 6 submission.
# ---------------------------------------------------------------------------

# CRITICAL 1: delete_line_item crashed for EVERY CO line (missing ChangeOrder
# entry in LineItemService.get_line_items_for_container's field_name_map).

class DeleteLineItemDoesNotCrashTests(AdjustmentReplaceBase):
    def test_service_delete_of_a_plain_line_succeeds_and_renumbers(self):
        add_line = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty='1', price='20.00',
            accounting_category=self.labor.pk,
        )
        ChangeOrderService.delete_line_item(add_line.pk)
        self.assertFalse(
            ChangeOrderLineItem.objects.filter(pk=add_line.pk).exists())

    def test_api_delete_returns_200(self):
        self.client = APIClient()
        from apps.core.models import User
        manager = User.objects.create_user(username='co_adj_del_mgr', password='x')
        manager = _add_can_manage_jobs(manager)
        self.client.force_authenticate(user=manager)

        add_line = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty='1', price='20.00',
            accounting_category=self.labor.pk,
        )
        resp = self.client.delete(
            f'/api/change-orders/{self.co.pk}/line-items/{add_line.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(
            ChangeOrderLineItem.objects.filter(pk=add_line.pk).exists())

    def test_delete_recomputes_adjustment_replace_price(self):
        """Deleting a plain (non-adjustment) CO line on a CO that also
        carries an adjustment-replace line must refresh that line's price
        against the new amended basis."""
        replace_li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        add_line = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty='1', price='60.00',
            accounting_category=self.labor.pk,
        )
        replace_li.refresh_from_db()
        # basis 100 + 40 + 60 = 200 -> 5% = 10.00
        self.assertEqual(replace_li.price, Decimal('10.00'))

        ChangeOrderService.delete_line_item(add_line.pk)

        replace_li.refresh_from_db()
        # basis back to 140 -> 5% = 7.00
        self.assertEqual(replace_li.price, Decimal('7.00'))


# IMPORTANT 2: add_line_item_from_pli / add_line_item_from_service skipped
# recompute_adjustment_replaces, so an adjustment-replace price went stale
# through those two add paths.

class AddFromPliAndServiceRecomputeTests(AdjustmentReplaceBase):
    def test_add_line_item_from_pli_recomputes_adjustment_replace(self):
        from apps.inventory.models import InventoryItem

        replace_li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertEqual(replace_li.price, Decimal('7.00'))  # 5% of 140

        pli = InventoryItem.objects.create(
            code='PLY-COADJ', accounting_category=self.labor,
            qty_on_hand=Decimal('50'), purchase_price=Decimal('30'),
            selling_price=Decimal('60.00'), units='ea',
        )
        ChangeOrderService.add_line_item_from_pli(self.co.pk, pli.pk, '1')

        replace_li.refresh_from_db()
        # basis 100 + 40 + 60 = 200 -> 5% = 10.00
        self.assertEqual(replace_li.price, Decimal('10.00'))

    def test_add_line_item_from_service_recomputes_adjustment_replace(self):
        from apps.estimates.models import ServiceItem

        replace_li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertEqual(replace_li.price, Decimal('7.00'))  # 5% of 140

        hourly = RateScheme.objects.create(
            name='Hourly-COADJ', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60.00'), unit_label='hour',
            accounting_category=self.labor,
        )
        service_item = ServiceItem.objects.create(
            template_name='Cutting-COADJ', rate_scheme=hourly,
        )
        ChangeOrderService.add_line_item_from_service(self.co.pk, service_item.pk, '1')

        replace_li.refresh_from_db()
        # basis 100 + 40 + 60 = 200 -> 5% = 10.00
        self.assertEqual(replace_li.price, Decimal('10.00'))


# IMPORTANT 3: retargeting a REPLACE line away from an adjustment target left
# the stale adjustment triple in place, tripping ChangeOrderLineItem.clean().

class RetargetAwayFromAdjustmentTests(AdjustmentReplaceBase):
    def test_retargeting_to_a_plain_line_clears_the_adjustment_triple(self):
        replace_li = ChangeOrderService.add_line_item(
            self.co.pk,
            action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk,
            adjustment_percent='5.00',
        )
        self.assertIsNotNone(replace_li.adjustment_service_id)

        updated = ChangeOrderService.update_line_item(
            replace_li.pk,
            target_line_item=self.li_labor.pk,
            description='Labor v2', qty='1', price='120.00',
            accounting_category=self.labor.pk,
        )

        self.assertIsNone(updated.adjustment_service_id)
        self.assertIsNone(updated.adjustment_percent)
        self.assertEqual(list(updated.adjustment_target_categories.all()), [])
        # Confirm it's now a fully valid plain replace.
        updated.full_clean()
