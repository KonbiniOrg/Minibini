from decimal import Decimal
from datetime import timedelta
from django.db import IntegrityError
from django.utils import timezone
from tests.base import BaseTestCase
from apps.jobs.models import Task, PlanTask, RateScheme, Blep
from apps.core.models import AccountingCategory


class TaskChargeModelTest(BaseTestCase):
    """Test creation and basic behavior of TaskCharge."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.get(pk=1)
        self.ac = AccountingCategory.objects.get(pk=901)
        self.modifiers = [
            {'key': 'messy', 'label': 'Messy job', 'percent': 10},
            {'key': 'doublestick', 'label': 'Double-stick tape', 'percent': 5},
        ]
        self.scheme = RateScheme.objects.create(
            name='Vinyl Application',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='sq ft',
            modifiers=self.modifiers,
            accounting_category=self.ac,
        )

    def test_create_task_charge(self):
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy', 'doublestick'],
            actuals={'qty': 30},
        )
        self.assertEqual(charge.task, self.task)
        self.assertEqual(charge.rate_scheme, self.scheme)
        self.assertEqual(charge.active_modifiers, ['messy', 'doublestick'])
        self.assertEqual(charge.actuals, {'qty': 30})

    def test_task_charge_compute(self):
        """entered_qty: 30 sq ft × $4.60 effective = $138"""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy', 'doublestick'],
            actuals={'qty': 30},
        )
        result = charge.compute()
        self.assertEqual(result, Decimal('138.00'))

    def test_task_charge_effective_rate(self):
        """With one modifier: $4.00 + 10% = $4.40"""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            actuals={},
        )
        result = charge.effective_rate()
        self.assertEqual(result, Decimal('4.40'))

    def test_task_charge_has_actuals_false(self):
        """No actuals entered for entered_qty scheme → has_actuals() is False."""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={},
        )
        self.assertFalse(charge.has_actuals())

    def test_task_charge_has_actuals_true(self):
        """Actuals present for entered_qty scheme → has_actuals() is True."""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={'qty': 10},
        )
        self.assertTrue(charge.has_actuals())

    def test_task_charge_one_to_one(self):
        """Second TaskCharge on same task raises an error."""
        from apps.jobs.models import TaskCharge
        TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={},
        )
        with self.assertRaises(IntegrityError):
            TaskCharge.objects.create(
                task=self.task,
                rate_scheme=self.scheme,
                active_modifiers=[],
                actuals={},
            )

    def test_task_charge_reverse_access(self):
        """task.charge.actuals works via reverse relation."""
        from apps.jobs.models import TaskCharge
        TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={'qty': 42},
        )
        task = Task.objects.get(pk=self.task.pk)
        self.assertEqual(task.charge.actuals, {'qty': 42})

    def test_get_actual_qty_returns_decimal_when_actuals_qty_is_string(self):
        """Carry-over stores qty as str(Decimal); compute() must still work."""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={'qty': '2.5'},  # string, not number — what carry-over writes
        )
        # The bug: compute() raised TypeError before the fix because
        # str * Decimal is invalid.
        self.assertEqual(charge.compute(), Decimal('10.00'))  # 2.5 × $4.00


class TaskChargeElapsedTimeTest(BaseTestCase):
    """Test compute() for elapsed_time algorithm via real Bleps."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.get(pk=1)
        self.ac = AccountingCategory.objects.get(pk=901)
        self.scheme = RateScheme.objects.create(
            name='Labor Rate',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
            accounting_category=self.ac,
        )
        # Create 2 Bleps totaling 2 hours
        now = timezone.now()
        from datetime import timedelta
        self.blep1 = Blep.objects.create(
            task=self.task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=now - timedelta(hours=1),
            end_time=now,
        )

    def test_compute_from_bleps(self):
        """elapsed_time: 2 hours × $45/hr = $90"""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={},
        )
        result = charge.compute()
        # Allow slight floating point tolerance (2 hours = $90.00)
        self.assertAlmostEqual(float(result), 90.0, places=1)


class TaskChargeFlatFeeTest(BaseTestCase):
    """Test compute() for flat_fee algorithm."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.get(pk=1)
        self.ac = AccountingCategory.objects.get(pk=901)
        self.scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
            accounting_category=self.ac,
        )

    def test_flat_fee_compute(self):
        """flat_fee: 1 × $50 = $50"""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={},
        )
        result = charge.compute()
        self.assertEqual(result, Decimal('50.00'))

    def test_flat_fee_has_actuals_always_true(self):
        """flat_fee never requires manual actuals → has_actuals() is True."""
        from apps.jobs.models import TaskCharge
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=[],
            actuals={},
        )
        self.assertTrue(charge.has_actuals())



class EstWorkerTimeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        from apps.jobs.models import TaskCharge
        ac = AccountingCategory.objects.get(pk=901)
        scheme = RateScheme.objects.create(
            name='EWT scheme', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='ea',
            accounting_category=ac,
        )
        TaskCharge.objects.get_or_create(
            task=Task.objects.get(pk=1),
            defaults={'rate_scheme': scheme, 'active_modifiers': [], 'actuals': {}},
        )

    def test_task_has_est_worker_time(self):
        task = Task.objects.get(pk=1)
        self.assertIsNone(task.est_worker_time)

    def test_task_set_est_worker_time(self):
        task = Task.objects.get(pk=1)
        task.est_worker_time = timedelta(hours=2, minutes=30)
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=2, minutes=30))

    def test_plan_task_has_est_worker_time(self):
        pt = PlanTask.objects.first()
        if pt is None:
            self.skipTest('No PlanTask in fixtures')
        self.assertIsNone(pt.est_worker_time)

    def test_task_has_source_template(self):
        task = Task.objects.get(pk=1)
        self.assertIsNone(task.source_template)

    def test_task_set_source_template(self):
        from apps.estimates.models import TaskTemplate
        tmpl = TaskTemplate.objects.first()
        task = Task.objects.get(pk=1)
        task.source_template = tmpl
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.source_template, tmpl)
