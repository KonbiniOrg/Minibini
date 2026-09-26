"""Fix 2a (RM browser-testing): a PO line's task link was invisible in the
API response — the SPA had no data to render a chip from. `task_detail`
mirrors the existing `material` nested-display convention on
POLineItemSerializer."""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, Task
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.api.purchasing.serializers import POLineItemSerializer
from apps.core.models import Configuration, AppState


class POSerializerTaskDetailTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.task = Task.objects.create(job=self.job, name='Mill part')
        self.po = PurchaseOrder.objects.create(business=self.business)

    def test_task_linked_line_exposes_task_detail(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('1.00'),
            price=Decimal('20.00'), task=self.task.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertEqual(data['task'], self.task.pk)
        self.assertIsNotNone(data['task_detail'])
        self.assertEqual(data['task_detail']['task_id'], self.task.pk)
        self.assertEqual(data['task_detail']['name'], 'Mill part')
        self.assertEqual(data['task_detail']['job_id'], self.job.pk)
        self.assertEqual(data['task_detail']['job_number'], self.job.job_number)

    def test_unlinked_line_has_null_task_detail(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('1.00'),
            price=Decimal('20.00'),
        )
        data = POLineItemSerializer(line).data
        self.assertIsNone(data['task'])
        self.assertIsNone(data['task_detail'])
