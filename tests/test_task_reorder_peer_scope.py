"""Task reordering is peer-scoped (plan B3): a top-level task swaps only
with other top-level tasks, and a subtask swaps only with its siblings.
The old behavior swapped adjacent rows in the flat per-job sort_order
sequence, where parents and subtasks interleave invisibly.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import TaskService


class PeerScopedReorderTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='R', last_name='O')
        self.job = Job.objects.create(
            job_number='REO-001', name='Reorder Job', contact=self.contact,
        )
        ac = AccountingCategory.objects.create(code='REO', name='Reorder AC')
        self.scheme = RateScheme.objects.create(
            name='S-reorder', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=ac,
        )
        # Flat creation order interleaves the subtask between the two
        # top-level tasks in the per-job sort_order sequence:
        #   t1(1), sub(2, child of t1), t2(3)
        self.t1 = Task(job=self.job, name='T1')
        self.t1.stamp_from_scheme(self.scheme)
        self.t1.save()
        self.sub = Task(
            job=self.job, name='T1 sub', parent_task=self.t1)
        self.sub.stamp_from_scheme(self.scheme)
        self.sub.save()
        self.t2 = Task(job=self.job, name='T2')
        self.t2.stamp_from_scheme(self.scheme)
        self.t2.save()

    def _top_level_order(self):
        return list(
            Task.objects.filter(job=self.job, parent_task__isnull=True)
            .order_by('sort_order', 'pk').values_list('name', flat=True)
        )

    def test_top_level_moves_past_interleaved_subtask_in_one_step(self):
        TaskService.reorder_tasks(self.t2.pk, 'up')
        self.assertEqual(self._top_level_order(), ['T2', 'T1'])

    def test_top_level_reorder_leaves_subtask_untouched(self):
        before = Task.objects.get(pk=self.sub.pk).sort_order
        TaskService.reorder_tasks(self.t2.pk, 'up')
        self.assertEqual(Task.objects.get(pk=self.sub.pk).sort_order, before)

    def test_subtask_swaps_within_siblings_only(self):
        sub2 = Task(
            job=self.job, name='T1 sub2', parent_task=self.t1)
        sub2.stamp_from_scheme(self.scheme)
        sub2.save()
        top_before = self._top_level_order()
        TaskService.reorder_tasks(sub2.pk, 'up')
        siblings = list(
            Task.objects.filter(parent_task=self.t1)
            .order_by('sort_order', 'pk').values_list('name', flat=True)
        )
        self.assertEqual(siblings, ['T1 sub2', 'T1 sub'])
        self.assertEqual(self._top_level_order(), top_before)

    def test_first_top_level_task_cannot_move_up(self):
        with self.assertRaises(ValidationError):
            TaskService.reorder_tasks(self.t1.pk, 'up')

    def test_only_sibling_cannot_move(self):
        with self.assertRaises(ValidationError):
            TaskService.reorder_tasks(self.sub.pk, 'up')
        with self.assertRaises(ValidationError):
            TaskService.reorder_tasks(self.sub.pk, 'down')
