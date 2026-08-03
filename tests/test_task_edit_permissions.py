"""Task editability matrix (plan C1) and cancel permissions (plan C2).

- pending: any authenticated user edits everything.
- in_progress / blocked: manager (atom), the job's PM, or the task's
  ASSIGNEE — assignee is a new object-scoped permission principal.
- complete / cancelled: frozen (existing behavior, pinned elsewhere).
- cancel: any authenticated user (same principal set as delete).

The serializer exposes a computed `can_edit` flag the SPA gates on.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from tests.base import grant_atoms


class TaskEditPermissionTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.worker = User.objects.create_user(
            username='edit-worker', password='x')
        self.assignee = User.objects.create_user(
            username='edit-assignee', password='x')
        self.manager = grant_atoms(
            User.objects.create_user(username='edit-mgr', password='x'),
            'can_manage_jobs')
        self.pm = User.objects.create_user(username='edit-pm', password='x')

        self.contact = Contact.objects.create(first_name='E', last_name='P')
        self.job = Job.objects.create(
            job_number='EDP-001', name='Edit Perm Job', contact=self.contact,
            project_manager=self.pm,
        )
        ac = AccountingCategory.objects.create(code='EDP', name='Edit AC')
        self.scheme = RateScheme.objects.create(
            name='S-edit', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=ac,
        )

    def _task(self, status=Task.STATUS_PENDING, assignee=None):
        task = Task(
            job=self.job, name=f'Task {status}',
            assignee=assignee,
            est_worker_time=timedelta(hours=1) if assignee else None,
        )
        task.stamp_from_scheme(self.scheme)
        task.save()
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    def _patch(self, task, user, payload=None):
        self.client.force_authenticate(user=user)
        return self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            payload or {'description': 'edited'},
            format='json',
        )


class EditByStatusTest(TaskEditPermissionTestBase):
    def test_pending_editable_by_any_worker(self):
        task = self._task()
        response = self._patch(task, self.worker)
        self.assertEqual(response.status_code, 200)

    def test_in_progress_rejects_plain_worker(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        response = self._patch(task, self.worker)
        self.assertEqual(response.status_code, 403)
        task.refresh_from_db()
        self.assertNotEqual(task.description, 'edited')

    def test_in_progress_allows_assignee(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        response = self._patch(task, self.assignee)
        self.assertEqual(response.status_code, 200)

    def test_in_progress_allows_manager(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        response = self._patch(task, self.manager)
        self.assertEqual(response.status_code, 200)

    def test_in_progress_allows_project_manager(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        response = self._patch(task, self.pm)
        self.assertEqual(response.status_code, 200)

    def test_blocked_rejects_plain_worker(self):
        task = self._task(Task.STATUS_BLOCKED, assignee=self.assignee)
        response = self._patch(task, self.worker)
        self.assertEqual(response.status_code, 403)

    def test_blocked_allows_assignee(self):
        task = self._task(Task.STATUS_BLOCKED, assignee=self.assignee)
        response = self._patch(task, self.assignee)
        self.assertEqual(response.status_code, 200)


class CanEditFlagTest(TaskEditPermissionTestBase):
    def _flag(self, task, user):
        self.client.force_authenticate(user=user)
        response = self.client.get(f'/api/tasks/{task.pk}/')
        return response.data.get('can_edit')

    def test_pending_flag_true_for_worker(self):
        self.assertTrue(self._flag(self._task(), self.worker))

    def test_in_progress_flag_false_for_worker(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        self.assertFalse(self._flag(task, self.worker))

    def test_in_progress_flag_true_for_assignee(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        self.assertTrue(self._flag(task, self.assignee))

    def test_in_progress_flag_true_for_pm(self):
        task = self._task(Task.STATUS_IN_PROGRESS, assignee=self.assignee)
        self.assertTrue(self._flag(task, self.pm))

    def test_complete_flag_false_for_everyone(self):
        task = self._task(Task.STATUS_COMPLETE)
        self.assertFalse(self._flag(task, self.manager))


class CancelPermissionTest(TaskEditPermissionTestBase):
    """Plan C2: cancel is open to any authenticated user."""

    def test_plain_worker_can_cancel(self):
        task = self._task()
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(f'/api/tasks/{task.pk}/cancel/')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_CANCELLED)

    def test_unauthenticated_cannot_cancel(self):
        task = self._task()
        self.client.force_authenticate(user=None)
        response = self.client.post(f'/api/tasks/{task.pk}/cancel/')
        self.assertIn(response.status_code, (401, 403))
