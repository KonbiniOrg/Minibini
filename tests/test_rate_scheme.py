from decimal import Decimal
from unittest.mock import MagicMock, patch
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme
from apps.estimates.models import TaskTemplate
from apps.core.models import AccountingCategory


class RateSchemeModelTest(BaseTestCase):
    """Test creation of RateScheme instances for all 3 algorithm types."""

    def test_create_elapsed_time_scheme(self):
        scheme = RateScheme.objects.create(
            name='Standard Labor',
            description='Billed per hour worked',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
        )
        self.assertEqual(scheme.name, 'Standard Labor')
        self.assertEqual(scheme.algorithm, RateScheme.ELAPSED_TIME)
        self.assertEqual(scheme.rate, Decimal('75.00'))
        self.assertEqual(scheme.unit_label, 'hour')
        self.assertIsNone(scheme.minimum_charge)
        self.assertEqual(scheme.modifiers, [])

    def test_create_entered_qty_scheme_with_modifiers(self):
        modifiers = [
            {'key': 'messy', 'label': 'Messy job', 'percent': 10},
            {'key': 'doublestick', 'label': 'Double-stick tape', 'percent': 5},
        ]
        scheme = RateScheme.objects.create(
            name='Vinyl Application',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='sq ft',
            minimum_charge=Decimal('20.00'),
            modifiers=modifiers,
        )
        self.assertEqual(scheme.algorithm, RateScheme.ENTERED_QTY)
        self.assertEqual(len(scheme.modifiers), 2)
        self.assertEqual(scheme.modifiers[0]['key'], 'messy')
        self.assertEqual(scheme.minimum_charge, Decimal('20.00'))

    def test_create_flat_fee_scheme(self):
        scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )
        self.assertEqual(scheme.algorithm, RateScheme.FLAT_FEE)
        self.assertEqual(str(scheme), 'Setup Fee')

    def test_name_unique(self):
        RateScheme.objects.create(
            name='Unique Scheme',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('10.00'),
            unit_label='job',
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            RateScheme.objects.create(
                name='Unique Scheme',
                algorithm=RateScheme.FLAT_FEE,
                rate=Decimal('10.00'),
                unit_label='job',
            )


class RateSchemeComputeTest(BaseTestCase):
    """Test compute methods on RateScheme."""

    def setUp(self):
        super().setUp()
        self.modifiers = [
            {'key': 'messy', 'label': 'Messy job', 'percent': 10},
            {'key': 'doublestick', 'label': 'Double-stick tape', 'percent': 5},
        ]
        self.scheme = RateScheme.objects.create(
            name='Vinyl Application',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='sq ft',
            minimum_charge=Decimal('20.00'),
            modifiers=self.modifiers,
        )
        self.flat_scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )

    def test_effective_rate_no_modifiers(self):
        result = self.scheme.effective_rate()
        self.assertEqual(result, Decimal('4.00'))

    def test_effective_rate_one_modifier(self):
        # $4.00 + 10% = $4.40
        result = self.scheme.effective_rate(active_modifiers=['messy'])
        self.assertEqual(result, Decimal('4.40'))

    def test_effective_rate_stacking_modifiers(self):
        # $4.00 + 10% + 5% = $4.00 * 1.15 = $4.60
        result = self.scheme.effective_rate(active_modifiers=['messy', 'doublestick'])
        self.assertEqual(result, Decimal('4.60'))

    def test_compute_charge_basic(self):
        # 30 sq ft × $4.00 = $120.00 (above minimum of $20)
        result = self.scheme.compute_charge(Decimal('30'))
        self.assertEqual(result, Decimal('120.00'))

    def test_compute_charge_with_modifiers(self):
        # 30 × $4.60 = $138.00
        result = self.scheme.compute_charge(Decimal('30'), active_modifiers=['messy', 'doublestick'])
        self.assertEqual(result, Decimal('138.00'))

    def test_compute_charge_minimum_applies(self):
        # 1 × $4.00 = $4.00, but minimum is $20.00
        result = self.scheme.compute_charge(Decimal('1'))
        self.assertEqual(result, Decimal('20.00'))

    def test_compute_charge_minimum_not_applied_when_exceeded(self):
        # 10 × $4.00 = $40.00, minimum is $20.00 → $40.00
        result = self.scheme.compute_charge(Decimal('10'))
        self.assertEqual(result, Decimal('40.00'))

    def test_flat_fee_effective_rate(self):
        result = self.flat_scheme.effective_rate()
        self.assertEqual(result, Decimal('50.00'))

    def test_flat_fee_compute_charge(self):
        result = self.flat_scheme.compute_charge(Decimal('1'))
        self.assertEqual(result, Decimal('50.00'))

    def test_get_actual_qty_elapsed_time(self):
        from datetime import datetime, timedelta
        from django.utils import timezone as tz

        labor_scheme = RateScheme.objects.create(
            name='Labor Rate',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
        )

        # Mock a task with bleps totaling 2 hours (7200 seconds)
        blep1 = MagicMock()
        blep1.elapsed = timedelta(seconds=3600)  # 1 hour
        blep2 = MagicMock()
        blep2.elapsed = timedelta(seconds=3600)  # 1 hour

        task = MagicMock()
        task.blep_set.all.return_value = [blep1, blep2]

        result = labor_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('2'))

    def test_get_actual_qty_entered_qty(self):
        charge = MagicMock()
        charge.actuals = {'qty': 25}
        task = MagicMock()
        task.charge = charge

        result = self.scheme.get_actual_qty(task)
        self.assertEqual(result, 25)

    def test_get_actual_qty_flat_fee(self):
        task = MagicMock()
        result = self.flat_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('1'))

    def test_get_modifier_inputs(self):
        result = self.scheme.get_modifier_inputs()
        self.assertEqual(result, self.modifiers)
        # Should be a copy (list), not the same object reference check not required
        self.assertIsInstance(result, list)


class TaskTemplateRateSchemeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor Test',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
        )

    def test_task_template_with_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
            default_billable_qty=Decimal('4.00'),
        )
        self.assertEqual(tmpl.rate_scheme, self.scheme)
        self.assertEqual(tmpl.default_active_modifiers, ['messy'])
        self.assertEqual(tmpl.default_billable_qty, Decimal('4.00'))

    def test_task_template_without_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(template_name='Legacy Template')
        self.assertIsNone(tmpl.rate_scheme)
        self.assertEqual(tmpl.default_active_modifiers, [])
        self.assertIsNone(tmpl.default_billable_qty)

    def test_task_template_api_includes_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
            default_billable_qty=Decimal('4.00'),
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.first()
        self.client.force_login(user)

        resp = self.client.get(f'/api/task-templates/{tmpl.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['rate_scheme'], self.scheme.pk)
        self.assertEqual(data['default_active_modifiers'], ['messy'])
        self.assertEqual(data['default_billable_qty'], '4.00')


class RateSchemeSupersessionFieldsTest(BaseTestCase):
    def test_scheme_has_replaced_by_and_replaced_at_fields(self):
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.first()
        scheme = RateScheme.objects.create(
            name='X', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=ac,
        )
        # New nullable fields exist with sensible defaults
        self.assertIsNone(scheme.replaced_by)
        self.assertIsNone(scheme.replaced_at)


class RateSchemeIsReferencedTest(BaseTestCase):
    fixtures = []  # clean slate

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def test_unreferenced_scheme_is_not_referenced(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='unref', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.assertFalse(s.is_referenced())

    def test_scheme_with_planTask_is_referenced(self):
        from apps.jobs.models import RateScheme, PlanTask
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact, Business
        from apps.jobs.models import Job
        contact = Contact.objects.create(first_name='F', last_name='L', email='f@l.test')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J1', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='ref', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            estimated_billable_qty=Decimal('1'),
        )
        self.assertTrue(s.is_referenced())

    def test_scheme_with_taskCharge_is_referenced(self):
        from apps.jobs.models import RateScheme, Task, TaskCharge, Job
        from apps.contacts.models import Contact, Business
        contact = Contact.objects.create(first_name='F', last_name='L', email='f2@l.test')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J2', contact=contact)
        s = RateScheme.objects.create(
            name='refTC', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        t = Task.objects.create(job=job, name='t')
        TaskCharge.objects.create(task=t, rate_scheme=s)
        self.assertTrue(s.is_referenced())

    def test_scheme_with_taskTemplate_is_referenced(self):
        from apps.jobs.models import RateScheme
        from apps.estimates.models import TaskTemplate
        s = RateScheme.objects.create(
            name='refTT', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        TaskTemplate.objects.create(
            template_name='tt', rate_scheme=s,
            default_billable_qty=Decimal('1'),
        )
        self.assertTrue(s.is_referenced())


class RateSchemeSupersedeMethodTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def test_supersede_creates_new_scheme_and_links_old(self):
        from apps.jobs.models import RateScheme
        from django.utils import timezone
        old = RateScheme.objects.create(
            name='Old', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
        )
        before = timezone.now()
        new = old.supersede(name='New', rate=Decimal('15'))
        old.refresh_from_db()
        self.assertEqual(old.replaced_by, new)
        self.assertGreaterEqual(old.replaced_at, before)
        self.assertEqual(new.name, 'New')
        self.assertEqual(new.rate, Decimal('15'))
        # New scheme inherits non-overridden fields
        self.assertEqual(new.algorithm, 'flat_fee')
        self.assertEqual(new.unit_label, 'ea')
        self.assertEqual(new.accounting_category, self.ac)
        self.assertIsNone(new.replaced_by)
        self.assertIsNone(new.replaced_at)

    def test_supersede_on_already_superseded_raises(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Old', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
        )
        old.supersede(name='V2')
        with self.assertRaises(ValueError):
            old.supersede(name='V3')

    def test_supersede_does_not_share_modifiers_list_with_new_scheme(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Old', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
            modifiers=[{'key': 'm1', 'label': 'M1', 'percent': 10}],
        )
        new = old.supersede(name='V2')
        new.modifiers.append({'key': 'm2', 'label': 'M2', 'percent': 5})
        self.assertEqual(len(old.modifiers), 1)
