"""TaskLifecycleService.cancel_work — the under-the-minimum 'oops' undo.

See docs/plans/2026-05-24-blep-handling-changes.md §2. Cancel deletes the
worker's open blep and, only when that blep was the first/only activity on the
task, reverts the task to pending and un-consumes its materials. Job status and
assignment are deliberately left alone.
"""
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import TaskLifecycleService
from apps.core.models import User, AccountingCategory
from apps.inventory.models import Material, InventoryItem
from apps.inventory.services import MaterialService


def _approve_job(job):
    for step in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        if job.status != step:
            job.status = step
            job.save()


class CancelWorkFirstActivityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.user = User.objects.get(username='admin')

    def test_cancel_reverts_task_to_pending(self):
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_PENDING)

    def test_cancel_deletes_the_blep(self):
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        blep_id = result['blep'].blep_id
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        self.assertFalse(Blep.objects.filter(pk=blep_id).exists())

    def test_cancel_leaves_job_status_in_progress(self):
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_cancel_unconsumes_materials(self):
        cat = AccountingCategory.objects.create(name='cw')
        pli = InventoryItem.objects.create(
            code='CW', accounting_category=cat,
            qty_on_hand=Decimal('10'),
        )
        mat = MaterialService.create_on_job(
            job=self.job, task=self.task, description='m',
            quantity=Decimal('4'), inventory_item=pli,
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        mat.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        mat.refresh_from_db()
        pli.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(pli.qty_on_hand, Decimal('10'))

    def test_restart_after_cancel_succeeds(self):
        TaskLifecycleService.start_work(self.task.pk, self.user)
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        result = TaskLifecycleService.start_work(self.task.pk, self.user)  # must not raise
        self.assertIsNone(result['blep'].end_time)


class CancelWorkGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.user = User.objects.get(username='admin')
        self.other = User.objects.create_user(username='cw_other', password='x')

    def test_cancel_rejects_session_over_threshold(self):
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=5),  # 300s > 60s default
        )
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_work(self.task.pk, self.user)

    def test_cancel_rejects_when_no_open_blep(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_work(self.task.pk, self.user)

    def test_cancel_join_case_only_deletes_own_blep(self):
        other_blep = Blep.objects.create(
            task=self.task, user=self.other, start_time=timezone.now(),
        )
        my_blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.cancel_work(self.task.pk, self.user)
        self.assertFalse(Blep.objects.filter(pk=my_blep.blep_id).exists())
        other_blep.refresh_from_db()
        self.assertIsNone(other_blep.end_time)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
