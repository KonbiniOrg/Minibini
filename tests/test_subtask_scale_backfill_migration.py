"""jobs/0062_task_qty_scales_with_parent's RunPython backfill: no test
previously exercised its forwards() body directly. Precedent for calling a
migration's logic directly against the live apps registry (rather than
replaying the whole migration graph): tests/test_singular_units_migration.py.

Controller-verified (2026-08-04, read-only dev-DB SELECT): 26 real dev-DB
subtask rows predate the qty_scales_with_parent flag entirely — their
est_qty values were authored as plain per-batch totals, with no multiplier
concept in play. The migration's own AddField default (True) would silently
start multiplying those historical totals by the parent's est_qty. This
test plants that pre-migration shape (a subtask row already carrying the
DB-default True, simulating what AddField alone would leave behind) and
asserts forwards() flips it to False, while leaving a top-level task's flag
untouched (it never had a parent_task_id to match on).
"""
import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, RateScheme, Task

_migration = importlib.import_module(
    'apps.jobs.migrations.0062_task_qty_scales_with_parent')


class SubtaskScaleBackfillMigrationTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='SSB', code='SSB')
        self.contact = Contact.objects.create(first_name='S', last_name='B')
        self.job = Job.objects.create(job_number='SSB-001', contact=self.contact)
        self.scheme = RateScheme.objects.create(
            name='SSB scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )

    def _task(self, name, parent=None):
        task = Task(job=self.job, name=name, parent_task=parent, est_qty=Decimal('1'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def test_forwards_sets_false_for_pre_existing_subtasks_only(self):
        parent = self._task('Parent')
        # Pre-migration shape: a real historical subtask, left at the
        # column's own DB default (True) — exactly what a bare AddField
        # (no backfill) would leave behind.
        subtask = self._task('Subtask', parent=parent)
        self.assertTrue(subtask.qty_scales_with_parent)

        _migration.forwards(django_apps, None)

        subtask.refresh_from_db()
        self.assertFalse(subtask.qty_scales_with_parent)
        # The top-level parent has no parent_task_id — untouched, still at
        # its own default (the flag is inert there anyway).
        parent.refresh_from_db()
        self.assertTrue(parent.qty_scales_with_parent)

    def test_forwards_is_a_noop_when_no_subtasks_exist(self):
        self._task('Loose top-level task')
        # Must not raise / touch anything when there's nothing to backfill.
        _migration.forwards(django_apps, None)

    def test_forwards_returns_none_but_does_not_raise_when_run_twice(self):
        parent = self._task('Parent2')
        subtask = self._task('Subtask2', parent=parent)
        _migration.forwards(django_apps, None)
        _migration.forwards(django_apps, None)  # idempotent re-run
        subtask.refresh_from_db()
        self.assertFalse(subtask.qty_scales_with_parent)
