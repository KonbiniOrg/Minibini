"""Task-owned money Phase 1, Task 3: Task.stamp_from_scheme and the
creation-time gate (SchemeInactiveError / allow_inactive_scheme).

Stamping copies a RateScheme preset's money fields onto the Task at
creation time (qty_source, rate, unit_label, accounting_category, resolved
active_modifiers snapshots, source_scheme provenance). Once stamped, the
task's own fields are the price of record — later edits to the preset must
never reprice an already-stamped task.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.jobs.models import Job, RateScheme, Task


class TaskStampingTestBase(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(code='X-stamp', name='X-stamp')
        self.scheme = RateScheme.objects.create(
            name='Hourly-stamp', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('95.00'), unit_label='hour',
            modifiers=[
                {'key': 'rush', 'label': 'Rush', 'percent': 20},
                {'key': 'weekend', 'label': 'Weekend', 'percent': 10},
            ],
            accounting_category=self.ac,
        )
        contact = Contact.objects.create(
            first_name='S', last_name='T', email='s-stamp@t.test',
        )
        self.job = Job.objects.create(job_number='JOB-stamp-1', contact=contact)


class StampFromSchemeTest(TaskStampingTestBase):
    def test_stamp_copies_all_five_aspects_plus_source_scheme(self):
        task = Task(job=self.job, name='X')
        task.stamp_from_scheme(self.scheme, modifier_keys=['rush'])
        self.assertEqual(task.qty_source, RateScheme.ENTERED_QTY)
        self.assertEqual(task.rate, Decimal('95.00'))
        self.assertEqual(task.unit_label, 'hour')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.scheme)
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'rush', 'label': 'Rush', 'percent': 20}],
        )

    def test_stamp_no_modifier_keys_yields_empty_active_modifiers(self):
        task = Task(job=self.job, name='X')
        task.stamp_from_scheme(self.scheme)
        self.assertEqual(task.active_modifiers, [])

    def test_stamp_resolves_multiple_modifier_keys(self):
        task = Task(job=self.job, name='X')
        task.stamp_from_scheme(self.scheme, modifier_keys=['rush', 'weekend'])
        self.assertEqual(len(task.active_modifiers), 2)
        keys = {m['key'] for m in task.active_modifiers}
        self.assertEqual(keys, {'rush', 'weekend'})

    def test_stamp_ignores_unknown_modifier_keys(self):
        task = Task(job=self.job, name='X')
        task.stamp_from_scheme(self.scheme, modifier_keys=['not-a-real-key'])
        self.assertEqual(task.active_modifiers, [])

    def test_stamp_percentage_scheme_raises_value_error(self):
        pct_scheme = RateScheme.objects.create(
            name='Rush surcharge-stamp', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='none',
            accounting_category=self.ac,
        )
        task = Task(job=self.job, name='X')
        with self.assertRaises(ValueError):
            task.stamp_from_scheme(pct_scheme)

    def test_stamp_then_edit_preset_does_not_reprice(self):
        task = Task.objects.create(job=self.job, name='X', accounting_category=self.ac)
        task.stamp_from_scheme(self.scheme, modifier_keys=['rush'])
        task.save()
        # Editing a referenced scheme is freely allowed (Task 4 — no frozen
        # fields, no supersession); a real save() proves the task-owned-money
        # invariant end to end, not just the DB row.
        self.scheme.rate = Decimal('500.00')
        self.scheme.save()
        task.refresh_from_db()
        self.assertEqual(task.rate, Decimal('95.00'))


class TaskServiceCreateDirectStampingTest(TaskStampingTestBase):
    def test_create_direct_stamps_the_task(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_direct(
            self.job, name='Direct', rate_scheme_id=self.scheme.pk,
            active_modifiers=['rush'],
        )
        self.assertEqual(task.qty_source, RateScheme.ENTERED_QTY)
        self.assertEqual(task.rate, Decimal('95.00'))
        self.assertEqual(task.unit_label, 'hour')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.scheme)
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'rush', 'label': 'Rush', 'percent': 20}],
        )

    def test_create_direct_percentage_scheme_rejected(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.services import TaskService
        pct_scheme = RateScheme.objects.create(
            name='Rush surcharge-cd', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='none',
            accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                self.job, name='x', rate_scheme_id=pct_scheme.pk,
            )

    def test_create_direct_inactive_scheme_raises_scheme_inactive_error(self):
        from apps.jobs.models import SchemeInactiveError
        from apps.jobs.services import TaskService
        self.scheme.is_active = False
        self.scheme.save()
        with self.assertRaises(SchemeInactiveError):
            TaskService.create_direct(
                self.job, name='x', rate_scheme_id=self.scheme.pk,
            )

    def test_create_direct_allow_inactive_scheme_bypasses(self):
        from apps.jobs.services import TaskService
        self.scheme.is_active = False
        self.scheme.save()
        task = TaskService.create_direct(
            self.job, name='x', rate_scheme_id=self.scheme.pk,
            allow_inactive_scheme=True,
        )
        self.assertEqual(task.source_scheme_id, self.scheme.pk)


class TaskServiceCreateFromTemplateStampingTest(TaskStampingTestBase):
    def setUp(self):
        super().setUp()
        self.template = ServiceItem.objects.create(
            template_name='Template-stamp', rate_scheme=self.scheme,
            default_active_modifiers=['weekend'],
        )

    def test_create_from_template_stamps_default_modifiers(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_from_template(self.template, self.job)
        self.assertEqual(task.rate, Decimal('95.00'))
        self.assertEqual(task.unit_label, 'hour')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.scheme)
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'weekend', 'label': 'Weekend', 'percent': 10}],
        )

    def test_create_from_template_inactive_scheme_raises(self):
        from apps.jobs.models import SchemeInactiveError
        from apps.jobs.services import TaskService
        self.scheme.is_active = False
        self.scheme.save()
        with self.assertRaises(SchemeInactiveError):
            TaskService.create_from_template(self.template, self.job)


class ServiceItemGenerateTaskStampingTest(TaskStampingTestBase):
    def setUp(self):
        super().setUp()
        self.template = ServiceItem.objects.create(
            template_name='Template-gt', rate_scheme=self.scheme,
            default_active_modifiers=['rush'],
        )

    def test_generate_task_defaults_to_service_item_modifiers(self):
        task = self.template.generate_task(self.job, est_qty=Decimal('1'))
        self.assertEqual(task.rate, Decimal('95.00'))
        self.assertEqual(task.unit_label, 'hour')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.scheme)
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'rush', 'label': 'Rush', 'percent': 20}],
        )

    def test_generate_task_explicit_modifiers_override_default(self):
        task = self.template.generate_task(
            self.job, est_qty=Decimal('1'), active_modifiers=['weekend'],
        )
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'weekend', 'label': 'Weekend', 'percent': 10}],
        )

    def test_generate_task_inactive_scheme_raises(self):
        from apps.jobs.models import SchemeInactiveError
        self.scheme.is_active = False
        self.scheme.save()
        with self.assertRaises(SchemeInactiveError):
            self.template.generate_task(self.job, est_qty=Decimal('1'))

    def test_generate_task_allow_inactive_scheme_bypasses(self):
        self.scheme.is_active = False
        self.scheme.save()
        task = self.template.generate_task(
            self.job, est_qty=Decimal('1'), allow_inactive_scheme=True,
        )
        self.assertEqual(task.source_scheme_id, self.scheme.pk)
