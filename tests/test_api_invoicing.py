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
        qty=Decimal('1'), units='hour',
        description='Labor', price=Decimal('100.00'),
        accounting_category=cat,
    )
    adj_line = EstimateLineItem.objects.create(
        estimate=estimate, line_number=2,
        qty=Decimal('1'), units='%',
        description='Rush Fee', price=Decimal('10.00'),
        accounting_category=cat,
        adjustment_service=svc,
        adjustment_percent=svc.rate,
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
            'units': 'hour',
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
            units='hour', description='Labor', price=Decimal('100.00'),
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
    @patch('django.core.mail.EmailMessage')
    def test_send_happy_path(
        self, MockEmailMessage, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        MockEmailMessage.return_value = MagicMock()
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
    @patch('django.core.mail.EmailMessage')
    def test_send_with_qbo_id_set_skips_qbo_push(
        self, MockEmailMessage, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        """Retry: qbo_id already set means skip the QBO push step (fixes
        the duplicate-push bug in the old code)."""
        self.invoice.qbo_id = '99'
        self.invoice.save()

        MockEmailMessage.return_value = MagicMock()
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
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-BILL-001',
        )

        # An incomplete (pending) task — must appear as not_billable
        self.incomplete_task = Task(job=self.job, name='Pending Work')
        self.incomplete_task.stamp_from_scheme(self.scheme)
        self.incomplete_task.save()
        # Status is STATUS_PENDING by default — don't change it.

        # A complete task — for contrast
        self.complete_task = Task(job=self.job, name='Done Work')
        self.complete_task.stamp_from_scheme(self.scheme)
        self.complete_task.save()
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
            qty=Decimal('1'), units='hour',
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
            qty=Decimal('1'), units='hour',
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


# ---------------------------------------------------------------------------
# Task 4 (better-fees skeleton phase): auto-seed on creation, seed:false
# opt-out, remaining-agreement-lines + restore-line endpoints.
# ---------------------------------------------------------------------------

class InvoiceAutoSeedAPITest(BaseTestCase):
    """POST /api/invoices/ auto-seeds a new draft from the job's agreement
    unless seed:false; GET .../remaining-agreement-lines/ and
    POST .../restore-line/ round-trip a removed line back onto the draft."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        from apps.contacts.models import Contact
        from apps.core.models import AccountingCategory
        from apps.estimates.models import Estimate, EstimateLineItem

        contact = Contact.objects.create(
            first_name='Seed', last_name='API',
            email='seed-api@test.com', mobile_number='555-0200',
        )
        self.cat = AccountingCategory.objects.create(
            code='LAB-SEEDAPI', name='Labor-SeedAPI', taxable=False,
        )

        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED,
            job_number='JOB-SEEDAPI-0001',
        )
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SEEDAPI-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        for n, desc in enumerate(['Labor', 'Materials', 'Delivery'], start=1):
            EstimateLineItem.objects.create(
                estimate=est, line_number=n, qty=Decimal('1'),
                units='ea', description=desc, price=Decimal('100.00'),
                accounting_category=self.cat,
            )

        # A job with no accepted estimate at all — compose_agreement returns
        # no lines, so seeding it produces an empty draft either way.
        self.bare_job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED,
            job_number='JOB-SEEDAPI-0002',
        )

    def _seeded_via_api(self):
        resp = self.client.post(
            '/api/invoices/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return Invoice.objects.get(pk=resp.data['invoice_id'])

    def test_create_invoice_auto_seeds_from_agreement(self):
        resp = self.client.post(
            '/api/invoices/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201)
        inv = Invoice.objects.get(pk=resp.data['invoice_id'])
        self.assertEqual(inv.invoicelineitem_set.count(), 3)

    def test_create_with_seed_false_stays_empty(self):
        resp = self.client.post(
            '/api/invoices/', {'job': self.job.pk, 'seed': False},
            format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        inv = Invoice.objects.get(pk=resp.data['invoice_id'])
        self.assertEqual(inv.invoicelineitem_set.count(), 0)

    def test_estimate_less_job_seeds_empty(self):
        resp = self.client.post(
            '/api/invoices/', {'job': self.bare_job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        inv = Invoice.objects.get(pk=resp.data['invoice_id'])
        self.assertEqual(inv.invoicelineitem_set.count(), 0)

    def test_remaining_agreement_lines_endpoint(self):
        inv = self._seeded_via_api()
        li = inv.invoicelineitem_set.first()
        self.client.delete(
            f'/api/invoices/{inv.pk}/line-items/{li.pk}/?confirm=true')
        resp = self.client.get(
            f'/api/invoices/{inv.pk}/remaining-agreement-lines/')
        self.assertEqual(resp.status_code, 200, resp.data)
        remaining_ids = [
            l['estimate_line_id'] for l in resp.data['lines']]
        self.assertEqual(remaining_ids, [li.agreement_estimate_line_id])

    def test_restore_line_endpoint(self):
        inv = self._seeded_via_api()
        li = inv.invoicelineitem_set.first()
        self.client.delete(
            f'/api/invoices/{inv.pk}/line-items/{li.pk}/?confirm=true')
        self.assertEqual(inv.invoicelineitem_set.count(), 2)
        resp = self.client.post(
            f'/api/invoices/{inv.pk}/restore-line/',
            {'estimate_line_id': li.agreement_estimate_line_id},
            format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(inv.invoicelineitem_set.count(), 3)

    def test_delete_line_item_releases_agreement_reference(self):
        """The generic line-item DELETE path (LineItemMixin) must route
        through InvoiceService.remove_line so the removed line's agreement
        reference reappears as remaining — not just disappear from the
        draft while still being claimed."""
        inv = self._seeded_via_api()
        li = inv.invoicelineitem_set.first()
        estimate_line_id = li.agreement_estimate_line_id
        resp = self.client.delete(
            f'/api/invoices/{inv.pk}/line-items/{li.pk}/?confirm=true')
        self.assertEqual(resp.status_code, 200)
        from apps.invoicing.services import InvoiceService
        remaining_ids = [
            l['estimate_line_id']
            for l in InvoiceService.remaining_agreement_lines(self.job)
        ]
        self.assertIn(estimate_line_id, remaining_ids)


class InvoiceLineBackingAPITest(BaseTestCase):
    """derive_backing / agreement_ref / actuals_total on
    GET /api/invoices/{id}/line-items/ (InvoiceLineItemSerializer)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        from apps.contacts.models import Contact
        from apps.core.models import AccountingCategory
        from apps.estimates.models import Estimate, EstimateLineItem

        self.contact = Contact.objects.create(
            first_name='Backing', last_name='Test',
            email='backing@test.com', mobile_number='555-0300',
        )
        self.cat = AccountingCategory.objects.create(
            code='LAB-BACK', name='Labor-Backing', taxable=False,
        )
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP-BACK', name='Deposits-Backing', taxable=False,
            is_deposit=True,
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-BACK-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-BACK-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.est_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1,
            qty=Decimal('2'), units='hour',
            description='Labor', price=Decimal('50.00'),
            accounting_category=self.cat,
        )

    def _row(self, invoice, line_item):
        resp = self.client.get(f'/api/invoices/{invoice.pk}/line-items/')
        self.assertEqual(resp.status_code, 200, resp.data)
        return next(r for r in resp.data if r['line_item_id'] == line_item.pk)

    def _completed_task(self, name, scheme, hours):
        from datetime import timedelta
        from django.utils import timezone
        from apps.jobs.models import Task, Blep

        task = Task(job=self.job, name=name)
        task.stamp_from_scheme(scheme)
        task.save()
        now = timezone.now()
        Blep.objects.create(
            task=task, user=self.user,
            start_time=now - timedelta(hours=hours), end_time=now,
        )
        task.status = Task.STATUS_COMPLETE
        task.save()
        return task

    def test_backing_estimate_on_untouched_seeded_line(self):
        """A seeded, untouched agreement-backed line: agreement_ref set, no
        sources, qty/price match the referenced estimate line -> 'estimate'."""
        from apps.invoicing.services import InvoiceService

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.seed_from_agreement(invoice)
        li = invoice.invoicelineitem_set.get()

        row = self._row(invoice, li)
        self.assertEqual(row['backing'], 'estimate')
        self.assertIsNotNone(row['agreement_ref'])
        self.assertEqual(row['agreement_ref']['kind'], 'estimate')
        self.assertEqual(row['agreement_ref']['line_id'], self.est_line.pk)
        # Pin the JSON TYPE, not just the numeric value: a bare Decimal
        # embedded in a SerializerMethodField dict bypasses DecimalField's
        # to-string coercion and DRF's raw JSONEncoder floats it instead
        # (see _agreement_ref_payload's docstring) — `Decimal(x) ==
        # Decimal('2.00')` would pass identically whether `x` is the
        # string '2.00' or the float 2.0, so it can't catch that
        # regression. Assert the wire value IS the string.
        self.assertEqual(row['agreement_ref']['est_qty'], '2.00')
        self.assertEqual(row['agreement_ref']['est_price'], '50.00')
        self.assertEqual(row['agreement_ref']['est_amount'], '100.00')
        self.assertIsInstance(row['agreement_ref']['est_qty'], str)
        self.assertIsInstance(row['agreement_ref']['est_price'], str)
        self.assertIsInstance(row['agreement_ref']['est_amount'], str)
        self.assertIsNone(row['actuals_total'])

    def test_use_estimate_patch_accepts_the_agreement_ref_values_verbatim(self):
        """Regression guard for the float-PATCH bug: PATCHing a line's
        qty/price back to agreement_ref's own est_qty/est_price (exactly
        what the frontend's "Use estimate" control sends) must succeed —
        it would 400 with a DecimalValidator error if agreement_ref ever
        regressed to shipping floats for a price needing more precision
        than float's binary expansion round-trips cleanly."""
        from apps.invoicing.services import InvoiceService

        # A price that a float round-trip reliably mangles beyond 2 places
        # (0.1 has no exact binary representation) — a stronger canary
        # than the round '50.00' used elsewhere in this test class.
        self.est_line.price = Decimal('33.10')
        self.est_line.save()

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.seed_from_agreement(invoice)
        li = invoice.invoicelineitem_set.get()

        row = self._row(invoice, li)
        ref = row['agreement_ref']

        resp = self.client.patch(
            f'/api/invoices/{invoice.pk}/line-items/{li.pk}/',
            {'qty': ref['est_qty'], 'price': ref['est_price']},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        li.refresh_from_db()
        self.assertEqual(li.price, Decimal('33.10'))

    def test_backing_actuals_on_in_sync_claimed_line(self):
        """A plain (non-agreement) wizard line whose price is still in sync
        with its claimed atoms -> 'actuals'."""
        from apps.jobs.models import RateScheme
        from apps.invoicing.services import InvoiceWizardService

        scheme = RateScheme.objects.create(
            name='Hourly-Back', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        task = self._completed_task('Build-Back', scheme, hours=0.5)

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': task.pk}])

        row = self._row(invoice, li)
        self.assertEqual(row['backing'], 'actuals')
        self.assertIsNone(row['agreement_ref'])
        self.assertEqual(Decimal(row['actuals_total']), Decimal('30.00'))

    def test_backing_edited_after_price_override(self):
        """A seeded agreement line whose price was hand-overridden no longer
        matches its agreement_ref -> 'edited'."""
        from apps.invoicing.services import InvoiceService

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.seed_from_agreement(invoice)
        li = invoice.invoicelineitem_set.get()
        li.price = Decimal('75.00')
        li.save()

        row = self._row(invoice, li)
        self.assertEqual(row['backing'], 'edited')
        self.assertIsNotNone(row['agreement_ref'])

    def test_backing_deposit_and_credit(self):
        """A deposit charge line -> 'deposit'; the deduction claiming it on
        another job's invoice -> 'deposit_credit' (takes precedence over the
        other rules even though it has a claimed source)."""
        from apps.invoicing.models import InvoiceLineItemSource

        dep_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)
        dep_line = InvoiceLineItem.objects.create(
            invoice=dep_invoice, line_number=1, description='Deposit',
            qty=Decimal('1'), price=Decimal('500.00'),
            accounting_category=self.dep_cat,
        )

        other_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-BACK-0002',
        )
        credit_invoice = Invoice.objects.create(
            job=other_job, status=Invoice.STATUS_DRAFT)
        credit_line = InvoiceLineItem.objects.create(
            invoice=credit_invoice, line_number=1, description='Less deposit',
            qty=Decimal('1'), price=Decimal('-500.00'),
            accounting_category=self.dep_cat,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=credit_line,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep_line.pk,
        )

        dep_row = self._row(dep_invoice, dep_line)
        self.assertEqual(dep_row['backing'], 'deposit')

        credit_row = self._row(credit_invoice, credit_line)
        self.assertEqual(credit_row['backing'], 'deposit_credit')

    def test_backing_null_on_plain_hand_line(self):
        """A bare hand line — no agreement_ref, no sources -> null."""
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='Misc',
            qty=Decimal('1'), price=Decimal('20.00'),
            accounting_category=self.cat,
        )

        row = self._row(invoice, li)
        self.assertIsNone(row['backing'])
        self.assertIsNone(row['agreement_ref'])
        self.assertIsNone(row['actuals_total'])

    def test_actuals_total_sums_claimed_atoms_only(self):
        """actuals_total sums compute_amount() over claimed atoms regardless
        of whether the line is still in sync; null when a line has no
        sources at all."""
        from apps.jobs.models import RateScheme
        from apps.invoicing.services import InvoiceWizardService

        scheme = RateScheme.objects.create(
            name='Hourly-Sum', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('40.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        task1 = self._completed_task('T1-Back', scheme, hours=1)
        task2 = self._completed_task('T2-Back', scheme, hours=0.5)

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': task1.pk},
                      {'type': 'task', 'id': task2.pk}])
        # Override the price so the line is no longer in sync — proves
        # actuals_total is independent of the backing derivation.
        li.price = Decimal('999.00')
        li.save()

        plain_li = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=99, description='Plain',
            qty=Decimal('1'), price=Decimal('5.00'),
            accounting_category=self.cat,
        )

        row = self._row(invoice, li)
        self.assertEqual(row['backing'], 'edited')
        self.assertEqual(Decimal(row['actuals_total']), Decimal('60.00'))

        plain_row = self._row(invoice, plain_li)
        self.assertIsNone(plain_row['actuals_total'])

    def test_source_qty_units_rate_mirror_the_pool_per_atom_type(self):
        """The nested `sources[]` breakdown on a line (what the SPA's
        AtomChildRow renders under a seeded/claimed line) must carry real
        qty/units/rate — not the '-' a missing field renders as — sourced
        the same way the source pool itself computes them
        (InvoiceWizardService._atom_detail): task actual-qty ×
        effective_rate, material quantity × units × sell_price, fee
        quantity × unit_rate. A deposit-credit claim is not a real work
        atom (get_actuals_total already skips it) so it reports null
        rather than a fabricated qty/rate."""
        from apps.jobs.models import Fee
        from apps.inventory.models import Material, InventoryItem
        from apps.invoicing.models import InvoiceLineItemSource
        from apps.invoicing.services import InvoiceWizardService

        scheme = RateScheme.objects.create(
            name='Hourly-Src', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('40.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        task = self._completed_task('Task-Src', scheme, hours=1.5)

        # _atom_units reads a material's units off its catalog link (a
        # bare Material.units field isn't consulted — pre-existing
        # behavior, not something this test changes), so link an
        # InventoryItem to get a real (non-'none') units value here.
        pli = InventoryItem.objects.create(
            code='SRC-PLY', description='Plywood', units='sheet',
            selling_price=Decimal('12.50'), accounting_category=self.cat,
        )
        material = Material.objects.create(
            job=self.job, description='Ply-Src', quantity=Decimal('3.00'),
            sell_price=Decimal('12.50'), inventory_item=pli,
            accounting_category=self.cat,
        )
        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])

        fee = Fee.objects.create(
            job=self.job, description='Rush-Src', quantity=Decimal('2'),
            unit_rate=Decimal('15.00'), accounting_category=self.cat,
        )

        dep_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_PAID)
        dep_line = InvoiceLineItem.objects.create(
            invoice=dep_invoice, line_number=1, description='Deposit-Src',
            qty=Decimal('1'), price=Decimal('500.00'),
            accounting_category=self.dep_cat,
        )

        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        task_li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': task.pk}])
        material_li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'material', 'id': material.pk}])
        fee_li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'fee', 'id': fee.pk}])
        deposit_li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'deposit', 'id': dep_line.pk}])

        task_row = self._row(invoice, task_li)
        self.assertEqual(len(task_row['sources']), 1)
        task_src = task_row['sources'][0]
        self.assertEqual(Decimal(task_src['qty']), task.get_actual_qty())
        self.assertEqual(task_src['units'], task.unit_label or 'none')
        self.assertEqual(Decimal(task_src['rate']), task.effective_rate())

        material_row = self._row(invoice, material_li)
        material_src = material_row['sources'][0]
        self.assertEqual(Decimal(material_src['qty']), Decimal('3.00'))
        self.assertEqual(material_src['units'], 'sheet')
        self.assertEqual(Decimal(material_src['rate']), Decimal('12.50'))

        fee_row = self._row(invoice, fee_li)
        fee_src = fee_row['sources'][0]
        self.assertEqual(Decimal(fee_src['qty']), Decimal('2'))
        self.assertEqual(Decimal(fee_src['rate']), Decimal('15.00'))

        deposit_row = self._row(invoice, deposit_li)
        deposit_src = deposit_row['sources'][0]
        self.assertIsNone(deposit_src['qty'])
        self.assertIsNone(deposit_src['units'])
        self.assertIsNone(deposit_src['rate'])
        # The deposit source's description/amount are unaffected — only
        # the fabricated-qty/rate fields are suppressed.
        self.assertIsNotNone(deposit_src['description'])
        self.assertIsNotNone(deposit_src['computed_amount'])
