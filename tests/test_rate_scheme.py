from decimal import Decimal
from unittest.mock import MagicMock, patch
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme
from apps.estimates.models import TaskTemplate
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

    def test_create_flat_fee_scheme(self):
        scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
            accounting_category=self.ac,
        )
        self.assertEqual(scheme.algorithm, RateScheme.FLAT_FEE)
        self.assertEqual(str(scheme), 'Setup Fee')

    def test_name_unique(self):
        RateScheme.objects.create(
            name='Unique Scheme',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('10.00'),
            unit_label='job',
            accounting_category=self.ac,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            RateScheme.objects.create(
                name='Unique Scheme',
                algorithm=RateScheme.FLAT_FEE,
                rate=Decimal('10.00'),
                unit_label='job',
                accounting_category=self.ac,
            )


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
            algorithm=RateScheme.FLAT_FEE,
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

    def test_get_actual_qty_flat_fee_uses_est_qty(self):
        # flat_fee now bills a fixed unit price x estimated quantity.
        task = MagicMock()
        task.est_qty = Decimal('12')
        result = self.flat_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('12'))

    def test_get_actual_qty_flat_fee_falls_back_to_one(self):
        # A genuine one-off fee carries no quantity; fall back to 1.
        task = MagicMock()
        task.est_qty = None
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
        self.ac = AccountingCategory.objects.create(code='TTRS', name='TTRS')
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor Test',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
            accounting_category=self.ac,
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

    def test_task_template_without_rate_scheme_rejected(self):
        """Phase B: rate_scheme and default_billable_qty are NOT NULL."""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            TaskTemplate.objects.create(template_name='Legacy Template')

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
            est_qty=Decimal('1'),
        )
        self.assertTrue(s.is_referenced())

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
            name='refTC', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        Task.objects.create(job=job, name='t', rate_scheme=s)
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
        # Old row gets the (v1) suffix even though the new row was renamed.
        self.assertEqual(old.name, 'Old (v1)')
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


class RateSchemeVersionedSupersedeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='V', name='V')

    def test_first_supersede_renames_old_to_v1_and_new_keeps_name(self):
        """
        Calling supersede() with no name override:
          - old row is renamed to "<orig> (v1)"
          - new row is created with the original name
          - the unique constraint on name is preserved at the DB level.
        """
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Standard Labor', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
        )
        new = old.supersede()
        old.refresh_from_db()
        self.assertEqual(old.name, 'Standard Labor (v1)')
        self.assertEqual(new.name, 'Standard Labor')
        self.assertEqual(old.replaced_by_id, new.pk)
        # Name stays globally unique — verify the row count for each name is 1.
        self.assertEqual(
            RateScheme.objects.filter(name='Standard Labor').count(), 1,
        )
        self.assertEqual(
            RateScheme.objects.filter(name='Standard Labor (v1)').count(), 1,
        )

    def test_second_supersede_increments_to_v2(self):
        """
        Superseding a chain of length 1 (i.e. there's already a (v1)
        predecessor) tags the next retired row (v2).
        """
        from apps.jobs.models import RateScheme
        a = RateScheme.objects.create(
            name='Job A', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        b = a.supersede()  # a -> "Job A (v1)", b -> "Job A"
        c = b.supersede()  # b -> "Job A (v2)", c -> "Job A"
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.name, 'Job A (v1)')
        self.assertEqual(b.name, 'Job A (v2)')
        self.assertEqual(c.name, 'Job A')
        self.assertEqual(a.replaced_by_id, b.pk)
        self.assertEqual(b.replaced_by_id, c.pk)
        self.assertIsNone(c.replaced_by_id)

    def test_supersede_with_name_override_renames_old_anyway(self):
        """
        Even when the caller gives the new scheme a different name, the
        old row still gets the (vN) suffix — consistency wins over
        cosmetics, per spec.
        """
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Hourly', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        new = old.supersede(name='Premium Hourly')
        old.refresh_from_db()
        self.assertEqual(old.name, 'Hourly (v1)')
        self.assertEqual(new.name, 'Premium Hourly')

    def test_supersede_appends_suffix_to_already_suffixed_name(self):
        """
        If a row was hand-created (or otherwise ended up) with a name
        that already looks like "...(v1)", a supersede operation just
        appends another suffix. No smart-stripping; the chain history
        is the source of truth, the suffix is a label.
        """
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Quirky (v1)', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        new = old.supersede()
        old.refresh_from_db()
        self.assertEqual(old.name, 'Quirky (v1) (v1)')
        self.assertEqual(new.name, 'Quirky (v1)')

    def test_supersede_does_not_share_modifiers_list_with_new_scheme(self):
        """
        Belt-and-braces: confirm the modifier-list copy still doesn't
        alias after the algorithm change. (Mirrors a pre-existing test
        in RateSchemeSupersedeMethodTest, but worth keeping for the
        new code path.)
        """
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='Mod', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
            modifiers=[{'key': 'm1', 'label': 'M1', 'percent': 10}],
        )
        new = old.supersede()
        new.modifiers.append({'key': 'm2', 'label': 'M2', 'percent': 5})
        old.refresh_from_db()
        self.assertEqual(len(old.modifiers), 1)


class RateSchemeFreezeOnReferenceTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def _make_referenced_scheme(self):
        from apps.jobs.models import RateScheme, PlanTask, Job
        from apps.estimates.models import EstWorksheet
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
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='S-frz', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            est_qty=Decimal('1'),
        )
        return s

    def test_unreferenced_scheme_can_be_edited(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='U-frz', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        s.rate = Decimal('2')
        s.save()  # no exception
        s.refresh_from_db()
        self.assertEqual(s.rate, Decimal('2'))

    def test_referenced_scheme_rejects_edits(self):
        from django.core.exceptions import ValidationError
        s = self._make_referenced_scheme()
        s.rate = Decimal('99')
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_supersede_still_works_on_referenced_scheme(self):
        s = self._make_referenced_scheme()
        # Pass a new name to avoid the unique-name constraint on RateScheme.name.
        new = s.supersede(name='S-frz-v2', rate=Decimal('99'))
        s.refresh_from_db()
        self.assertEqual(s.replaced_by, new)


class RateSchemeRequiresACTest(BaseTestCase):
    fixtures = []

    def test_full_clean_rejects_missing_ac(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import RateScheme
        s = RateScheme(
            name='NoAC', algorithm='flat_fee', rate=Decimal('1'),
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
            name='Test B2', algorithm=RateScheme.FLAT_FEE,
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
        Task.objects.create(job=job, name='Direct', rate_scheme=scheme)

        self.assertTrue(scheme.is_referenced())
        counts = scheme.reference_counts()
        self.assertEqual(counts['task_count'], 1)
        self.assertNotIn('task_charge_count', counts)
