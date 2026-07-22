from decimal import Decimal
from unittest.mock import patch, MagicMock
from apps.core.models import JobHistory
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job, RateScheme
from apps.inventory.models import Material


# ---------------------------------------------------------------------------
# Shared fixture helpers for adjustment tests
# ---------------------------------------------------------------------------

def _make_adjustment_fixture(test_case):
    """Create job + estimate + accepted estimate + accounting cats + PERCENTAGE
    service on test_case. Returns (job, cat, svc, estimate).
    Called from setUp; populates test_case attributes."""
    from apps.contacts.models import Contact
    from apps.core.models import AccountingCategory
    from apps.estimates.models import Estimate, EstimateLineItem

    contact = Contact.objects.create(
        first_name='Adj', last_name='Test',
        email='adj@test.com', mobile_number='555-0001',
    )
    cat = AccountingCategory.objects.create(name='AdjCat', code='ADJC')
    svc = RateScheme.objects.create(
        name='Rush Fee', algorithm=RateScheme.PERCENTAGE,
        rate=Decimal('10.00'), unit_label='%',
        accounting_category=cat,
    )
    job = Job.objects.create(
        contact=contact, status=Job.STATUS_APPROVED,
        job_number='JOB-ADJ-001',
    )
    estimate = Estimate.objects.create(
        job=job, status=Estimate.STATUS_ACCEPTED,
        estimate_number='EST-ADJ-001',
    )
    # one normal line + one adjustment line
    base_line = EstimateLineItem.objects.create(
        estimate=estimate, line_number=1,
        qty=Decimal('1'), units='hours',
        description='Labor', price=Decimal('100.00'),
        accounting_category=cat,
    )
    adj_line = EstimateLineItem.objects.create(
        estimate=estimate, line_number=2,
        qty=Decimal('1'), units='%',
        description='Rush Fee', price=Decimal('10.00'),
        accounting_category=cat,
        adjustment_service=svc,
    )
    adj_line.adjustment_target_categories.set([cat.pk])

    test_case.adj_contact = contact
    test_case.adj_cat = cat
    test_case.adj_svc = svc
    test_case.adj_job = job
    test_case.adj_estimate = estimate
    test_case.adj_base_line = base_line
    test_case.adj_adj_line = adj_line


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

    def test_invoice_payload_carries_authoritative_total(self):
        """The job-overview Invoicing block reads invoice.total; the full
        (non-summary) list/detail serializer must supply the summed line total
        (qty*price, matching InvoiceSummarySerializer.total_anno and
        financials._invoiced), not leave the SPA to recompute from line items
        (adjustment/percentage lines make client qty*price fragile)."""
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-TOTAL-001', status=Invoice.STATUS_DRAFT,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, qty=Decimal('2'),
            units='hours', description='Labor', price=Decimal('100.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, line_number=2, qty=Decimal('1'),
            units='ea', description='Part', price=Decimal('50.00'),
        )
        response = self.client.get(f'/api/invoices/?job={job.pk}')
        self.assertEqual(response.status_code, 200)
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        row = next(r for r in results if r['invoice_id'] == invoice.pk)
        self.assertEqual(str(row['total']), '250.00')

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
        # Every line needs an accounting category or the send-gate blocks it.
        from apps.core.models import AccountingCategory
        send_cat = AccountingCategory.objects.create(
            name='Send Test', code='SNDT',
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=Decimal('1.00'),
            price=Decimal('100.00'), description='Test',
            accounting_category=send_cat,
        )

    def test_send_defaults_returns_form_prefills(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('to', response.data)
        self.assertIn('subject', response.data)
        self.assertIn('body', response.data)
        self.assertIn('attachments_preview', response.data)
        # One auto-attached PDF: the QBO invoice (the Job Statement was
        # dropped from the send 2026-07-22).
        filenames = [a['filename'] for a in response.data['attachments_preview']]
        self.assertEqual(len(filenames), 1)
        self.assertTrue(filenames[0].startswith('Invoice-'))

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
        qbo_invoice.DocNumber = '1042'
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

    def test_unconsumed_material_not_billable_regardless_of_parent_task(self):
        """Material is not_billable because it is unconsumed — not because of
        the parent task's status.  The pending_material is attached to the
        incomplete_task, but the gate keys only on its own consumption_state."""
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        mat_atom = self._find_atom(pool, 'material', self.pending_material.pk)
        self.assertEqual(mat_atom['state'], 'not_billable')

    def test_consumed_material_on_incomplete_task_is_available(self):
        """Key invariant: a CONSUMED material on an INCOMPLETE task must be
        'available' in the source pool — the material gate never looks at the
        parent task's status, only at the material's own consumption_state."""
        from apps.inventory.models import InventoryItem
        from apps.invoicing.services import InvoiceWizardService

        pli = InventoryItem.objects.filter(
            accounting_category=self.cat,
        ).first()
        consumed_on_incomplete = Material.objects.create(
            job=self.job, task=self.incomplete_task,
            description='Consumed-on-incomplete Ply', quantity=Decimal('3.00'),
            sell_price=Decimal('10.00'), inventory_item=pli,
            accounting_category=self.cat,
        )
        consumed_on_incomplete.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        consumed_on_incomplete.save(update_fields=['consumption_state'])

        pool = InvoiceWizardService.get_source_pool(self.invoice)
        mat_atom = self._find_atom(pool, 'material', consumed_on_incomplete.pk)
        self.assertIsNotNone(mat_atom, 'consumed material must appear in pool')
        self.assertEqual(mat_atom['state'], 'available')

    def test_append_atoms_rejects_incomplete_task(self):
        """add_atoms_to_line_item (append path) must also reject a non-complete task."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService

        # Build an existing draft line item by adding a legitimately-billable atom.
        existing_li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': self.complete_task.pk}],
        )
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_line_item(
                existing_li, [{'type': 'task', 'id': self.incomplete_task.pk}],
            )

    def test_append_atoms_rejects_unconsumed_material(self):
        """add_atoms_to_line_item (append path) must also reject an unconsumed material."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService

        # Build an existing draft line item by adding a legitimately-billable atom.
        existing_li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'material', 'id': self.consumed_material.pk}],
        )
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_line_item(
                existing_li, [{'type': 'material', 'id': self.pending_material.pk}],
            )


