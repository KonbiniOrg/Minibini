"""Task deletion guards (plan B5): open to any authenticated user, but
refused when the task has a consumed material or the job is terminal;
pending materials detach to the job as loose rows.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import Material
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import TaskService


class TaskDeleteGuardsTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='D', last_name='G')
        self.job = Job.objects.create(
            job_number='DEL-001', name='Delete Job', contact=self.contact,
        )
        self.ac = AccountingCategory.objects.create(code='DEL', name='Del AC')
        self.scheme = RateScheme.objects.create(
            name='S-del', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=self.ac,
        )
        self.task = Task(
            job=self.job, name='Doomed',
        )
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

    def test_consumed_material_blocks_delete(self):
        Material.objects.create(
            job=self.job, task=self.task, description='Hand-consumed',
            quantity=Decimal('1'), accounting_category=self.ac,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.task.pk)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_pending_material_detaches_to_loose(self):
        material = Material.objects.create(
            job=self.job, task=self.task, description='Planned stock',
            quantity=Decimal('2'), accounting_category=self.ac,
        )
        TaskService.delete_task(self.task.pk)
        material.refresh_from_db()
        self.assertIsNone(material.task)
        self.assertEqual(material.job, self.job)

    def test_terminal_job_blocks_delete(self):
        self.job.status = Job.STATUS_REJECTED
        self.job.save()
        with self.assertRaises(ValidationError):
            TaskService.delete_task(self.task.pk)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_plain_delete_still_works(self):
        TaskService.delete_task(self.task.pk)
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())
