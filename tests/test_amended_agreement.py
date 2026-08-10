"""
Tests for compose_amended_agreement(co) — the server-composed "amended
agreement" (apps/estimates/agreement.py) and its GET endpoint
(/api/change-orders/{id}/amended-agreement/).

compose_amended_agreement folds the baseline (the accepted estimate plus the
accepted COs that precede `co` in acceptance order) and then applies `co`'s
own add/remove/replace lines on top, producing kind-tagged rows plus
original/co_delta/revised totals.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import FixtureTestCase
from apps.core.models import AccountingCategory
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
    EstimateLineItemSource,
)
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job, RateScheme, Task


# ---------------------------------------------------------------------------
# Helpers (mirror tests/test_agreement_composition.py's local helpers)
# ---------------------------------------------------------------------------

def _make_accepted_estimate(job, number='EST-AMD-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _make_est_line(estimate, line_number, description, qty, price, **kwargs):
    return EstimateLineItem.objects.create(
        estimate=estimate, line_number=line_number, description=description,
        qty=Decimal(str(qty)), price=Decimal(str(price)), **kwargs,
    )


def _make_co(job, estimate, *, accepted=False, closed_date=None):
    co = ChangeOrder.objects.create(job=job, estimate=estimate)
    if accepted:
        ChangeOrder.objects.filter(pk=co.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=closed_date or timezone.now(),
        )
        co.refresh_from_db()
    return co


def _make_co_line(co, line_number, action, description='', qty='1', price='0',
                   target=None, **kwargs):
    return ChangeOrderLineItem.objects.create(
        change_order=co, line_number=line_number, action=action,
        description=description, qty=Decimal(str(qty)), price=Decimal(str(price)),
        target_line_item=target, **kwargs,
    )


# ---------------------------------------------------------------------------
# Row kinds, co_index ordering, totals
# ---------------------------------------------------------------------------

class ComposeAmendedAgreementRowKindsTests(FixtureTestCase):
    """Draft CO with a remove, a replace, and an add: agreement / removed /
    replaced / added rows, co_index numbering, and the three totals."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '2', '100.00')
        self.li2 = _make_est_line(self.est, 2, 'Widget B', '1', '50.00')
        self.li3 = _make_est_line(self.est, 3, 'Widget C', '3', '25.00')

        self.co = _make_co(self.job, self.est)  # draft
        _make_co_line(self.co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li2)
        self.replace_line = _make_co_line(
            self.co, 2, ChangeOrderLineItem.ACTION_REPLACE,
            description='Widget C v2', qty='5', price='30.00', target=self.li3)
        self.add_line = _make_co_line(
            self.co, 3, ChangeOrderLineItem.ACTION_ADD,
            description='Extra Item', qty='2', price='60.00')

    def test_row_kinds_and_shapes(self):
        from apps.estimates.agreement import compose_amended_agreement
        result = compose_amended_agreement(self.co)
        rows = result['rows']

        kinds = [r['kind'] for r in rows]
        self.assertEqual(kinds, ['agreement', 'removed', 'replaced', 'added'])

        agreement_row = rows[0]
        self.assertEqual(agreement_row['line']['description'], 'Widget A')
        self.assertIn('billed_on', agreement_row)
        self.assertIn('adjustment_expected_amount', agreement_row)

        removed_row = rows[1]
        self.assertEqual(removed_row['original']['description'], 'Widget B')
        self.assertEqual(removed_row['co_line_id'],
                          ChangeOrderLineItem.objects.get(
                              change_order=self.co, line_number=1).pk)
        self.assertNotIn('line', removed_row)

        replaced_row = rows[2]
        self.assertEqual(replaced_row['line']['description'], 'Widget C v2')
        self.assertEqual(replaced_row['original']['description'], 'Widget C')
        self.assertEqual(replaced_row['co_line_id'], self.replace_line.pk)

        added_row = rows[3]
        self.assertEqual(added_row['line']['description'], 'Extra Item')
        self.assertEqual(added_row['co_line_id'], self.add_line.pk)

    def test_co_index_numbers_add_and_replace_in_line_number_order_skipping_removes(self):
        from apps.estimates.agreement import compose_amended_agreement
        result = compose_amended_agreement(self.co)
        by_co_line = {r['co_line_id']: r for r in result['rows'] if r['kind'] != 'agreement'}

        self.assertEqual(by_co_line[self.replace_line.pk]['co_index'], 1)
        self.assertEqual(by_co_line[self.add_line.pk]['co_index'], 2)
        # removed row carries no co_index
        removed_row = next(r for r in result['rows'] if r['kind'] == 'removed')
        self.assertNotIn('co_index', removed_row)

    def test_totals(self):
        from apps.estimates.agreement import compose_amended_agreement
        result = compose_amended_agreement(self.co)

        # baseline: 200 + 50 + 75 = 325
        self.assertEqual(result['original_total'], Decimal('325.00'))
        # revised: li1 (200) + replaced li3 (5*30=150) + added (2*60=120) = 470
        self.assertEqual(result['revised_total'], Decimal('470.00'))
        self.assertEqual(result['co_delta'], Decimal('145.00'))