# ---------------------------------------------------------------------------
# Task 7: compose_agreement adjustment surfacing
# ---------------------------------------------------------------------------

class ComposeAgreementAdjustmentTest(BaseTestCase):
    """compose_agreement must surface is_adjustment / adjustment_service_id /
    percent / target_category_ids on estimate-origin lines."""

    def setUp(self):
        super().setUp()
        _make_adjustment_fixture(self)

    def test_compose_agreement_marks_adjustment_lines(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.adj_job)
        adj = [l for l in result['lines'] if l.get('is_adjustment')]
        self.assertEqual(len(adj), 1)
        self.assertIn('adjustment_service_id', adj[0])
        self.assertIn('percent', adj[0])

    def test_compose_agreement_adjustment_fields_values(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.adj_job)
        adj = [l for l in result['lines'] if l.get('is_adjustment')][0]
        self.assertEqual(adj['adjustment_service_id'], self.adj_svc.pk)
        self.assertEqual(adj['percent'], self.adj_svc.rate)
        self.assertIn(self.adj_cat.pk, adj['target_category_ids'])

    def test_compose_agreement_non_adjustment_lines_have_falsey_is_adjustment(self):
        from apps.estimates.agreement import compose_agreement
        result = compose_agreement(self.adj_job)
        non_adj = [l for l in result['lines'] if not l.get('is_adjustment')]
        self.assertTrue(len(non_adj) >= 1)
        for line in non_adj:
            self.assertFalse(line.get('is_adjustment'))
            self.assertIsNone(line.get('adjustment_service_id'))
            self.assertEqual(line.get('target_category_ids'), [])


# ---------------------------------------------------------------------------
# Task 7: InvoiceService adjustment methods (service layer)
# ---------------------------------------------------------------------------

