from decimal import Decimal
from unittest.mock import MagicMock, patch
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme
from apps.estimates.models import ServiceItem
from apps.core.models import AccountingCategory


class RateSchemeModelTest(BaseTestCase):
    """Test creation of RateScheme instances for all 3 algorithm types."""

    def setUp(self):
        super().setUp()
        self.ac = AccountingCategory.objects.create(code='RSM', name='RSM')

    def test_create_elapsed_time_scheme(self):
        scheme = RateScheme.objects.create(
            name='Standard Labor',
            description='Billed per hour worked',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
            accounting_category=self.ac,
        )
        self.assertEqual(scheme.name, 'Standard Labor')
        self.assertEqual(scheme.algorithm, RateScheme.ELAPSED_TIME)
        self.assertEqual(scheme.rate, Decimal('75.00'))
        self.assertEqual(scheme.unit_label, 'hour')
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
            modifiers=modifiers,
            accounting_category=self.ac,
        )
        self.assertEqual(scheme.algorithm, RateScheme.ENTERED_QTY)
        self.assertEqual(len(scheme.modifiers), 2)
        self.assertEqual(scheme.modifiers[0]['key'], 'messy')

    def test_name_unique(self):
        RateScheme.objects.create(
            name='Unique Scheme',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='job',
            accounting_category=self.ac,
        )
        # save() now runs full_clean() on create too, and full_clean()
        # includes validate_unique() — the duplicate name is now caught
        # there (ValidationError) before the INSERT ever reaches the DB's
        # unique constraint (IntegrityError). The earlier catch is the
        # better contract: it's what the API's error-response layer
        # actually renders as a field-keyed 400.
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            RateScheme.objects.create(
                name='Unique Scheme',
                algorithm=RateScheme.ENTERED_QTY,
                rate=Decimal('10.00'),
                unit_label='job',
                accounting_category=self.ac,
            )
        self.assertIn('name', ctx.exception.message_dict)


class RateSchemeComputeTest(BaseTestCase):
    """Test compute methods on RateScheme."""

    def setUp(self):
        super().setUp()
        self.ac = AccountingCategory.objects.create(code='RSC', name='RSC')
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
        self.flat_scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'),
            unit_label='job',
            accounting_category=self.ac,
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
        # 30 sq ft × $4.00 = $120.00
        result = self.scheme.compute_charge(Decimal('30'))
        self.assertEqual(result, Decimal('120.00'))

    def test_compute_charge_with_modifiers(self):
        # 30 × $4.60 = $138.00
        result = self.scheme.compute_charge(Decimal('30'), active_modifiers=['messy', 'doublestick'])
        self.assertEqual(result, Decimal('138.00'))

    def test_effective_rate_quantizes_to_cents(self):
        # A percentage modifier on a rate carrying cents yields a non-terminating
        # / >2-place product (99.99 × 1.05 = 104.9895). effective_rate is a
        # per-unit money value that becomes a line item price (max 2 decimals),
        # so it must trim to cents at the source — not just at scattered callers.
        scheme = RateScheme.objects.create(
            name='Cents Rate',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.99'),
            unit_label='sq ft',
            modifiers=[{'key': 'surcharge', 'label': 'Surcharge', 'percent': 5}],
            accounting_category=self.ac,
        )
        result = scheme.effective_rate(active_modifiers=['surcharge'])
        self.assertEqual(result, Decimal('104.99'))
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_get_actual_qty_elapsed_time(self):
        from datetime import datetime, timedelta
        from django.utils import timezone as tz

        labor_scheme = RateScheme.objects.create(
            name='Labor Rate',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
            accounting_category=self.ac,
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

    def test_get_actual_qty_elapsed_time_quantizes_to_two_places(self):
        """Hours derived from bleps are quantized to 2 decimal places. A raw
        seconds/3600 division produces a non-terminating decimal (~28 digits)
        that overflows the line item qty field (max_digits=10)."""
        from datetime import timedelta

        labor_scheme = RateScheme.objects.create(
            name='Labor Rate Quantized',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
            accounting_category=self.ac,
        )

        blep = MagicMock()
        blep.elapsed = timedelta(seconds=3700)  # 1.0277... hours
        task = MagicMock()
        task.blep_set.all.return_value = [blep]

        result = labor_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('1.03'))
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_get_actual_qty_entered_qty(self):
        task = MagicMock()
        task.actual_qty = Decimal('25')

        result = self.scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('25'))

    def test_get_modifier_inputs(self):
        result = self.scheme.get_modifier_inputs()
        self.assertEqual(result, self.modifiers)
        # Should be a copy (list), not the same object reference check not required
        self.assertIsInstance(result, list)


class ServiceItemRateSchemeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ac = AccountingCategory.objects.create(code='TTRS', name='TTRS')
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor Test',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
            accounting_category=self.ac,
        )

    def test_service_item_with_rate_scheme(self):
        tmpl = ServiceItem.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
        )
        self.assertEqual(tmpl.rate_scheme, self.scheme)
        self.assertEqual(tmpl.default_active_modifiers, ['messy'])

    def test_service_item_without_rate_scheme_rejected(self):
        """Phase B: rate_scheme is NOT NULL."""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ServiceItem.objects.create(template_name='Legacy Template')

    def test_service_item_api_includes_rate_scheme(self):
        tmpl = ServiceItem.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.first()
        self.client.force_login(user)

        resp = self.client.get(f'/api/service-items/{tmpl.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['rate_scheme'], self.scheme.pk)
        self.assertEqual(data['default_active_modifiers'], ['messy'])


class RateSchemeIsReferencedTest(BaseTestCase):
    fixtures = []  # clean slate

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def test_unreferenced_scheme_is_not_referenced(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='unref', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.assertFalse(s.is_referenced())

    def test_scheme_with_task_is_referenced(self):
        """Phase B: is_referenced checks Task.rate_scheme, not TaskCharge."""
        from apps.jobs.models import RateScheme, Task, Job
        from apps.contacts.models import Contact, Business
        contact = Contact.objects.create(first_name='F', last_name='L', email='f2@l.test')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J2', contact=contact)
        s = RateScheme.objects.create(
            name='refTC', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        Task.objects.create(job=job, name='t', source_scheme=s)
        self.assertTrue(s.is_referenced())

    def test_scheme_with_taskTemplate_is_referenced(self):
        from apps.jobs.models import RateScheme
        from apps.estimates.models import ServiceItem
        s = RateScheme.objects.create(
            name='refTT', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        ServiceItem.objects.create(
            template_name='tt', rate_scheme=s,
        )
        self.assertTrue(s.is_referenced())


class RateSchemeReferencedEditableTest(BaseTestCase):
    """Task 4: RateSchemes are freely editable presets — no frozen fields,
    no supersession. A referenced scheme (stamped tasks and/or a ServiceItem
    pointing at it) edits exactly like an unreferenced one; the stamped
    tasks already carry their own permanent copy of the money fields, so
    editing the preset can never reprice them. See
    tests/test_rate_scheme_retire.py for the fuller retire/delete coverage."""
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def _make_referenced_scheme(self):
        from apps.jobs.models import RateScheme, Task, Job
        from apps.contacts.models import Contact, Business
        # NOTE: real model schema requires Business.business_name + default_contact
        # FK, and Contact.email. Build the pair in the order: Contact first
        # (without business), then Business with default_contact, then attach
        # business back to contact and save.
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f@l.test',
        )
        biz = Business.objects.create(
            business_name='B-frz', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-frz', contact=contact)
        s = RateScheme.objects.create(
            name='S-frz', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        Task.objects.create(job=job, name='t', source_scheme=s)
        return s

    def test_unreferenced_scheme_can_be_edited(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='U-frz', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        s.rate = Decimal('2')
        s.save()  # no exception
        s.refresh_from_db()
        self.assertEqual(s.rate, Decimal('2'))

    def test_referenced_scheme_can_be_edited(self):
        s = self._make_referenced_scheme()
        s.rate = Decimal('99')
        s.full_clean()  # must not raise
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.rate, Decimal('99'))


class RateSchemeRequiresACTest(BaseTestCase):
    fixtures = []

    def test_full_clean_rejects_missing_ac(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import RateScheme
        s = RateScheme(
            name='NoAC', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea',
        )
        with self.assertRaises(ValidationError) as cm:
            s.full_clean()
        self.assertIn('accounting_category', cm.exception.message_dict)


class RateSchemeIsReferencedTaskTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='BIRT', name='BIRT')

    def test_is_referenced_counts_task_not_taskcharge(self):
        """After Phase B, RateScheme.is_referenced checks Task instead of TaskCharge."""
        from apps.jobs.models import Task, RateScheme, Job
        from apps.contacts.models import Contact, Business

        scheme = RateScheme.objects.create(
            name='Test B2', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='job',
            accounting_category=self.ac,
        )
        self.assertFalse(scheme.is_referenced())

        # Create job + contact (mind the Business/Contact circular FK)
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='X-B2', default_contact=contact)
        contact.business = biz
        contact.save()
        job = Job.objects.create(
            job_number='JOB-T1-B2', contact=contact, status=Job.STATUS_DRAFT,
        )
        Task.objects.create(job=job, name='Direct', source_scheme=scheme)

        self.assertTrue(scheme.is_referenced())
        counts = scheme.reference_counts()
        self.assertEqual(counts['task_count'], 1)
        self.assertNotIn('task_charge_count', counts)


class RateSchemePercentageAlgorithmTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        self.ac = AccountingCategory.objects.create(code='PCT', name='PCT')

    def test_percentage_allows_negative_rate(self):
        from apps.jobs.models import RateScheme
        svc = RateScheme(
            name='Discount', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('-10.00'), unit_label='%', accounting_category=self.ac,
        )
        svc.full_clean()  # must not raise

    def test_non_percentage_rejects_negative_rate(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import RateScheme
        svc = RateScheme(
            name='Bad', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('-5.00'), unit_label='hour', accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError):
            svc.full_clean()

    def test_get_actual_qty_rejects_percentage(self):
        from apps.jobs.models import RateScheme
        svc = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%', accounting_category=self.ac,
        )
        with self.assertRaises(ValueError):
            svc.get_actual_qty(object())

    def test_effective_rate_rejects_percentage(self):
        # Mirrors the get_actual_qty guard: percentage services compute at the
        # document layer, never as a per-unit rate.
        from apps.jobs.models import RateScheme
        svc = RateScheme.objects.create(
            name='Rush ER', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%', accounting_category=self.ac,
        )
        with self.assertRaises(ValueError):
            svc.effective_rate()