# ---------------------------------------------------------------------------
# billed_on
# ---------------------------------------------------------------------------

class ComposeAmendedAgreementBilledOnTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '2', '100.00')
        self.co = _make_co(self.job, self.est)  # draft, no lines needed

    def _agreement_row_for(self, result, description):
        return next(r for r in result['rows']
                    if r['kind'] == 'agreement' and r['line']['description'] == description)

    def test_billed_on_populated_for_live_invoice(self):
        from apps.estimates.agreement import compose_amended_agreement
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='Widget A',
            qty=Decimal('2'), price=Decimal('100.00'),
            agreement_estimate_line=self.li1,
        )
        result = compose_amended_agreement(self.co)
        row = self._agreement_row_for(result, 'Widget A')
        self.assertEqual(row['billed_on'], invoice.display_number)

    def test_billed_on_absent_for_cancelled_invoice(self):
        from apps.estimates.agreement import compose_amended_agreement
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='Widget A',
            qty=Decimal('2'), price=Decimal('100.00'),
            agreement_estimate_line=self.li1,
        )
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_CANCELLED)

        result = compose_amended_agreement(self.co)
        row = self._agreement_row_for(result, 'Widget A')
        self.assertIsNone(row['billed_on'])


# ---------------------------------------------------------------------------
# Baseline selection / no double-apply
# ---------------------------------------------------------------------------

