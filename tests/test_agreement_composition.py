"""
Tests for compose_agreement(job) — the agreement-of-record composition.

compose_agreement returns the effective set of billing lines = the accepted
estimate's line items with each accepted change order's add/remove/replace
deltas applied, plus the grand total.
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from tests.base import FixtureTestCase
from apps.estimates.models import Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem
from apps.jobs.models import Job


def _make_accepted_estimate(job, number='EST-AGR-1'):
    """Create an accepted estimate directly (bypasses transition guards)."""
    return Estimate.objects.create(
        job=job,
        estimate_number=number,
        version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _make_est_line(estimate, line_number, description, qty, price):
    """Create an EstimateLineItem with explicit line_number."""
    return EstimateLineItem.objects.create(
        estimate=estimate,
        line_number=line_number,
        description=description,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
    )


def _make_accepted_co(job, estimate):
    """Create a ChangeOrder already in accepted status, bypassing lifecycle side-effects."""
    co = ChangeOrder.objects.create(job=job, estimate=estimate)
    ChangeOrder.objects.filter(pk=co.pk).update(
        status=ChangeOrder.STATUS_ACCEPTED,
        closed_date=timezone.now(),
    )
    co.refresh_from_db()
    return co


def _make_co_line(co, line_number, action, description='', qty='1', price='0', target=None):
    """Create a ChangeOrderLineItem. target is the EstimateLineItem FK for remove/replace."""
    return ChangeOrderLineItem.objects.create(
        change_order=co,
        line_number=line_number,
        action=action,
        description=description,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
        target_line_item=target,
    )


class ComposeAgreementNoEstimateTests(FixtureTestCase):
    """compose_agreement returns empty result when no accepted estimate exists."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

    def test_no_accepted_estimate_returns_empty(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.job)
        self.assertEqual(result['lines'], [])
        self.assertEqual(result['grand_total'], Decimal('0'))

    def test_draft_estimate_not_accepted_returns_empty(self):
        from apps.estimates.agreement import compose_agreement
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-DRAFT-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        result = compose_agreement(self.job)
        self.assertEqual(result['lines'], [])
        self.assertEqual(result['grand_total'], Decimal('0'))


class ComposeAgreementNoCOTests(FixtureTestCase):
    """compose_agreement with accepted estimate but no COs returns the estimate lines."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '2', '100.00')
        self.li2 = _make_est_line(self.est, 2, 'Widget B', '1', '50.00')
        self.li3 = _make_est_line(self.est, 3, 'Widget C', '3', '25.00')

    def test_three_lines_returned_in_order(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.job)
        lines = result['lines']
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]['description'], 'Widget A')
        self.assertEqual(lines[1]['description'], 'Widget B')
        self.assertEqual(lines[2]['description'], 'Widget C')

    def test_all_lines_have_estimate_origin(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.job)
        for line in result['lines']:
            self.assertEqual(line['origin'], 'estimate')

    def test_line_fields_are_correct(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.job)
        line = result['lines'][0]
        self.assertEqual(line['description'], 'Widget A')
        self.assertEqual(line['qty'], Decimal('2'))
        self.assertEqual(line['price'], Decimal('100.00'))
        self.assertEqual(line['amount'], Decimal('200.00'))

    def test_grand_total_is_sum_of_amounts(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.job)
        # line1: 2*100=200, line2: 1*50=50, line3: 3*25=75  → total=325
        expected = Decimal('200.00') + Decimal('50.00') + Decimal('75.00')
        self.assertEqual(result['grand_total'], expected)


class ComposeAgreementWithCOTests(FixtureTestCase):
    """compose_agreement applies accepted CO deltas correctly."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '2', '100.00')
        self.li2 = _make_est_line(self.est, 2, 'Widget B', '1', '50.00')
        self.li3 = _make_est_line(self.est, 3, 'Widget C', '3', '25.00')

    def test_co_remove_drops_line(self):
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)

        result = compose_agreement(self.job)
        descriptions = [l['description'] for l in result['lines']]
        self.assertNotIn('Widget B', descriptions)
        self.assertIn('Widget A', descriptions)
        self.assertIn('Widget C', descriptions)
        self.assertEqual(len(result['lines']), 2)

    def test_co_replace_swaps_content(self):
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REPLACE,
                      description='Widget C UPGRADED', qty='3', price='40.00',
                      target=self.li3)

        result = compose_agreement(self.job)
        descriptions = [l['description'] for l in result['lines']]
        self.assertNotIn('Widget C', descriptions)
        self.assertIn('Widget C UPGRADED', descriptions)

        replaced = next(l for l in result['lines'] if l['description'] == 'Widget C UPGRADED')
        self.assertEqual(replaced['qty'], Decimal('3'))
        self.assertEqual(replaced['price'], Decimal('40.00'))
        self.assertEqual(replaced['amount'], Decimal('120.00'))
        self.assertEqual(replaced['origin'], 'change_order')

    def test_co_add_appends_line(self):
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_ADD,
                      description='New Service', qty='1', price='200.00')

        result = compose_agreement(self.job)
        self.assertEqual(len(result['lines']), 4)
        added = result['lines'][-1]
        self.assertEqual(added['description'], 'New Service')
        self.assertEqual(added['origin'], 'change_order')

    def test_co_remove_replace_add_combined(self):
        """CO removes li2, replaces li3, adds new line → [li1, replaced-li3, added]."""
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        _make_co_line(co, 2, ChangeOrderLineItem.ACTION_REPLACE,
                      description='Widget C v2', qty='5', price='30.00',
                      target=self.li3)
        _make_co_line(co, 3, ChangeOrderLineItem.ACTION_ADD,
                      description='Extra Item', qty='2', price='60.00')

        result = compose_agreement(self.job)
        lines = result['lines']
        self.assertEqual(len(lines), 3)

        # Position 0: surviving li1
        self.assertEqual(lines[0]['description'], 'Widget A')
        self.assertEqual(lines[0]['origin'], 'estimate')
        self.assertEqual(lines[0]['amount'], Decimal('200.00'))

        # Position 1: replaced li3 (in original position)
        self.assertEqual(lines[1]['description'], 'Widget C v2')
        self.assertEqual(lines[1]['origin'], 'change_order')
        self.assertEqual(lines[1]['amount'], Decimal('150.00'))  # 5*30

        # Position 2: added line (appended)
        self.assertEqual(lines[2]['description'], 'Extra Item')
        self.assertEqual(lines[2]['origin'], 'change_order')
        self.assertEqual(lines[2]['amount'], Decimal('120.00'))  # 2*60

        # Grand total: 200 + 150 + 120 = 470
        self.assertEqual(result['grand_total'], Decimal('470.00'))

    def test_lines_carry_estimate_line_identity(self):
        """All estimate-origin lines carry estimate_line_id and have co_line_id=None."""
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_ADD,
                      description='New Service', qty='1', price='200.00')

        lines = compose_agreement(self.job)['lines']
        est_lines = [l for l in lines if l['origin'] == 'estimate']
        self.assertTrue(est_lines)
        for l in est_lines:
            self.assertIsNotNone(l['estimate_line_id'])
            self.assertIsNone(l['co_line_id'])

    def test_co_added_lines_carry_co_line_identity(self):
        """All CO-origin lines (add/replace) carry co_line_id and have estimate_line_id=None."""
        from apps.estimates.agreement import compose_agreement
        co = _make_accepted_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_ADD,
                      description='New Service', qty='1', price='200.00')

        lines = compose_agreement(self.job)['lines']
        co_lines = [l for l in lines if l['origin'] == 'change_order']
        self.assertTrue(co_lines)
        for l in co_lines:
            self.assertIsNotNone(l['co_line_id'])
            self.assertIsNone(l['estimate_line_id'])

    def test_non_accepted_co_is_ignored(self):
        """Draft, open, rejected COs must not affect the composition."""
        from apps.estimates.agreement import compose_agreement
        # Create a draft CO with a remove action
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        # co remains STATUS_DRAFT

        result = compose_agreement(self.job)
        # All three estimate lines should still be present
        self.assertEqual(len(result['lines']), 3)

    def test_rejected_co_is_ignored(self):
        from apps.estimates.agreement import compose_agreement
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        ChangeOrder.objects.filter(pk=co.pk).update(
            status=ChangeOrder.STATUS_REJECTED,
            closed_date=timezone.now(),
        )

        result = compose_agreement(self.job)
        self.assertEqual(len(result['lines']), 3)


