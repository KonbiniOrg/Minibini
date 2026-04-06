"""
Tests for earmark release when a WorkOrder is completed.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, WorkOrder, Task
from apps.jobs.services import WorkOrderService
from apps.inventory.models import Material, PriceListItem, Earmark


class EarmarkReleaseOnWOCompleteTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-REL-001', contact=self.contact,
        )
        self.plywood = PriceListItem.objects.create(
            code='PLY.REL', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_inventoried=True,
        )

    def test_earmarks_released_on_wo_complete(self):
        """Remaining earmarks for the job are deleted when WO is completed."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_partial_earmark_released_on_complete(self):
        """Even partially consumed earmarks are cleaned up."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('1.50'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_error_when_no_earmarks_on_complete(self):
        """Completing a WO with no earmarks doesn't error."""
        wo = WorkOrder.objects.create(job=self.job)

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_other_job_earmarks_untouched(self):
        """Completing one job's WO doesn't affect another job's earmarks."""
        other_job = Job.objects.create(
            job_number='J-REL-002', contact=self.contact,
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=other_job,
            quantity=Decimal('5.00'),
        )
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Earmark.objects.filter(job=other_job).count(), 1)

    def test_blocking_wo_does_not_release_earmarks(self):
        """Blocking a WO does NOT release earmarks — only completion does."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_BLOCKED)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)
