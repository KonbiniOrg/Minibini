"""Tests for compose_change_order_diff — the customer/portal-facing line-item
diff of a ChangeOrder against its (accepted) estimate's line items. Mirrors the
shop CO detail page's merged-rows logic.
"""
from decimal import Decimal

from tests.base import FixtureTestCase
from apps.estimates.agreement import compose_change_order_diff
from apps.estimates.models import (
    Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem,
)
from apps.jobs.models import Job


class ComposeChangeOrderDiffTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-DIFF-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.l1 = EstimateLineItem.objects.create(
            estimate=self.est, description='Line one', qty=Decimal('2'),
            units='ea', price=Decimal('100.00'), line_number=1,
        )
        self.l2 = EstimateLineItem.objects.create(
            estimate=self.est, description='Line two', qty=Decimal('1'),
            units='ea', price=Decimal('50.00'), line_number=2,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def _kinds(self, result):
        return [r['kind'] for r in result['line_rows']]

    def test_no_co_lines_all_unchanged(self):
        result = compose_change_order_diff(self.co)
        self.assertEqual(self._kinds(result), ['unchanged', 'unchanged'])
        self.assertEqual(result['prior_total'], Decimal('250.00'))
        self.assertEqual(result['proposed_total'], Decimal('250.00'))
        self.assertEqual(result['diff_total'], Decimal('0.00'))

    def test_add_appends_added_row(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Brand new', qty=Decimal('3'), units='ea',
            price=Decimal('10.00'), line_number=1,
        )
        result = compose_change_order_diff(self.co)
        self.assertEqual(self._kinds(result), ['unchanged', 'unchanged', 'added'])
        added = result['line_rows'][-1]
        self.assertEqual(added['description'], 'Brand new')
        self.assertEqual(added['amount'], Decimal('30.00'))
        self.assertEqual(result['proposed_total'], Decimal('280.00'))
        self.assertEqual(result['diff_total'], Decimal('30.00'))

    def test_remove_strikes_target(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.l2, description='Line two', qty=Decimal('1'),
            units='ea', price=Decimal('50.00'), line_number=1,
        )
        result = compose_change_order_diff(self.co)
        self.assertEqual(self._kinds(result), ['unchanged', 'removed'])
        # removed line does NOT count toward proposed
        self.assertEqual(result['prior_total'], Decimal('250.00'))
        self.assertEqual(result['proposed_total'], Decimal('200.00'))
        self.assertEqual(result['diff_total'], Decimal('-50.00'))

    def test_replace_emits_changed_then_orig(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.l1, description='Line one revised',
            qty=Decimal('2'), units='ea', price=Decimal('150.00'), line_number=1,
        )
        result = compose_change_order_diff(self.co)
        self.assertEqual(
            self._kinds(result), ['changed', 'changed-orig', 'unchanged'])
        changed = result['line_rows'][0]
        orig = result['line_rows'][1]
        self.assertEqual(changed['description'], 'Line one revised')
        self.assertEqual(changed['amount'], Decimal('300.00'))
        self.assertEqual(orig['description'], 'Line one')
        self.assertEqual(orig['amount'], Decimal('200.00'))
        # proposed counts the changed (new) value, not the struck original
        self.assertEqual(result['proposed_total'], Decimal('350.00'))
        self.assertEqual(result['diff_total'], Decimal('100.00'))

    def test_added_rows_sorted_by_line_number(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='second add', qty=Decimal('1'), units='ea',
            price=Decimal('5.00'), line_number=2,
        )
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='first add', qty=Decimal('1'), units='ea',
            price=Decimal('5.00'), line_number=1,
        )
        result = compose_change_order_diff(self.co)
        added = [r['description'] for r in result['line_rows'] if r['kind'] == 'added']
        self.assertEqual(added, ['first add', 'second add'])
