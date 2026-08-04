"""Task deletion guards (plan B5): open to any authenticated user, but
refused when the task has a consumed material or the job is terminal;
pending materials detach to the job as loose rows.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.inventory.models import Material
from apps.jobs.models import Blep, Job, Task, RateScheme
from apps.jobs.services import TaskService


class TaskDeleteGuardsTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='D', last_name='G')
        self.job = Job.objects.create(
            job_number='DEL-001', name='Delete Job', contact=self.contact,
        )
        self.ac = AccountingCategory.objects.create(code='DEL', name='Del AC')
        self.scheme = RateScheme.objects.create(
            name='S-del', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=self.ac,
        )
        self.task = Task(
            job=self.job, name='Doomed',
        )
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

    def test_consumed_material_blocks_delete(self):
        Material.objects.create(
            job=self.job, task=self.task, description='Hand-consumed',
            quantity=Decimal('1'), accounting_category=self.ac,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.task.pk)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_pending_material_detaches_to_loose(self):
        material = Material.objects.create(
            job=self.job, task=self.task, description='Planned stock',
            quantity=Decimal('2'), accounting_category=self.ac,
        )
        TaskService.delete_task(self.task.pk)
        material.refresh_from_db()
        self.assertIsNone(material.task)
        self.assertEqual(material.job, self.job)

    def test_terminal_job_blocks_delete(self):
        self.job.status = Job.STATUS_REJECTED
        self.job.save()
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.task.pk)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_plain_delete_still_works(self):
        TaskService.delete_task(self.task.pk)
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())


class TaskDeleteParentGuardTest(TestCase):
    """Final-review finding I3: TaskService.delete_task cascades (DB
    CASCADE from Task.parent_task) without checking its children's own
    delete guards. A parent with a non-terminal child, or a TERMINAL
    child that still carries bleps or consumed materials, must not be
    deletable — the cascade would otherwise silently destroy that
    child's recorded work/inventory history out from under its own
    guards (cancel_task's own children-terminal gate doesn't cover
    this: cancel never deletes rows, but delete does)."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='D2', last_name='G2')
        self.job = Job.objects.create(
            job_number='DELP-001', name='Delete Parent Job', contact=self.contact,
        )
        self.ac = AccountingCategory.objects.create(code='DELP', name='DelP AC')
        self.elapsed_scheme = RateScheme.objects.create(
            name='S-delp-elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=self.ac,
        )
        self.entered_scheme = RateScheme.objects.create(
            name='S-delp-entered', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )
        self.parent = Task(job=self.job, name='Structure', est_qty=Decimal('5'))
        self.parent.stamp_from_scheme(self.entered_scheme)
        self.parent.save()

    def _child(self, name, scheme=None):
        child = Task(
            job=self.job, name=name, parent_task=self.parent,
            est_qty=Decimal('1'), qty_scales_with_parent=False,
        )
        child.stamp_from_scheme(scheme or self.entered_scheme)
        child.save()
        return child

    def test_delete_parent_blocked_by_non_terminal_child(self):
        self._child('Open child')
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.parent.pk)
        self.assertTrue(Task.objects.filter(pk=self.parent.pk).exists())

    def test_delete_parent_blocked_by_terminal_child_with_bleps(self):
        worker = User.objects.create_user(username='delp_worker', password='pass')
        child = self._child('Timed child', scheme=self.elapsed_scheme)
        Blep.objects.create(
            task=child, user=worker,
            start_time=timezone.now() - timedelta(hours=1), end_time=timezone.now(),
        )
        Task.objects.filter(pk=child.pk).update(status=Task.STATUS_COMPLETE)
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.parent.pk)
        self.assertTrue(Task.objects.filter(pk=self.parent.pk).exists())
        self.assertTrue(Task.objects.filter(pk=child.pk).exists())

    def test_delete_parent_blocked_by_terminal_child_with_consumed_material(self):
        child = self._child('Consumed child')
        Task.objects.filter(pk=child.pk).update(status=Task.STATUS_COMPLETE)
        Material.objects.create(
            job=self.job, task=child, description='Consumed on child',
            quantity=Decimal('1'), accounting_category=self.ac,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.parent.pk)
        self.assertTrue(Task.objects.filter(pk=self.parent.pk).exists())

    def test_delete_parent_allowed_when_children_all_clean_and_terminal(self):
        child = self._child('Clean terminal child')
        Task.objects.filter(pk=child.pk).update(status=Task.STATUS_CANCELLED)
        TaskService.delete_task(self.parent.pk)
        self.assertFalse(Task.objects.filter(pk=self.parent.pk).exists())
        self.assertFalse(Task.objects.filter(pk=child.pk).exists())
