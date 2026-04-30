from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from apps.jobs.models import Job, Task, Blep
from apps.estimates.models import Estimate, TaskTemplate
from apps.contacts.models import Contact
from apps.core.models import User
from .base import FixtureTestCase


class JobModelFixtureTest(FixtureTestCase):
    """Test Job model using fixture data loaded from unit_test_data.json"""

    def test_jobs_exist_from_fixture(self):
        job1 = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(job1.status, Job.STATUS_DRAFT)
        self.assertEqual(job1.description, "Kitchen renovation project for residential client")
        self.assertIsNone(job1.completed_date)
        self.assertEqual(job1.contact.name, "John Doe")

        job2 = Job.objects.get(job_number="JOB-2024-0002")
        self.assertEqual(job2.status, Job.STATUS_COMPLETED)
        self.assertEqual(job2.description, "Office electrical upgrade")
        self.assertIsNotNone(job2.completed_date)
        self.assertEqual(job2.contact.name, "Jane Smith")

    def test_job_str_method_with_fixture_data(self):
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(str(job), "JOB-2024-0001")

    def test_job_contact_relationships(self):
        job1 = Job.objects.get(job_number="JOB-2024-0001")
        contact1 = Contact.objects.get(first_name="John", last_name="Doe")
        self.assertEqual(job1.contact, contact1)

    def test_job_status_progression(self):
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(job.status, Job.STATUS_DRAFT)

        job.status = Job.STATUS_SUBMITTED
        job.save()

        updated_job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(updated_job.status, Job.STATUS_SUBMITTED)

    def test_create_new_job_with_existing_contact(self):
        contact = Contact.objects.get(first_name="John", last_name="Doe")
        new_job = Job.objects.create(
            job_number="JOB-2024-0003",
            contact=contact,
            description="New project for existing customer",
            status=Job.STATUS_DRAFT
        )
        self.assertEqual(new_job.contact, contact)
        self.assertEqual(Job.objects.count(), 3)  # 2 from fixture + 1 new


class EstimateModelFixtureTest(FixtureTestCase):
    """Test Estimate model using fixture data"""

    def test_estimates_exist_from_fixture(self):
        est1 = Estimate.objects.get(estimate_number="EST-2024-0001")
        self.assertEqual(est1.version, 1)
        self.assertEqual(est1.status, Job.STATUS_DRAFT)
        self.assertEqual(est1.job.job_number, "JOB-2024-0001")

        est2 = Estimate.objects.get(estimate_number="EST-2024-0002", version=2)
        self.assertEqual(est2.version, 2)
        self.assertEqual(est2.status, Estimate.STATUS_ACCEPTED)
        self.assertEqual(est2.job.job_number, "JOB-2024-0002")

    def test_estimate_str_method_with_fixture_data(self):
        estimate = Estimate.objects.get(estimate_number="EST-2024-0001")
        self.assertEqual(str(estimate), "Estimate EST-2024-0001")

    def test_estimate_job_relationships(self):
        estimate = Estimate.objects.get(estimate_number="EST-2024-0001")
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(estimate.job, job)


class TaskModelFixtureTest(FixtureTestCase):
    """Test Task model using fixture data (tasks now belong directly to jobs)."""

    def test_tasks_exist_from_fixture(self):
        task1 = Task.objects.get(name="Kitchen demolition")
        self.assertEqual(task1.assignee.username, "manager1")
        self.assertEqual(task1.job.job_number, "JOB-2024-0001")

        task2 = Task.objects.get(name="Electrical rough-in")
        self.assertEqual(task2.assignee.username, "manager1")

    def test_task_str_method_with_fixture_data(self):
        task = Task.objects.get(name="Kitchen demolition")
        self.assertEqual(str(task), "Kitchen demolition")

    def test_task_user_relationships(self):
        task = Task.objects.get(name="Kitchen demolition")
        user = User.objects.get(username="manager1")
        self.assertEqual(task.assignee, user)

    def test_task_job_relationships(self):
        """Post-Phase-A: tasks are linked directly to jobs."""
        task = Task.objects.get(name="Kitchen demolition")
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(task.job, job)

    def test_create_new_task_for_existing_job(self):
        job = Job.objects.get(job_number="JOB-2024-0001")
        user = User.objects.get(username="manager1")

        new_task = Task.objects.create(
            assignee=user,
            job=job,
            name="Cabinet installation",
        )
        self.assertEqual(new_task.job, job)
        self.assertEqual(Task.objects.count(), 3)  # 2 from fixture + 1 new


class BlepModelFixtureTest(FixtureTestCase):
    """Test Blep model using fixture data"""

    def test_create_blep_for_existing_task(self):
        task = Task.objects.get(name="Kitchen demolition")
        user = User.objects.get(username="manager1")

        start_time = timezone.now()
        end_time = start_time + timedelta(hours=4)

        blep = Blep.objects.create(
            user=user,
            task=task,
            start_time=start_time,
            end_time=end_time
        )

        self.assertEqual(blep.task, task)
        self.assertEqual(blep.user, user)
        self.assertEqual(blep.start_time, start_time)
        self.assertEqual(blep.end_time, end_time)

    def test_blep_str_method_with_fixture_task(self):
        task = Task.objects.get(name="Kitchen demolition")
        blep = Blep.objects.create(task=task)
        expected_str = f"Blep {blep.pk} for Task {task.pk}"
        self.assertEqual(str(blep), expected_str)
