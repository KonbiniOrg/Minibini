from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme
from apps.estimates.models import ServiceItem
from apps.jobs.flat_fee_reframe import reframe_flat_fee_prices

# The live PlanTask model has been removed (job-owns-atoms refactor), and
# live Task itself no longer has a same-named FK to stand in for the
# migration-era Task/PlanTask (task-owned-money Phase 1 renamed it to the
# provenance-only source_scheme, and active_modifiers is now a snapshot
# list, not the {'flat_fee_price': ...} dict this helper's Task/PlanTask
# branch expects). These tests never create any Task rows — the Task/
# PlanTask branch was always meant to be a no-op scan here — so both slots
# get a genuine empty stand-in instead of the live Task class, rather than
# coupling this migration-helper test to Task's current live shape.


class _EmptyModel:
    """Stand-in for the migration-era Task/PlanTask args: always reports
    zero rows, regardless of `fk_field`, so reframe_flat_fee_prices's
    Task/PlanTask branch is a no-op — these tests only exercise the
    ServiceItem branch."""
    class objects:
        @staticmethod
        def select_related(*args, **kwargs):
            class _EmptyQuerySet:
                def all(self):
                    return []
            return _EmptyQuerySet()


class _BareCreateProxy:
    """Stand-in for the `ServicePrice` arg reframe_flat_fee_prices actually
    gets from the real migration: a bare historical model (Django's
    migration state auto-generates one with only fields/Meta, no custom
    methods), where 'flat_fee' was still a valid ALGORITHM_CHOICES entry at
    that point in schema history. Finding-1 made RateScheme.save() run
    full_clean() on create, which correctly rejects 'flat_fee' on the LIVE
    model now — but the real migration never hits that path, since its
    ServicePrice class has no full_clean-calling save() at all. Mirror that
    exactly via save_base(raw=True) (the same bypass Model.save_base uses
    for fixture loading) rather than weakening the live model's real
    invariant just to keep this live-model stand-in test passing."""
    class objects:
        @staticmethod
        def create(**kwargs):
            obj = RateScheme(**kwargs)
            obj.save_base(raw=True, force_insert=True)
            return obj


class FlatFeeReframeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        # Literal 'flat_fee' (not RateScheme.FLAT_FEE — that constant is gone):
        # this exercises the historical migration helper, which still queries the
        # raw 'flat_fee' string. 'flat_fee' is no longer a valid choice in
        # ALGORITHM_CHOICES, and save() now runs full_clean() on create too,
        # so a plain .create() can't plant it directly. Create with a valid
        # algorithm, then bypass full_clean via QuerySet.update() to
        # simulate the pre-migration legacy row this helper cleans up.
        self.shared = RateScheme.objects.create(
            name='Flat Fee', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('0.00'), unit_label='each', accounting_category=self.ac,
        )
        RateScheme.objects.filter(pk=self.shared.pk).update(algorithm='flat_fee')
        self.shared.refresh_from_db()

    def _template(self, price):
        return ServiceItem.objects.create(
            template_name='t', rate_scheme=self.shared,
            default_active_modifiers={'flat_fee_price': str(price)},
        )

    def test_mints_per_price_service_and_repoints(self):
        t1 = self._template('1.00')
        t2 = self._template('30.00')
        t3 = self._template('1.00')  # same price as t1 -> shares minted service
        worklist = reframe_flat_fee_prices(
            _BareCreateProxy, _EmptyModel, _EmptyModel, ServiceItem, fk_field='rate_scheme')
        t1.refresh_from_db(); t2.refresh_from_db(); t3.refresh_from_db()
        self.assertEqual(t1.rate_scheme.rate, Decimal('1.00'))
        self.assertEqual(t2.rate_scheme.rate, Decimal('30.00'))
        self.assertEqual(t1.rate_scheme_id, t3.rate_scheme_id)
        self.assertNotEqual(t1.rate_scheme_id, t2.rate_scheme_id)
        self.assertEqual(t1.default_active_modifiers, [])
        self.assertEqual(worklist, [])

    def test_logs_unresolved_zero_price(self):
        bad = self._template('0')
        worklist = reframe_flat_fee_prices(
            _BareCreateProxy, _EmptyModel, _EmptyModel, ServiceItem, fk_field='rate_scheme')
        self.assertTrue(any(r[0] == 'ServiceItem' and r[1] == bad.pk for r in worklist))