class InvoiceAdjustmentServiceTest(BaseTestCase):
    """InvoiceService.add_adjustment_line and auto-recompute."""

    def setUp(self):
        super().setUp()
        _make_adjustment_fixture(self)
        self.invoice = Invoice.objects.create(
            job=self.adj_job, status=Invoice.STATUS_DRAFT,
        )
        # seed a base line so recompute has something to sum
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1,
            qty=Decimal('1'), units='hours',
            description='Labor', price=Decimal('200.00'),
            accounting_category=self.adj_cat,
        )

    def test_add_adjustment_line_creates_line(self):
        from apps.invoicing.services import InvoiceService
        line = InvoiceService.add_adjustment_line(
            self.invoice,
            adjustment_service_id=self.adj_svc.pk,
            target_category_ids=[self.adj_cat.pk],
        )
        self.assertIsNotNone(line.pk)
        self.assertEqual(line.adjustment_service_id, self.adj_svc.pk)

    def test_add_adjustment_line_computes_price(self):
        from apps.invoicing.services import InvoiceService
        line = InvoiceService.add_adjustment_line(
            self.invoice,
            adjustment_service_id=self.adj_svc.pk,
            target_category_ids=[self.adj_cat.pk],
        )
        # 10% of $200 = $20
        self.assertEqual(line.price, Decimal('20.00'))

    def test_add_adjustment_line_rejects_non_draft(self):
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceService
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)
        self.invoice.refresh_from_db()
        with self.assertRaises(ValidationError):
            InvoiceService.add_adjustment_line(
                self.invoice,
                adjustment_service_id=self.adj_svc.pk,
            )

    def test_add_adjustment_line_rejects_non_percentage_service(self):
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceService
        from apps.core.models import AccountingCategory
        flat_svc = RateScheme.objects.create(
            name='Flat Labor', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='ea',
            accounting_category=self.adj_cat,
        )
        with self.assertRaises(ValidationError):
            InvoiceService.add_adjustment_line(
                self.invoice,
                adjustment_service_id=flat_svc.pk,
            )


# ---------------------------------------------------------------------------
# Task 7: Invoice API actions for adjustments
# ---------------------------------------------------------------------------

class InvoiceAdjustmentAPITest(BaseTestCase):
    """POST /api/invoices/{id}/adjustment-lines/ and
    GET  /api/invoices/{id}/agreement-adjustments/"""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        _make_adjustment_fixture(self)
        self.invoice = Invoice.objects.create(
            job=self.adj_job, status=Invoice.STATUS_DRAFT,
        )
        # seed a base line for adjustment to sum
        self.base_li = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1,
            qty=Decimal('1'), units='hours',
            description='Labor', price=Decimal('200.00'),
            accounting_category=self.adj_cat,
        )

    def test_post_adjustment_lines_returns_201(self):
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/adjustment-lines/',
            {
                'adjustment_service': self.adj_svc.pk,
                'target_category_ids': [self.adj_cat.pk],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('line_item_id', resp.data)
        self.assertEqual(resp.data['adjustment_service'], self.adj_svc.pk)

    def test_post_adjustment_lines_non_draft_returns_400(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/adjustment-lines/',
            {'adjustment_service': self.adj_svc.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_recalculate_endpoint_removed(self):
        """The recalculate endpoint no longer exists (adjustments auto-recompute)."""
        from apps.invoicing.services import InvoiceService
        adj_line = InvoiceService.add_adjustment_line(
            self.invoice,
            adjustment_service_id=self.adj_svc.pk,
            target_category_ids=[self.adj_cat.pk],
        )
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{adj_line.pk}/recalculate/',
        )
        self.assertEqual(resp.status_code, 404)

    def test_agreement_adjustments_lists_adjustments(self):
        resp = self.client.get(
            f'/api/invoices/{self.invoice.pk}/agreement-adjustments/',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        adjustments = resp.data['adjustments']
        self.assertEqual(len(adjustments), 1)
        adj = adjustments[0]
        self.assertEqual(adj['adjustment_service_id'], self.adj_svc.pk)
        self.assertIn('percent', adj)
        self.assertIn('target_category_ids', adj)

    def test_agreement_adjustments_already_added_false_initially(self):
        resp = self.client.get(
            f'/api/invoices/{self.invoice.pk}/agreement-adjustments/',
        )
        self.assertEqual(resp.status_code, 200)
        adj = resp.data['adjustments'][0]
        self.assertFalse(adj['already_added'])

    def test_agreement_adjustments_already_added_true_after_adding(self):
        from apps.invoicing.services import InvoiceService
        InvoiceService.add_adjustment_line(
            self.invoice,
            adjustment_service_id=self.adj_svc.pk,
        )
        resp = self.client.get(
            f'/api/invoices/{self.invoice.pk}/agreement-adjustments/',
        )
        self.assertEqual(resp.status_code, 200)
        adj = resp.data['adjustments'][0]
        self.assertTrue(adj['already_added'])
