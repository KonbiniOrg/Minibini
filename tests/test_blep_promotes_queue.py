from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Task, RateScheme
from apps.jobs.services import JobService, TaskLifecycleService


class BlepStartPromotesQueueTest(BaseTestCase):
    """Starting a blep on a task moves that task to position 1 in the
    assignee's worker_queue, with the other open tasks shifted down by
    one. Keeps queue state aligned with what's actually being worked on."""

    def setUp(self):
        super().setUp()
        self.user, _ = User.objects.get_or_create(
            username='qpromote',
            defaults={'first_name': 'Q', 'last_name': 'P'},
        )
        contact = Contact.objects.first()
        self.job = JobService.create_job(contact=contact, description='Test job')
        rs = RateScheme.objects.first()
        self.tasks = [
            Task.objects.create(
                job=self.job, assignee=self.user, rate_scheme=rs,
                name=f'T{i}', est_worker_time=timedelta(minutes=60),
                worker_queue=i, status=Task.STATUS_PENDING,
            )
            for i in range(1, 6)  # five tasks, queue 1..5
        ]
        from apps.jobs.models import Job
        self.job.status = Job.STATUS_SUBMITTED; self.job.save()
        self.job.status = Job.STATUS_APPROVED; self.job.save()

    def test_starting_blep_on_third_task_promotes_it_to_front(self):
        target = self.tasks[2]  # original worker_queue=3
        TaskLifecycleService.start_work(target.task_id, self.user)

        target_after = Task.objects.get(pk=target.task_id)
        self.assertEqual(target_after.worker_queue, 1)

        # Original [T1, T2, T3, T4, T5] minus T3 → [T1, T2, T4, T5] at queue 2..5
        expected_after_target = [self.tasks[0].pk, self.tasks[1].pk,
                                  self.tasks[3].pk, self.tasks[4].pk]
        actual_after_target = [
            t.pk for t in Task.objects.filter(
                assignee=self.user,
            ).exclude(pk=target.task_id).order_by('worker_queue', 'pk')
        ]
        self.assertEqual(actual_after_target, expected_after_target)

    def test_starting_blep_on_already_first_is_noop(self):
        target = self.tasks[0]
        TaskLifecycleService.start_work(target.task_id, self.user)
        target_after = Task.objects.get(pk=target.task_id)
        self.assertEqual(target_after.worker_queue, 1)
        for i, task in enumerate(self.tasks[1:], start=2):
            self.assertEqual(
                Task.objects.get(pk=task.task_id).worker_queue, i,
            )

    def test_non_assignee_blep_leaves_assignee_queue_untouched(self):
        """A blep by someone who is NOT the assignee is 'helping' — it must
        not renumber the assignee's queue. Only the assignee's own blep
        promotes their queue."""
        helper = User.objects.create_user(username='qhelper', password='x')
        target = self.tasks[1]  # T2, worker_queue=2, assigned to self.user
        Task.objects.filter(pk=target.task_id).update(
            status=Task.STATUS_IN_PROGRESS,
        )

        TaskLifecycleService.start_work(target.task_id, helper)

        # The assignee's queue is unchanged — no shuffle, T2 still at 2.
        for i, task in enumerate(self.tasks, start=1):
            self.assertEqual(
                Task.objects.get(pk=task.task_id).worker_queue, i,
                f'T{i} worker_queue should be unchanged by a non-assignee blep',
            )
        # The task stays assigned to its owner (helping, not takeover).
        self.assertEqual(
            Task.objects.get(pk=target.task_id).assignee_id, self.user.pk,
        )
