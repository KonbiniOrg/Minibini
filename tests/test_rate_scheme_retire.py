"""Task 4: RateScheme slimming — supersession out, is_active in.

RateSchemes are now freely editable presets: no frozen fields, no
supersession chain. A Task stamps its own permanent copy of the preset's
money fields at creation time (task-owned-money Phase 1, Tasks 1-3), so
editing — or even deleting — a preset that already has stamped tasks can
never reprice or orphan them. ``is_active`` replaces the old
``replaced_by``/``replaced_at`` mechanism as the sole retirement signal
(read by the creation-time guard, Task 3's ``SchemeInactiveError``).

ServiceItem.rate_scheme is still a live, current-pricing pointer (PROTECT),
so a scheme referenced by a ServiceItem still can't be deleted.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory
from apps.core.services import ConfigurationService
from apps.estimates.models import ServiceItem
from apps.jobs.models import Job, RateScheme, Task


class RateSchemeRetireTestBase(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(code='X-rsr', name='X-rsr')
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-rsr@l.test',
        )
        biz = Business.objects.create(
            business_name='B-rsr', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-rsr', contact=contact)

    def _scheme(self, name='S-rsr', **overrides):
        fields = dict(
            name=name, algorithm=RateScheme.ENTERED_QTY, rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
        )
        fields.update(overrides)
        return RateScheme.objects.create(**fields)

    def _stamp_task(self, scheme, name='t'):
        task = Task(job=self.job, name=name)
        task.stamp_from_scheme(scheme)
        task.save()
        return task


class EditingReferencedPresetTest(RateSchemeRetireTestBase):
    def test_editing_referenced_preset_succeeds(self):
        scheme = self._scheme()
        task = self._stamp_task(scheme)
        scheme.rate = Decimal('99.00')
        scheme.save()  # must not raise
        scheme.refresh_from_db()
        self.assertEqual(scheme.rate, Decimal('99.00'))

    def test_editing_referenced_preset_does_not_touch_stamped_tasks(self):
        scheme = self._scheme()
        task = self._stamp_task(scheme)
        original_task_rate = task.rate
        scheme.rate = Decimal('999.00')
        scheme.save()
        task.refresh_from_db()
        self.assertEqual(task.rate, original_task_rate)
        self.assertEqual(task.rate, Decimal('10'))

    def test_update_rate_scheme_service_edits_referenced_scheme(self):
        scheme = self._scheme()
        self._stamp_task(scheme)
        ConfigurationService.update_rate_scheme(scheme, rate=Decimal('42.00'))
        scheme.refresh_from_db()
        self.assertEqual(scheme.rate, Decimal('42.00'))


class RetireFlagTest(RateSchemeRetireTestBase):
    def test_new_scheme_defaults_active(self):
        scheme = self._scheme()
        self.assertTrue(scheme.is_active)

    def test_retire_rate_scheme_flips_flag(self):
        scheme = self._scheme()
        ConfigurationService.retire_rate_scheme(scheme.pk)
        scheme.refresh_from_db()
        self.assertFalse(scheme.is_active)

    def test_reactivate_rate_scheme_flips_flag_back(self):
        scheme = self._scheme()
        ConfigurationService.retire_rate_scheme(scheme.pk)
        ConfigurationService.reactivate_rate_scheme(scheme.pk)
        scheme.refresh_from_db()
        self.assertTrue(scheme.is_active)

    def test_retire_does_not_touch_stamped_tasks(self):
        scheme = self._scheme()
        task = self._stamp_task(scheme)
        ConfigurationService.retire_rate_scheme(scheme.pk)
        task.refresh_from_db()
        self.assertEqual(task.rate, Decimal('10'))
        self.assertEqual(task.source_scheme_id, scheme.pk)


class DefaultRateSchemeGuardTest(RateSchemeRetireTestBase):
    """RM browser-testing fix: retire/delete of the current
    `default_rate_scheme` is rejected outright rather than silently
    clearing the Configuration key (see tests/test_api_rate_schemes.py for
    the API-level + PATCH-is_active-bypass coverage of the same guard)."""

    def test_retire_rejects_the_current_default(self):
        scheme = self._scheme()
        ConfigurationService.set('default_rate_scheme', str(scheme.pk))
        with self.assertRaises(ValidationError):
            ConfigurationService.retire_rate_scheme(scheme.pk)
        scheme.refresh_from_db()
        self.assertTrue(scheme.is_active)

    def test_delete_rejects_the_current_default(self):
        scheme = self._scheme()
        ConfigurationService.set('default_rate_scheme', str(scheme.pk))
        with self.assertRaises(ValidationError):
            ConfigurationService.delete_rate_scheme(scheme)
        self.assertTrue(RateScheme.objects.filter(pk=scheme.pk).exists())


class DeleteWithStampedTasksTest(RateSchemeRetireTestBase):
    def test_delete_scheme_with_stamped_tasks_succeeds(self):
        scheme = self._scheme()
        task = self._stamp_task(scheme)
        pk = scheme.pk
        ConfigurationService.delete_rate_scheme(scheme)
        self.assertFalse(RateScheme.objects.filter(pk=pk).exists())

    def test_delete_scheme_with_stamped_tasks_nulls_source_scheme(self):
        scheme = self._scheme()
        task = self._stamp_task(scheme)
        ConfigurationService.delete_rate_scheme(scheme)
        task.refresh_from_db()
        self.assertIsNone(task.source_scheme_id)
        # The task's own money is untouched — it's the price of record.
        self.assertEqual(task.rate, Decimal('10'))


class DeleteReferencedByServiceItemTest(RateSchemeRetireTestBase):
    def test_delete_scheme_referenced_by_service_item_raises_protected_error(self):
        scheme = self._scheme()
        ServiceItem.objects.create(
            template_name='SI-rsr', rate_scheme=scheme,
        )
        with self.assertRaises(ProtectedError):
            ConfigurationService.delete_rate_scheme(scheme)
        self.assertTrue(RateScheme.objects.filter(pk=scheme.pk).exists())


class IsReferencedAndReferenceCountsTest(RateSchemeRetireTestBase):
    def test_is_referenced_true_for_stamped_task(self):
        scheme = self._scheme()
        self._stamp_task(scheme)
        self.assertTrue(scheme.is_referenced())

    def test_is_referenced_true_for_service_item(self):
        scheme = self._scheme()
        ServiceItem.objects.create(template_name='SI-rsr2', rate_scheme=scheme)
        self.assertTrue(scheme.is_referenced())

    def test_is_referenced_false_when_untouched(self):
        scheme = self._scheme()
        self.assertFalse(scheme.is_referenced())

    def test_reference_counts_counts_stamped_tasks_and_service_items(self):
        scheme = self._scheme()
        self._stamp_task(scheme, name='t1')
        self._stamp_task(scheme, name='t2')
        ServiceItem.objects.create(template_name='SI-rsr3', rate_scheme=scheme)
        counts = scheme.reference_counts()
        self.assertEqual(counts['task_count'], 2)
        self.assertEqual(counts['service_item_count'], 1)


class SupersessionRemovedTest(RateSchemeRetireTestBase):
    """Supersede is gone everywhere server-side: no method, no fields."""

    def test_no_supersede_method(self):
        scheme = self._scheme()
        self.assertFalse(hasattr(scheme, 'supersede'))

    def test_no_replaced_by_field(self):
        scheme = self._scheme()
        self.assertFalse(hasattr(scheme, 'replaced_by'))

    def test_no_replaced_at_field(self):
        scheme = self._scheme()
        self.assertFalse(hasattr(scheme, 'replaced_at'))

    def test_no_supersede_rate_scheme_service_method(self):
        self.assertFalse(hasattr(ConfigurationService, 'supersede_rate_scheme'))
