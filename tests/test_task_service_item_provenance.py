"""Task.service_item provenance: tasks generated from a ServiceItem record
which catalog service they instantiate, so the QBO invoice push can resolve
a task-sourced line to its mirrored QBO Item."""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import TaskService


class TaskServiceItemProvenanceTests(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.category = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True,
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-prov', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=self.category,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='CNC Cutting', is_active=True,
            rate_scheme=self.scheme,
        )

    def test_generate_task_stamps_service_item(self):
        task = self.service_item.generate_task(self.job, est_qty=Decimal('1'))
        self.assertEqual(task.service_item_id, self.service_item.pk)

    def test_copy_fields_carries_service_item(self):
        task = self.service_item.generate_task(self.job, est_qty=Decimal('1'))
        self.assertEqual(
            task.copy_fields()['service_item_id'], self.service_item.pk,
        )

    def test_taskservice_create_from_template_stamps_service_item(self):
        task = TaskService.create_from_template(self.service_item, self.job)
        self.assertEqual(task.service_item_id, self.service_item.pk)

    def test_hand_created_task_has_no_service_item(self):
        task = Task.objects.create(
            job=self.job, name='Ad hoc', rate_scheme=self.scheme,
        )
        self.assertIsNone(task.service_item_id)