class ComposeAmendedAgreementBaselineTests(FixtureTestCase):
    """Baseline = estimate + accepted COs preceding `co` in acceptance
    order. An accepted CO's own record view must not double-apply its own
    deltas, and an earlier accepted CO's baseline view must not see a later
    CO's deltas."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.li1 = _make_est_line(self.est, 1, 'Widget A', '1', '100.00')
        self.li2 = _make_est_line(self.est, 2, 'Widget B', '1', '50.00')

        now = timezone.now()
        self.co1 = _make_co(self.job, self.est, accepted=True,
                             closed_date=now - timezone.timedelta(hours=1))
        self.co1_line = _make_co_line(
            self.co1, 1, ChangeOrderLineItem.ACTION_REPLACE,
            description='Widget B v2', qty='1', price='70.00', target=self.li2)

        self.co2 = _make_co(self.job, self.est, accepted=True, closed_date=now)
        self.co2_line = _make_co_line(
            self.co2, 1, ChangeOrderLineItem.ACTION_REPLACE,
            description='Widget A v2', qty='1', price='150.00', target=self.li1)

    def test_later_accepted_co_baseline_includes_earlier_co_but_not_itself(self):
        """Viewing co2 (accepted, later): baseline includes co1's replace of
        li2 but must apply co2's OWN replace of li1 fresh — not have it
        already folded into the baseline (which would make 'original' for
        the li1 row read co2's own replacement text instead of the true
        prior state)."""
        from apps.estimates.agreement import compose_amended_agreement
        result = compose_amended_agreement(self.co2)
        rows = result['rows']

        # li2 (replaced by co1, in baseline) shows as an untouched 'agreement'
        # row carrying co1's replacement text.
        agreement_row = next(r for r in rows if r['kind'] == 'agreement')
        self.assertEqual(agreement_row['line']['description'], 'Widget B v2')

        # li1 (replaced by co2 itself) shows as 'replaced' with the TRUE
        # original ('Widget A'), not double-applied.
        replaced_row = next(r for r in rows if r['kind'] == 'replaced')
        self.assertEqual(replaced_row['line']['description'], 'Widget A v2')
        self.assertEqual(replaced_row['original']['description'], 'Widget A')
        self.assertEqual(replaced_row['original']['price'], Decimal('100.00'))

        # baseline total: li1 unmodified (100) + li2-as-replaced-by-co1 (70) = 170
        self.assertEqual(result['original_total'], Decimal('170.00'))
        # revised: li2 v2 (70) + li1 v2 (150) = 220
        self.assertEqual(result['revised_total'], Decimal('220.00'))

    def test_earlier_accepted_co_record_view_does_not_see_later_co(self):
        """Viewing co1 (accepted, earlier): baseline is the raw estimate
        (no accepted CO precedes co1); co2's replace of li1 must NOT show up
        — li1 stays an untouched 'agreement' row reading the original
        estimate text."""
        from apps.estimates.agreement import compose_amended_agreement
        result = compose_amended_agreement(self.co1)
        rows = result['rows']

        agreement_row = next(r for r in rows if r['kind'] == 'agreement')
        self.assertEqual(agreement_row['line']['description'], 'Widget A')

        replaced_row = next(r for r in rows if r['kind'] == 'replaced')
        self.assertEqual(replaced_row['line']['description'], 'Widget B v2')
        self.assertEqual(replaced_row['original']['description'], 'Widget B')

        # baseline total: raw estimate = 100 + 50 = 150
        self.assertEqual(result['original_total'], Decimal('150.00'))
        # revised: li1 unmodified (100) + li2 v2 (70) = 170
        self.assertEqual(result['revised_total'], Decimal('170.00'))


# ---------------------------------------------------------------------------
# adjustment_expected_amount staleness
# ---------------------------------------------------------------------------

class ComposeAmendedAgreementAdjustmentStalenessTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.cat = AccountingCategory.objects.create(
            code='LAB-AMD', name='Labor-AMD', taxable=False)
        self.est = _make_accepted_estimate(self.job)
        self.li_a = _make_est_line(self.est, 1, 'Base A', '1', '100.00',
                                    accounting_category=self.cat)
        self.li_b = _make_est_line(self.est, 2, 'Base B', '1', '40.00',
                                    accounting_category=self.cat)
        self.scheme = RateScheme.objects.create(
            name='Rush-AMD', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%', accounting_category=self.cat,
        )
        # 10% of (100 + 40) = 14 — in sync with the current estimate.
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=3, description='Rush 10%',
            qty=Decimal('1'), price=Decimal('14.00'),
            adjustment_service=self.scheme, adjustment_percent=Decimal('10.00'),
        )

    def _adj_row(self, result):
        return next(r for r in result['rows']
                    if r['kind'] == 'agreement' and r['line']['description'] == 'Rush 10%')

    def test_none_when_in_sync(self):
        from apps.estimates.agreement import compose_amended_agreement
        co = _make_co(self.job, self.est)  # draft, no lines
        result = compose_amended_agreement(co)
        row = self._adj_row(result)
        self.assertIsNone(row['adjustment_expected_amount'])

    def test_stale_when_co_remove_changes_the_amended_basis(self):
        """CO removes Base B (40): amended basis becomes 100, so the stored
        14.00 (10% of 140) no longer matches the amended-basis expectation
        (10% of 100 = 10.00)."""
        from apps.estimates.agreement import compose_amended_agreement
        co = _make_co(self.job, self.est)
        _make_co_line(co, 1, ChangeOrderLineItem.ACTION_REMOVE, target=self.li_b)
        result = compose_amended_agreement(co)
        row = self._adj_row(result)
        self.assertEqual(row['adjustment_expected_amount'], Decimal('10.00'))


# ---------------------------------------------------------------------------
# Endpoint: GET /api/change-orders/{id}/amended-agreement/
# ---------------------------------------------------------------------------

class AmendedAgreementEndpointTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.user = User.objects.create_user(username='amd_agree', password='x')
        self.client.force_authenticate(user=self.user)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.cat = AccountingCategory.objects.create(
            code='LAB-AMD-EP', name='Labor-AMD-EP', taxable=False)
        self.est = _make_accepted_estimate(self.job)

        # A task-backed estimate line, in sync (est_qty=2, rate=100 -> 200.00).
        self.scheme = RateScheme.objects.create(
            name='Hourly-AMD-EP', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100.00'), unit_label='hr', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Cutting', est_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.li_task = _make_est_line(self.est, 1, 'Cutting labor', '2', '200.00',
                                       accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.li_task,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

        self.co = _make_co(self.job, self.est)  # draft
        self.replace_line = _make_co_line(
            self.co, 1, ChangeOrderLineItem.ACTION_REPLACE,
            description='Cutting labor (revised)', qty='2', price='250.00',
            target=self.li_task)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(f'/api/change-orders/{self.co.pk}/amended-agreement/')
        self.assertIn(resp.status_code, [401, 403])

    def test_returns_200_with_backing_and_inherited_sources_on_replace_row(self):
        resp = self.client.get(f'/api/change-orders/{self.co.pk}/amended-agreement/')
        self.assertEqual(resp.status_code, 200, resp.data)

        rows = resp.data['rows']
        replaced_row = next(r for r in rows if r['kind'] == 'replaced')
        self.assertEqual(replaced_row['line']['description'], 'Cutting labor (revised)')
        self.assertEqual(replaced_row['co_line_id'], self.replace_line.pk)

        # backing: price 250 vs. the target's resolvable source total (200) ->
        # out of sync -> 'edited'.
        self.assertEqual(replaced_row['backing'], 'edited')
        self.assertEqual(replaced_row['backing_total'], '200.00')

        sources = replaced_row['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['inherited_from_line'], self.li_task.line_number)
        self.assertEqual(sources[0]['description'], 'Cutting')

        # totals are present and stringified
        self.assertIn('original_total', resp.data)
        self.assertIn('co_delta', resp.data)
        self.assertIn('revised_total', resp.data)
