"""TaskSerializer exposes the parent task's name so the task-detail page can
render its "subtask of <parent>" crumb link without an extra fetch.
"""
from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, RateScheme
from apps.api.tasks.serializers import TaskSerializer


class TaskParentNameSerializerTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.parent = Task(
            name='Build shelving unit', job=self.job)
        self.parent.stamp_from_scheme(RateScheme.objects.get(pk=1))
        self.parent.save()
        self.child = Task(
            name='CNC cut shelving parts', job=self.job,
            parent_task=self.parent)
        self.child.stamp_from_scheme(RateScheme.objects.get(pk=1))
        self.child.save()

    def test_subtask_carries_parent_name(self):
        d = TaskSerializer(self.child).data
        self.assertEqual(d['parent_task'], self.parent.task_id)
        self.assertEqual(d['parent_task_name'], 'Build shelving unit')

    def test_top_level_task_has_null_parent_name(self):
        d = TaskSerializer(self.parent).data
        self.assertIsNone(d['parent_task'])
        self.assertIsNone(d['parent_task_name'])
