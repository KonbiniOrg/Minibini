"""estimates/0047 descoped_by backfill data migration.

One-time historical backfill (CO amend-in-place plan, Task 4): legacy
accepted-CO remove AND replace lines both retired their target's atom, so
the migration stamps descoped_by on both, reading the target line's own
EstimateLineItemSource rows directly. Direct-call precedent for invoking a
migration's function against the live apps registry:
tests/test_fee_purge_migrations.py.

ChangeOrderLineItem.clean() now forbids a crystallization descriptor on a
replace line, but .objects.create() doesn't call clean() — exactly how
legacy rows with retired-atom replace semantics exist in the dev DB.
"""
import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
    EstimateLineItemSource,
)
from apps.inventory.models import Material
from apps.jobs.models import Job, Task

# Module name starts with a digit, so importlib handles the dotted string.
_migration = importlib.import_module(
    'apps.estimates.migrations.0047_backfill_descoped_by')


class DescopeBackfillMigrationTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED)

    def _make_task(self, name):
        return Task.objects.create(job=self.job, name=name)

    def _make_material(self, description):
        return Material.objects.create(
            job=self.job, description=description,
            accounting_category=self.cat)

    def test_stamps_remove_and_replace_targets_skips_dangling(self):
        # Target 1: claimed by a Task, hit by an accepted CO's remove line.
        remove_target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='remove target',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat)
        removed_task = self._make_task('removed task')
        EstimateLineItemSource.objects.create(
            estimate_line_item=remove_target, source_type='task',
            source_pk=removed_task.pk)

        # Target 2: claimed by a Material, hit by an accepted CO's replace line.
        replace_target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='replace target',
            qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat)
        replaced_material = self._make_material('replaced material')
        EstimateLineItemSource.objects.create(
            estimate_line_item=replace_target, source_type='material',
            source_pk=replaced_material.pk)

        # Unrelated line, untouched by any CO — must survive unstamped.
        unrelated = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='unrelated',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat)
        unrelated_task = self._make_task('unrelated task')
        EstimateLineItemSource.objects.create(
            estimate_line_item=unrelated, source_type='task',
            source_pk=unrelated_task.pk)

        # Dangling source row: atom already deleted, must be skipped without error.
        dangling_target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='dangling target',
            qty=Decimal('1'), price=Decimal('5.00'),
            accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=dangling_target, source_type='task',
            source_pk=999999)

        co = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate,
            change_order_number='CO-2026-0001',
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now())
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_REMOVE,
            line_number=1, target_line_item=remove_target,
            description='remove', qty=Decimal('1'), price=Decimal('0'),
            accounting_category=self.cat)
        # Legacy replace row: descriptor-free (clean() would forbid a
        # descriptor here, but .objects.create() bypasses clean(), matching
        # how legacy rows exist).
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_REPLACE,
            line_number=2, target_line_item=replace_target,
            description='replace', qty=Decimal('1'), price=Decimal('60.00'),
            accounting_category=self.cat)
        # CO line targeting the dangling row, so the migration walks it too.
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_REMOVE,
            line_number=3, target_line_item=dangling_target,
            description='remove dangling', qty=Decimal('1'), price=Decimal('0'),
            accounting_category=self.cat)

        _migration.stamp_descoped_atoms(django_apps, None)

        removed_task.refresh_from_db()
        replaced_material.refresh_from_db()
        unrelated_task.refresh_from_db()

        self.assertEqual(removed_task.descoped_by_id, co.pk)
        self.assertEqual(replaced_material.descoped_by_id, co.pk)
        self.assertIsNone(unrelated_task.descoped_by_id)
        # No exception raised for the dangling source row is itself the assertion.

    def test_later_accepted_co_wins_when_both_target_same_line(self):
        target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='target',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat)
        task = self._make_task('contested task')
        EstimateLineItemSource.objects.create(
            estimate_line_item=target, source_type='task', source_pk=task.pk)

        earlier_co = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate,
            change_order_number='CO-2026-0001',
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now() - timezone.timedelta(days=2))
        ChangeOrderLineItem.objects.create(
            change_order=earlier_co, action=ChangeOrderLineItem.ACTION_REMOVE,
            line_number=1, target_line_item=target,
            description='remove', qty=Decimal('1'), price=Decimal('0'),
            accounting_category=self.cat)

        later_co = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate,
            change_order_number='CO-2026-0002',
            status=ChangeOrder.STATUS_ACCEPTED,
            closed_date=timezone.now() - timezone.timedelta(days=1))
        ChangeOrderLineItem.objects.create(
            change_order=later_co, action=ChangeOrderLineItem.ACTION_REMOVE,
            line_number=1, target_line_item=target,
            description='remove again', qty=Decimal('1'), price=Decimal('0'),
            accounting_category=self.cat)

        _migration.stamp_descoped_atoms(django_apps, None)

        task.refresh_from_db()
        self.assertEqual(task.descoped_by_id, later_co.pk)
