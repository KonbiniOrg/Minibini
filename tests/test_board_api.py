from tests.base import FixtureTestCase
from apps.jobs.models import Task, WorkOrder, Job
from apps.contacts.models import Contact


class TaskWorkerQueueTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import Configuration
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001',
            name='Test Job',
            status='approved',
            contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)

    def test_task_worker_queue_field_exists(self):
        task = Task(
            name='Test task',
            work_order=self.wo,
            worker_queue=5,
        )
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.worker_queue, 5)

    def test_task_worker_queue_nullable(self):
        task = Task(
            name='Test task',
            work_order=self.wo,
            worker_queue=None,
        )
        task.save()
        task.refresh_from_db()
        self.assertIsNone(task.worker_queue)
