"""TaskSerializer exposes the parent task's name so the task-detail page can
render its "subtask of <parent>" crumb link without an extra fetch.
"""
from tests.base import BaseTestCase
from apps.jobs.models import Job, Task
from apps.api.tasks.serializers import TaskSerializer


class TaskParentNameSerializerTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.parent = Task.objects.create(
            name='Build shelving unit', job=self.job, rate_scheme_id=1)
        self.child = Task.objects.create(
            name='CNC cut shelving parts', job=self.job,
            rate_scheme_id=1, parent_task=self.parent)

    def test_subtask_carries_parent_name(self):
        d = TaskSerializer(self.child).data
        self.assertEqual(d['parent_task'], self.parent.task_id)
        self.assertEqual(d['parent_task_name'], 'Build shelving unit')

    def test_top_level_task_has_null_parent_name(self):
        d = TaskSerializer(self.parent).data
        self.assertIsNone(d['parent_task'])
        self.assertIsNone(d['parent_task_name'])
