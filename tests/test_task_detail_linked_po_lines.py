"""Fix 2b (RM browser-testing): a task with PO lines attributing cost to it
showed nothing on its own detail page — the reverse direction of Fix 2a's
`task_detail` on POLineItemSerializer. `linked_po_lines` is detail-only
(TaskDetailSerializer), matching this file's `/api/tasks/{id}/` surface."""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, Task
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.core.models import Configuration, AppState

User = get_user_model()


class TaskDetailLinkedPOLinesTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.worker = User.objects.create_user(username='worker', password='testpass')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.task = Task.objects.create(job=self.job, name='Mill part')
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.client.login(username='worker', password='testpass')

    def test_linked_po_lines_lists_the_attributing_po(self):
        PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('1.00'),
            price=Decimal('20.00'), task=self.task.pk,
        )
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(len(body['linked_po_lines']), 1)
        entry = body['linked_po_lines'][0]
        self.assertEqual(entry['po_id'], self.po.pk)
        self.assertEqual(entry['po_number'], self.po.po_number)
        self.assertEqual(entry['po_status'], self.po.status)

    def test_task_with_no_po_lines_has_empty_list(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['linked_po_lines'], [])
