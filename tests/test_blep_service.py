from django.utils import timezone
from datetime import timedelta

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.jobs.services.blep_service import BlepService


class BlepServicePrimitivesTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Task', work_order=self.wo)
        self.other_task = Task.objects.create(name='Other', work_order=self.wo)
        self.user = User.objects.get(username='admin')
        self.other_user = User.objects.create_user(username='worker2', password='x')

    def test_create_returns_open_blep(self):
        blep = BlepService._create(self.task, self.user)
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.task, self.task)

    def test_create_with_explicit_times(self):
        start = timezone.now() - timedelta(hours=2)
        end = timezone.now() - timedelta(hours=1)
        blep = BlepService._create(self.task, self.user, start_time=start, end_time=end)
        self.assertEqual(blep.start_time, start)
        self.assertEqual(blep.end_time, end)

    def test_close_open_by_user_closes_all_user_bleps(self):
        b1 = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        b2 = Blep.objects.create(task=self.other_task, user=self.user, start_time=timezone.now())
        # Another user's blep should NOT be closed.
        other = Blep.objects.create(task=self.task, user=self.other_user, start_time=timezone.now())
        BlepService._close_open(user=self.user)
        b1.refresh_from_db(); b2.refresh_from_db(); other.refresh_from_db()
        self.assertIsNotNone(b1.end_time)
        self.assertIsNotNone(b2.end_time)
        self.assertIsNone(other.end_time)

    def test_close_open_by_user_and_task_scoped(self):
        on_task = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        other_task_blep = Blep.objects.create(task=self.other_task, user=self.user, start_time=timezone.now())
        BlepService._close_open(user=self.user, task=self.task)
        on_task.refresh_from_db(); other_task_blep.refresh_from_db()
        self.assertIsNotNone(on_task.end_time)
        self.assertIsNone(other_task_blep.end_time)

    def test_close_open_by_task_closes_all_workers(self):
        mine = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        theirs = Blep.objects.create(task=self.task, user=self.other_user, start_time=timezone.now())
        BlepService._close_open(task=self.task)
        mine.refresh_from_db(); theirs.refresh_from_db()
        self.assertIsNotNone(mine.end_time)
        self.assertIsNotNone(theirs.end_time)

    def test_close_open_requires_filter(self):
        with self.assertRaises(ValueError):
            BlepService._close_open()
