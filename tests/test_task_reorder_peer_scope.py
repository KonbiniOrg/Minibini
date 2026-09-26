"""Task reordering operates over the job's flat task list.

(Formerly peer-scoped between top-level tasks and subtask siblings; tasks
are one flat level since the better-fees subtask removal — spec §3 — so
the peer group is simply the job.)
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import TaskService


class FlatReorderTest(TestCase):
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
        self.t1 = Task(job=self.job, name='T1')
        self.t1.stamp_from_scheme(self.scheme)
        self.t1.save()
        self.t2 = Task(job=self.job, name='T2')
        self.t2.stamp_from_scheme(self.scheme)
        self.t2.save()
        self.t3 = Task(job=self.job, name='T3')
        self.t3.stamp_from_scheme(self.scheme)
        self.t3.save()

    def _order(self):
        return list(
            Task.objects.filter(job=self.job)
            .order_by('sort_order', 'pk').values_list('name', flat=True)
        )

    def test_move_up_swaps_adjacent_tasks(self):
        TaskService.reorder_tasks(self.t3.pk, 'up')
        self.assertEqual(self._order(), ['T1', 'T3', 'T2'])

    def test_move_down_swaps_adjacent_tasks(self):
        TaskService.reorder_tasks(self.t1.pk, 'down')
        self.assertEqual(self._order(), ['T2', 'T1', 'T3'])

    def test_first_task_cannot_move_up(self):
        with self.assertRaises(ValidationError):
            TaskService.reorder_tasks(self.t1.pk, 'up')
        self.assertEqual(self._order(), ['T1', 'T2', 'T3'])

    def test_last_task_cannot_move_down(self):
        with self.assertRaises(ValidationError):
            TaskService.reorder_tasks(self.t3.pk, 'down')
        self.assertEqual(self._order(), ['T1', 'T2', 'T3'])
