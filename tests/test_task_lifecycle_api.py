from django.utils import timezone
from rest_framework.test import APIClient
from apps.jobs.models import Task, WorkOrder, Blep
from tests.base import BaseTestCase


class TaskLifecycleAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def _create_user(self, username):
        from apps.core.models import User
        return User.objects.create_user(username=username, password='test')

    def test_complete_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        url = f'/api/tasks/{self.task.pk}/complete/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_block_task(self):
        url = f'/api/tasks/{self.task.pk}/block/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)

    def test_unblock_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        url = f'/api/tasks/{self.task.pk}/unblock/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_cancel_task(self):
        url = f'/api/tasks/{self.task.pk}/cancel/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_start_work(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('blep_id', resp.data)
        self.assertTrue(Blep.objects.filter(task=self.task, user=self.user).exists())

    def test_start_work_on_pending_task_auto_promotes(self):
        # Task is pending by default; start-work should transition it to
        # in_progress and create a Blep in one step.
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('blep_id', resp.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        self.assertTrue(Blep.objects.filter(task=self.task, user=self.user).exists())

    def test_stop_work(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/stop-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNotNone(blep.end_time)

    def test_bleps_list(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/bleps/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_start_work_conflict_response(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        Blep.objects.create(task=self.task, user=other_user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('conflict', resp.data)

    def test_start_work_join(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        Blep.objects.create(task=self.task, user=other_user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'join'})
        self.assertEqual(resp.status_code, 200)
        # Both users should have open bleps
        self.assertEqual(
            Blep.objects.filter(task=self.task, end_time__isnull=True).count(), 2
        )

    def test_start_work_takeover(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        Blep.objects.create(task=self.task, user=other_user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'takeover'})
        self.assertEqual(resp.status_code, 200)
        # Other user's blep should be closed
        other_blep = Blep.objects.get(task=self.task, user=other_user)
        self.assertIsNotNone(other_blep.end_time)
        # Current user should have open blep
        my_blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNone(my_blep.end_time)

    def test_invalid_transition_returns_400(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)

    def test_wrong_task_returns_404(self):
        url = f'/api/tasks/99999/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


class TaskSerializerStatusTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User
        from apps.jobs.models import Job
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_task_list_includes_status(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('status', resp.data[0])
        self.assertEqual(resp.data[0]['status'], Task.STATUS_PENDING)