class ComposeAgreementMultipleCOTests(FixtureTestCase):
    """compose_agreement stacks multiple accepted COs in acceptance order."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '2', '100.00')
        self.li2 = _make_est_line(self.est, 2, 'Widget B', '1', '50.00')
        self.li3 = _make_est_line(self.est, 3, 'Widget C', '3', '25.00')

    def test_second_co_removes_surviving_original_line(self):
        """CO1: remove li2, replace li3, add new. CO2: remove li1.
        Final: [replaced-li3, added]."""
        from apps.estimates.agreement import compose_agreement

        # CO1 — earlier closed_date
        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co1, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        _make_co_line(co1, 2, ChangeOrderLineItem.ACTION_REPLACE,
                      description='Widget C v2', qty='5', price='30.00',
                      target=self.li3)
        _make_co_line(co1, 3, ChangeOrderLineItem.ACTION_ADD,
                      description='Extra Item', qty='2', price='60.00')
        ChangeOrder.objects.filter(pk=co1.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now() - timezone.timedelta(hours=1),
        )

        # CO2 — later closed_date, removes li1
        co2 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co2, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li1)
        ChangeOrder.objects.filter(pk=co2.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now(),
        )

        result = compose_agreement(self.job)
        lines = result['lines']
        descriptions = [l['description'] for l in lines]

        # li1 removed by CO2, li2 removed by CO1, li3 replaced by CO1
        self.assertNotIn('Widget A', descriptions)
        self.assertNotIn('Widget B', descriptions)
        self.assertIn('Widget C v2', descriptions)
        self.assertIn('Extra Item', descriptions)
        self.assertEqual(len(lines), 2)

        # Grand total: 5*30 + 2*60 = 150 + 120 = 270
        self.assertEqual(result['grand_total'], Decimal('270.00'))

    def test_remove_already_removed_line_is_noop(self):
        """CO2 trying to remove a line that CO1 already removed is silently ignored."""
        from apps.estimates.agreement import compose_agreement

        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co1, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        ChangeOrder.objects.filter(pk=co1.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now() - timezone.timedelta(hours=1),
        )

        co2 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _make_co_line(co2, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        ChangeOrder.objects.filter(pk=co2.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now(),
        )

        result = compose_agreement(self.job)
        # li2 gone once; li1 and li3 survive
        descriptions = [l['description'] for l in result['lines']]
        self.assertNotIn('Widget B', descriptions)
        self.assertEqual(len(result['lines']), 2)
