from decimal import Decimal
from unittest.mock import patch, MagicMock
from apps.core.models import JobHistory
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job, RateScheme
from apps.inventory.models import Material


class InvoiceAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_invoices(self):
        response = self.client.get('/api/invoices/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_invoice(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.get(f'/api/invoices/{invoice.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_add_line_item(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-LI', status=Invoice.STATUS_DRAFT,
        )
        response = self.client.post(f'/api/invoices/{invoice.pk}/line-items/', {
            'qty': '1.00',
            'units': 'hours',
            'description': 'Consulting',
            'price': '150.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_cancel_invoice_requires_reason(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.post(f'/api/invoices/{invoice.pk}/cancel/', {}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_cancel_invoice_creates_history(self):
        invoice = Invoice.objects.filter(status='active').first()
        if invoice:
            self.client.post(f'/api/invoices/{invoice.pk}/cancel/', {
                'reason': 'Billed in error',
            }, format='json')
            entry = JobHistory.objects.filter(
                entry_type='audit', object_type='invoice', object_id=invoice.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'Billed in error')
            self.assertEqual(entry.user, self.user)

    def test_discard_draft_returns_200_with_message(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DISCARD-001', status=Invoice.STATUS_DRAFT,
        )
        pk = invoice.pk
        response = self.client.delete(f'/api/invoices/{pk}/?confirm=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Invoice.objects.filter(pk=pk).exists())

    def test_discard_non_draft_returns_400(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DISCARD-002', status=Invoice.STATUS_DRAFT,
        )
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_OPEN)
        response = self.client.delete(f'/api/invoices/{invoice.pk}/?confirm=true')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_due_date_and_is_late_for_unsent_invoice(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-001', status=Invoice.STATUS_DRAFT,
        )
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['due_date'])
        self.assertFalse(response.data['is_late'])

    def test_due_date_30_days_after_sent_and_late_when_unpaid(self):
        from datetime import timedelta
        from django.utils import timezone
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-002', status=Invoice.STATUS_OPEN,
        )
        sent = timezone.now() - timedelta(days=45)
        Invoice.objects.filter(pk=invoice.pk).update(sent_date=sent)
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        body = response.json()
        expected_due = (sent + timedelta(days=30)).date().isoformat()
        self.assertEqual(body['due_date'], expected_due)
        self.assertTrue(body['is_late'])

    def test_paid_invoice_is_not_late(self):
        from datetime import timedelta
        from django.utils import timezone
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-003', status=Invoice.STATUS_PAID,
        )
        sent = timezone.now() - timedelta(days=45)
        Invoice.objects.filter(pk=invoice.pk).update(sent_date=sent)
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        self.assertFalse(response.json()['is_late'])


class InvoiceSendTest(BaseTestCase):
    """New /api/invoices/{id}/send-defaults/ + /send/ endpoints. The send
    orchestrates QBO push (if qbo_id not already set), PDF rendering, and
    OutboundEmailService.send_tracked."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.job = Job.objects.first()
        from decimal import Decimal
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-SEND-001',
            status=Invoice.STATUS_DRAFT,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=Decimal('1.00'),
            price=Decimal('100.00'), description='Test',
        )

    def test_send_defaults_returns_form_prefills(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('to', response.data)
        self.assertIn('subject', response.data)
        self.assertIn('body', response.data)
        self.assertIn('attachments_preview', response.data)
        # Two auto-attached PDFs: the QBO invoice + the local Job Statement.
        filenames = [a['filename'] for a in response.data['attachments_preview']]
        self.assertEqual(len(filenames), 2)

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice')
    @patch('apps.qbo.services.QBOInvoiceSyncService._mark_as_sent')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_happy_path(
        self, MockEmailMessage, mock_stmt_pdf, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        MockEmailMessage.return_value = MagicMock()
        mock_stmt_pdf.return_value = b'%PDF-stmt'
        mock_dl_pdf.return_value = b'%PDF-qbo'
        qbo_invoice = MagicMock()
        qbo_invoice.Id = '42'
        qbo_invoice.save = MagicMock(return_value=qbo_invoice)
        mock_build.return_value = qbo_invoice
        mock_get_client.return_value = MagicMock()

        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {
                'to': 'customer@example.com',
                'subject': 'Invoice INV-SEND-001',
                'body': 'Pay link inside.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_OPEN)
        self.assertEqual(self.invoice.qbo_id, '42')

        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice')
    @patch('apps.qbo.services.QBOInvoiceSyncService._mark_as_sent')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_with_qbo_id_set_skips_qbo_push(
        self, MockEmailMessage, mock_stmt_pdf, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        """Retry: qbo_id already set means skip the QBO push step (fixes
        the duplicate-push bug in the old code)."""
        self.invoice.qbo_id = '99'
        self.invoice.save()

        MockEmailMessage.return_value = MagicMock()
        mock_stmt_pdf.return_value = b'%PDF-stmt'
        mock_dl_pdf.return_value = b'%PDF-qbo'
        mock_get_client.return_value = MagicMock()

        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {'to': 'customer@example.com', 'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        # The build-QBO-invoice path should NOT have been called.
        mock_build.assert_not_called()
        mock_mark.assert_not_called()

        # PDF download still happens; outbound EmailRecord still created.
        mock_dl_pdf.assert_called_once()
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)

    def test_send_missing_to_returns_400(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class BillabilityGateTest(BaseTestCase):
    """Task 5: incomplete tasks and unconsumed materials are not billable."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from apps.contacts.models import Contact
        from apps.jobs.models import Task
        from apps.inventory.models import InventoryItem

        super().setUp()

        self.contact = Contact.objects.create(
            first_name='Bill', last_name='Test',
            email='bill@test.com', mobile_number='555-9999',
        )
        self.cat = AccountingCategory.objects.create(name='BillCat', code='BCAT')
        self.scheme = RateScheme.objects.create(
            name='Hourly-bill', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hours',
            accounting_category=self.cat,
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-BILL-001',
        )

        # An incomplete (pending) task — must appear as not_billable
        self.incomplete_task = Task.objects.create(
            job=self.job, name='Pending Work', rate_scheme=self.scheme,
        )
        # Status is STATUS_PENDING by default — don't change it.

        # A complete task — for contrast
        self.complete_task = Task.objects.create(
            job=self.job, name='Done Work', rate_scheme=self.scheme,
        )
        self.complete_task.status = Task.STATUS_COMPLETE
        self.complete_task.save()

        pli = InventoryItem.objects.create(
            code='BCAT-PLY', description='Plywood',
            selling_price=Decimal('10.00'),
            accounting_category=self.cat,
        )

        # A pending (unconsumed) material on the incomplete task
        self.pending_material = Material.objects.create(
            job=self.job, task=self.incomplete_task,
            description='Pending Ply', quantity=Decimal('2.00'),
            sell_price=Decimal('10.00'), inventory_item=pli,
            accounting_category=self.cat,
        )
        # consumption_state is PENDING by default — don't change it.

        # A consumed material (on the complete task) — for contrast.
        # Set consumption_state directly via update_fields to bypass inventory
        # on-hand checks in MaterialService.consume (test fixture only).
        self.consumed_material = Material.objects.create(
            job=self.job, task=self.complete_task,
            description='Used Ply', quantity=Decimal('1.00'),
            sell_price=Decimal('10.00'), inventory_item=pli,
            accounting_category=self.cat,
        )
        self.consumed_material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        self.consumed_material.save(update_fields=['consumption_state'])

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def _find_atom(self, pool, atom_type, atom_id):
        """Walk pool['tasks'][*]['atoms'] for a matching type+id."""
        for group in pool['tasks']:
            for atom in group['atoms']:
                if atom['type'] == atom_type and atom['id'] == atom_id:
                    return atom
        return None

    def test_source_pool_marks_incomplete_task_not_billable(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        task_atom = self._find_atom(pool, 'task', self.incomplete_task.pk)
        self.assertIsNotNone(task_atom, 'incomplete task must appear in pool')
        self.assertEqual(task_atom['state'], 'not_billable')
        self.assertEqual(task_atom['not_billable_reason'], 'task_incomplete')

    def test_source_pool_marks_pending_material_not_billable(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        mat_atom = self._find_atom(pool, 'material', self.pending_material.pk)
        self.assertIsNotNone(mat_atom, 'pending material must appear in pool')
        self.assertEqual(mat_atom['state'], 'not_billable')
        self.assertEqual(mat_atom['not_billable_reason'], 'material_unconsumed')

    def test_source_pool_complete_task_available(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        task_atom = self._find_atom(pool, 'task', self.complete_task.pk)
        self.assertIsNotNone(task_atom, 'complete task must appear in pool')
        self.assertEqual(task_atom['state'], 'available')

    def test_source_pool_consumed_material_available(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        mat_atom = self._find_atom(pool, 'material', self.consumed_material.pk)
        self.assertIsNotNone(mat_atom, 'consumed material must appear in pool')
        self.assertEqual(mat_atom['state'], 'available')

    def test_add_atoms_rejects_incomplete_task(self):
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.invoice, [{'type': 'task', 'id': self.incomplete_task.pk}],
            )

    def test_add_atoms_rejects_unconsumed_material(self):
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.invoice, [{'type': 'material', 'id': self.pending_material.pk}],
            )

    def test_add_atoms_accepts_complete_task(self):
        from apps.invoicing.services import InvoiceWizardService
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': self.complete_task.pk}],
        )
        self.assertIsNotNone(li)
        self.assertEqual(li.sources.count(), 1)

    def test_add_atoms_accepts_consumed_material(self):
        from apps.invoicing.services import InvoiceWizardService
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'material', 'id': self.consumed_material.pk}],
        )
        self.assertIsNotNone(li)
        self.assertEqual(li.sources.count(), 1)

    def test_not_billable_atom_dict_has_not_billable_reason_key(self):
        """Every atom dict carries not_billable_reason — None for available atoms."""
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        complete_atom = self._find_atom(pool, 'task', self.complete_task.pk)
        self.assertIn('not_billable_reason', complete_atom)
        self.assertIsNone(complete_atom['not_billable_reason'])

    def test_incomplete_task_child_material_is_not_billable(self):
        """Material on an incomplete task is not_billable (unconsumed)."""
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        mat_atom = self._find_atom(pool, 'material', self.pending_material.pk)
        self.assertEqual(mat_atom['state'], 'not_billable')
