"""Subtask creation must never skip the task-creation service guards
(plan A2), and subtask depth is capped at one level (plan B1).

Both creation surfaces are pinned here — the flat subtasks endpoint
(POST /api/tasks/{id}/subtasks/) and the job-nested create with a
parent_task — so a future endpoint change can't quietly bypass
TaskService.create_direct again.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService, TaskService


def _scheme(suffix):
    ac, _ = AccountingCategory.objects.get_or_create(
        code=f'SG{suffix[:3]}'.upper(), defaults={'name': f'AC {suffix}'},
    )
    return RateScheme.objects.create(
        name=f'S-guard-{suffix}', algorithm=RateScheme.ELAPSED_TIME,
        rate=Decimal('45'), unit_label='hour', accounting_category=ac,
    )


class SubtaskGuardTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='guarduser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='G', last_name='U')
        self.job = Job.objects.create(
            job_number='GRD-001', name='Guard Job', contact=self.contact,
        )
        self.scheme = _scheme('a')
        self.parent = Task.objects.create(
            job=self.job, name='Parent', source_scheme=self.scheme,
        )

    def _post_subtask(self, parent, name='Sub', scheme=None):
        return self.client.post(
            f'/api/tasks/{parent.pk}/subtasks/',
            {'name': name, 'rate_scheme': (scheme or self.scheme).pk},
            format='json',
        )

    def _approve(self):
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = status
            self.job.save()


class SubtaskCreateGuardsTest(SubtaskGuardTestBase):
    """The subtasks endpoint routes through TaskService.create_direct."""

    def test_held_job_rejects_subtask_create(self):
        self._approve()
        JobService.hold_job(self.job.pk, 'checking guards')
        response = self._post_subtask(self.parent)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.filter(parent_task=self.parent).exists())

    def test_inactive_scheme_rejects_subtask_create(self):
        old = _scheme('old')
        old.is_active = False
        old.save()
        response = self._post_subtask(self.parent, scheme=old)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.filter(parent_task=self.parent).exists())

    def test_percentage_scheme_rejects_subtask_create(self):
        ac = AccountingCategory.objects.create(code='SGPCT', name='Pct')
        pct = RateScheme.objects.create(
            name='S-guard-pct', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=ac,
        )
        response = self._post_subtask(self.parent, scheme=pct)
        self.assertEqual(response.status_code, 400)

    def test_subtask_create_reopens_work_complete_job(self):
        self._approve()
        # Complete the only task -> auto-advance to work_complete.
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        from django.utils import timezone
        from datetime import timedelta
        now = timezone.now()
        Blep.objects.create(
            task=self.parent, user=self.user,
            start_time=now - timedelta(hours=1), end_time=now,
        )
        TaskLifecycleService.complete_task(self.parent.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

        # A parent task that's complete refuses subtasks; use a fresh
        # sibling parent to host the new subtask.
        sibling = Task.objects.create(
            job=self.job, name='Sibling parent', source_scheme=self.scheme,
        )
        # Creating the sibling itself already reopens; force the job back
        # to work_complete so the SUBTASK create is what reopens it.
        Task.objects.filter(pk=sibling.pk).update(status=Task.STATUS_COMPLETE)
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        Task.objects.filter(pk=sibling.pk).update(status=Task.STATUS_PENDING)

        response = self._post_subtask(sibling, name='Reopening sub')
        self.assertEqual(response.status_code, 201)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)


class SubtaskDepthGuardTest(SubtaskGuardTestBase):
    """One level of subtasks only — a subtask can never be a parent."""

    def setUp(self):
        super().setUp()
        self.subtask = Task.objects.create(
            job=self.job, name='Child', source_scheme=self.scheme,
            parent_task=self.parent,
        )

    def test_subtasks_endpoint_rejects_grandchild(self):
        response = self._post_subtask(self.subtask, name='Grandchild')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.filter(parent_task=self.subtask).exists())

    def test_job_nested_create_rejects_grandchild(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Grandchild', 'rate_scheme': self.scheme.pk,
             'parent_task': self.subtask.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.filter(parent_task=self.subtask).exists())

    def test_service_rejects_grandchild(self):
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                self.job, 'Grandchild', rate_scheme_id=self.scheme.pk,
                parent_task_id=self.subtask.pk,
            )

    def test_service_rejects_cross_job_parent(self):
        other_job = Job.objects.create(
            job_number='GRD-002', name='Other Job', contact=self.contact,
        )
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                other_job, 'Wrong-job sub', rate_scheme_id=self.scheme.pk,
                parent_task_id=self.parent.pk,
            )

    def test_one_level_subtask_still_allowed(self):
        response = self._post_subtask(self.parent, name='Second child')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Task.objects.filter(parent_task=self.parent).count(), 2)
