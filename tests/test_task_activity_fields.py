"""Derived task-activity fields that distinguish 'has an active blep right now'
from 'has had bleps applied'. See docs/plans/2026-05-24-blep-handling-changes.md §4.
Surfaced in both the task serializer and the board payload; no new task status.
"""
from datetime import timedelta
from django.utils import timezone

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, Blep
from apps.core.models import User
from apps.api.tasks.serializers import TaskSerializer
from apps.jobs.services import BoardService


class TaskActivitySerializerFieldsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_item_id=1)
        self.u1 = User.objects.create_user(username='taf1', password='x')
        self.u2 = User.objects.create_user(username='taf2', password='x')

    def _data(self):
        return TaskSerializer(self.task).data

    def test_no_bleps(self):
        d = self._data()
        self.assertFalse(d['has_active_blep'])
        self.assertEqual(d['active_worker_count'], 0)
        self.assertFalse(d['has_bleps'])

    def test_one_open_blep(self):
        Blep.objects.create(task=self.task, user=self.u1, start_time=timezone.now())
        d = self._data()
        self.assertTrue(d['has_active_blep'])
        self.assertEqual(d['active_worker_count'], 1)
        self.assertTrue(d['has_bleps'])

    def test_two_workers_open(self):
        Blep.objects.create(task=self.task, user=self.u1, start_time=timezone.now())
        Blep.objects.create(task=self.task, user=self.u2, start_time=timezone.now())
        d = self._data()
        self.assertEqual(d['active_worker_count'], 2)

    def test_closed_blep_only_is_worked_not_active(self):
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.u1,
            start_time=now - timedelta(hours=1), end_time=now,
        )
        d = self._data()
        self.assertFalse(d['has_active_blep'])
        self.assertEqual(d['active_worker_count'], 0)
        self.assertTrue(d['has_bleps'])


class BoardTaskActivityFieldsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_item_id=1)
        self.u1 = User.objects.create_user(username='btaf1', password='x')

    def test_board_serialize_task_includes_activity(self):
        Blep.objects.create(task=self.task, user=self.u1, start_time=timezone.now())
        d = BoardService._serialize_task(self.task, {})
        self.assertTrue(d['has_active_blep'])
        self.assertEqual(d['active_worker_count'], 1)
        self.assertTrue(d['has_bleps'])

    def test_board_serialize_task_no_bleps(self):
        d = BoardService._serialize_task(self.task, {})
        self.assertFalse(d['has_active_blep'])
        self.assertEqual(d['active_worker_count'], 0)
        self.assertFalse(d['has_bleps'])
