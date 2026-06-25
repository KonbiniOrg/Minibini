from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.core.services import NotFoundError, TaxCalculationService
from apps.core.wizard import BaseWizardService


class InvoiceService:
    """Service for invoice operations."""

    @staticmethod
    def _validate_draft(invoice):
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Can only modify line items on draft invoices.'
            )

    @staticmethod
    def add_line_item(invoice_pk, **kwargs):
        """Add a manual line item to a draft invoice."""
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(InvoiceLineItem, kwargs)
        li = InvoiceLineItem(invoice=invoice, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(invoice_pk, pli_pk, qty):
        """Add a line item from a InventoryItem to a draft invoice."""
        from apps.inventory.models import InventoryItem
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        try:
            pli = InventoryItem.objects.get(pk=pli_pk)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {pli_pk} not found')
        li = InvoiceLineItem(
            invoice=invoice,
            inventory_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            accounting_category=pli.accounting_category,
        )
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update an invoice line item — validates draft status."""
        try:
            li = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        InvoiceService._validate_draft(li.invoice)
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(InvoiceLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(invoice_pk, item_ids):
        """Reorder invoice line items by position list — validates draft status."""
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                InvoiceLineItem.objects.filter(
                    pk=item_id, invoice=invoice,
                ).update(line_number=position)

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder an invoice line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        if line_item.invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft invoice.'
            )
        return LineItemService.reorder_line_item(line_item, direction)

    @staticmethod
    def discard_draft(invoice):
        """Hard-delete a draft invoice; cascades to line items and sources."""
        InvoiceService._validate_draft(invoice)
        invoice.delete()

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete an invoice line item and renumber — validates draft status."""
        from apps.core.services import LineItemService
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        if line_item.invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft invoice.'
            )
        return LineItemService.delete_line_item_with_renumber(line_item)

    @staticmethod
    def add_adjustment_line(invoice, *, adjustment_service_id, target_category_ids=None):
        """Add a percentage-adjustment line item to a draft invoice.

        Creates an InvoiceLineItem backed by a PERCENTAGE ServiceItem, sets
        target categories (empty list = apply to all non-adjustment lines),
        computes the initial price via ``compute_adjustment_amount``, and
        returns the saved line.

        Raises ValidationError if the invoice is not draft or the service is
        not a PERCENTAGE algorithm.
        """
        from django.db import transaction
        from django.db.models import Max
        from apps.jobs.models import ServiceItem
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Adjustments can only be added to a draft invoice.')
        svc = ServiceItem.objects.get(pk=adjustment_service_id)
        if svc.algorithm != ServiceItem.PERCENTAGE:
            raise ValidationError('Adjustment line requires a percentage service.')
        with transaction.atomic():
            max_ln = (InvoiceLineItem.objects.filter(invoice=invoice)
                      .aggregate(Max('line_number'))['line_number__max'] or 0)
            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                line_number=max_ln + 1,
                qty=Decimal('1'),
                units=svc.unit_label or 'none',
                description=svc.name,
                price=Decimal('0.00'),
                accounting_category=svc.accounting_category,
                adjustment_service=svc,
            )
            if target_category_ids:
                line.adjustment_target_categories.set(target_category_ids)
            return InvoiceService.recalculate_adjustment_line(line)

    @staticmethod
    def recalculate_adjustment_line(line):
        """Recompute the price of a percentage-adjustment line from its siblings.

        Raises ValidationError if the parent invoice is not draft.
        Returns the saved line with updated price.
        """
        from apps.core.adjustments import compute_adjustment_amount
        invoice = line.invoice
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Cannot recalculate on a non-draft invoice.')
        siblings = InvoiceLineItem.objects.filter(invoice=invoice).exclude(pk=line.pk)
        line.price = compute_adjustment_amount(line, siblings)
        line.save()
        return line


class InvoiceEmailService:
    """Orchestrates sending an Invoice to the customer.

    Steps on each send: ensure the invoice exists in QBO (push only if
    qbo_id is unset — fixes the duplicate-push-on-retry bug), generate
    the Minibini job-statement PDF, download the QBO-rendered invoice
    PDF (which carries the Pay Now link), call OutboundEmailService.
    send_tracked with both PDFs attached, then transition the Invoice
    draft -> open on send success.
    """

    DEFAULT_SUBJECT = 'Invoice {document_number} for {job_number}'
    DEFAULT_BODY = (
        'Hi {contact_fname},\n\n'
        'Please find attached your invoice {document_number} for {job_name}. '
        'The invoice includes a Pay Now link.\n\n'
        'Thanks,\n{my_user_name}'
    )

    @staticmethod
    def get_email_defaults(invoice):
        """Pre-populated send-form fields for an Invoice."""
        from apps.core.models import Configuration
        from apps.core.email_templates import render_email_template

        subject_template = InvoiceEmailService.DEFAULT_SUBJECT
        body_template = InvoiceEmailService.DEFAULT_BODY
        try:
            subject_template = Configuration.objects.get(
                key='invoice_email_subject_template'
            ).value
        except Configuration.DoesNotExist:
            pass
        try:
            body_template = Configuration.objects.get(
                key='invoice_email_body_template'
            ).value
        except Configuration.DoesNotExist:
            pass
        job = invoice.job
        contact = job.contact if job else None
        contact_business = ''
        if contact and contact.business:
            contact_business = contact.business.business_name

        from apps.core.email_templates import build_object_url
        values = {
            'contact_fname': contact.first_name if contact else '',
            'contact_lname': contact.last_name if contact else '',
            'contact_business': contact_business,
            'my_user_name': '',
            'job_number': job.job_number if job else '',
            'job_name': job.name if job else '',
            'document_number': invoice.invoice_number,
            'invoice_number': invoice.invoice_number,
            'object_url': build_object_url('invoice', invoice.invoice_id),
        }
        subject = render_email_template(subject_template, **values)
        body = render_email_template(body_template, **values)

        to = ''
        if contact and contact.email:
            to = contact.email

        attachments_preview = [
            {'filename': f'Invoice-{invoice.invoice_number}.pdf',
             'content_type': 'application/pdf', 'size': 0},
            {'filename': f'JobStatement-{invoice.invoice_number}.pdf',
             'content_type': 'application/pdf', 'size': 0},
        ]
        return {
            'to': to, 'subject': subject, 'body': body,
            'attachments_preview': attachments_preview,
        }

    @staticmethod
    def send_invoice(invoice, *, to, subject, body, cc=None, bcc=None,
                     extra_attachments=None, user=None):
        """Send an Invoice. Pushes to QBO if needed, attaches both QBO PDF
        and statement PDF, calls send_tracked, transitions status on success.

        Returns the outbound EmailRecord.
        """
        from apps.core.services import OutboundEmailService
        from apps.invoicing.pdf import generate_job_statement_pdf
        from apps.qbo.services import (
            QBOService, QBOInvoiceSyncService, QBOCustomerSyncService,
        )

        if not to:
            raise ValidationError('Recipient email address is required.')

        client = QBOService.get_client()
        if not client:
            raise ValidationError('No active QBO connection.')

        # Step 1: QBO push (skip if already pushed — retry path).
        if not invoice.qbo_id:
            contact = invoice.job.contact
            business = contact.business if contact else None

            if business:
                if not business.qbo_customer_id:
                    QBOCustomerSyncService.push_customer(business)
                qbo_customer_id = business.qbo_customer_id
            else:
                if not contact.qbo_customer_id:
                    QBOCustomerSyncService.push_contact_as_customer(contact)
                    contact.refresh_from_db()
                qbo_customer_id = contact.qbo_customer_id

            grouped_lines = InvoiceGroupingService.group_for_qbo(invoice)
            qbo_invoice = QBOInvoiceSyncService._build_qbo_invoice(
                invoice, qbo_customer_id, grouped_lines,
            )
            qbo_invoice.save(qb=client)
            qbo_id = str(qbo_invoice.Id)
            invoice.qbo_id = qbo_id
            invoice.save(update_fields=['qbo_id'])

            QBOInvoiceSyncService._mark_as_sent(client, qbo_id)
            QBOService.log_sync(
                entity_type='invoice', entity_id=invoice.pk,
                qbo_entity_type='Invoice', qbo_entity_id=qbo_id,
                action='create', status='success',
            )

        # Step 2: generate / fetch the two PDFs.
        statement_pdf = generate_job_statement_pdf(invoice)
        qbo_invoice_pdf = QBOInvoiceSyncService._download_qbo_pdf(client, invoice.qbo_id)

        # Step 3: send via tracked outbound.
        attachments = [
            (f'Invoice-{invoice.invoice_number}.pdf', qbo_invoice_pdf, 'application/pdf'),
            (f'JobStatement-{invoice.invoice_number}.pdf', statement_pdf, 'application/pdf'),
        ]
        if extra_attachments:
            attachments.extend(extra_attachments)

        record = OutboundEmailService.send_tracked(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachments=attachments,
            associate_with={'job': invoice.job},
        )

        # Step 4: status transition on success.
        if invoice.status == Invoice.STATUS_DRAFT:
            invoice.status = Invoice.STATUS_OPEN
            invoice.save()

        return record


class InvoiceGroupingService:
    """Groups invoice line items by AccountingCategory + taxability for QBO push."""

    @staticmethod
    def group_for_qbo(invoice):
        line_items = invoice.invoicelineitem_set.select_related('accounting_category').all()
        job_number = invoice.job.job_number

        groups = defaultdict(lambda: {
            'amount': Decimal('0.00'),
            'category_name': '',
            'qbo_item_id': '',
            'taxable': False,
        })

        for item in line_items:
            taxable = TaxCalculationService.get_effective_taxability(item)
            cat = item.accounting_category
            cat_id = cat.pk if cat else None
            key = (cat_id, taxable)

            groups[key]['amount'] += item.total_amount
            groups[key]['taxable'] = taxable

            if cat:
                groups[key]['category_name'] = cat.name
                groups[key]['qbo_item_id'] = cat.qbo_item_id
            else:
                groups[key]['category_name'] = 'Uncategorized'

        result = []
        for (cat_id, taxable), data in groups.items():
            tax_label = '(taxable)' if taxable else '(non-taxable)'
            data['description'] = f"Job {job_number}: {data['category_name']} {tax_label}"
            result.append(data)

        return sorted(result, key=lambda g: g['category_name'])


class ClaimConflict(Exception):
    """Raised when the wizard tries to claim an atom already claimed elsewhere."""

    def __init__(self, atom_ids):
        self.atom_ids = atom_ids
        super().__init__(f'Atoms already claimed: {atom_ids}')


class WizardAtomLabels:
    """Helpers for rendering human-friendly labels for wizard atoms."""

    @staticmethod
    def qty_source_label(task):
        """Describe where the billable quantity came from for a Task atom."""
        from apps.jobs.models import ServiceItem
        scheme = task.service_item
        if scheme.algorithm == ServiceItem.ELAPSED_TIME:
            qty = scheme.get_actual_qty(task)
            return f'{qty:.2f} {scheme.unit_label} from bleps'
        if scheme.algorithm == ServiceItem.ENTERED_QTY:
            qty = scheme.get_actual_qty(task)
            return f'{qty} {scheme.unit_label} entered'
        return 'flat fee'


class InvoiceWizardService(BaseWizardService):
    """Orchestration layer for the invoice wizard.

    Composes on top of InvoiceService rather than replacing it. The wizard service
    handles the atom-based flows; manual line item CRUD continues to use InvoiceService.
    Shared line-items-from-atoms logic lives in BaseWizardService.
    """

    container_attr = 'invoice'
    source_fk = 'invoice_line_item'
    claim_conflict_exc = ClaimConflict

    # Job statuses that allow invoicing
    BILLABLE_JOB_STATUSES = {
        Job.STATUS_APPROVED,
        Job.STATUS_IN_PROGRESS,  # NEW
        Job.STATUS_WORK_COMPLETE,
        Job.STATUS_COMPLETED,
        Job.STATUS_CANCELLED,  # stopped early — still billable for work done
    }

    @staticmethod
    def open_for_job(job):
        """Return the job's draft Invoice, creating one if none exists.

        Raises ValidationError if the job is in a status that doesn't allow invoicing.
        """
        if job.status not in InvoiceWizardService.BILLABLE_JOB_STATUSES:
            raise ValidationError(
                f'Cannot start invoice wizard for job in status "{job.status}". '
                f'Job must be approved or completed.'
            )

        existing = Invoice.objects.filter(
            job=job, status=Invoice.STATUS_DRAFT
        ).first()
        if existing:
            return existing

        return Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)

    @staticmethod
    def get_source_pool(invoice):
        """Walk the job's tasks -> atoms and return the source pool tree.

        Atoms are annotated with state: 'available', 'claimed_by_current', or 'claimed_by_other'.
        """
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource

        job = invoice.job

        # Build the claim lookup: (source_type, source_pk) -> state info
        # Only non-cancelled invoices create claims
        claimed_sources = (
            InvoiceLineItemSource.objects
            .filter(invoice_line_item__invoice__job=job)
            .exclude(invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED)
            .select_related('invoice_line_item', 'invoice_line_item__invoice')
        )
        claims = {}
        for src in claimed_sources:
            li = src.invoice_line_item
            inv = li.invoice
            key = (src.source_type, src.source_pk)
            if inv.pk == invoice.pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_line_number': li.line_number,
                    'claiming_invoice_id': None,
                    'claiming_invoice_number': None,
                    'not_billable_reason': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_line_number': None,
                    'claiming_invoice_id': inv.pk,
                    'claiming_invoice_number': inv.invoice_number,
                    'not_billable_reason': None,
                }

        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_line_number': None,
            'claiming_invoice_id': None,
            'claiming_invoice_number': None,
            'not_billable_reason': None,
        }

        def billability(atom_type, instance):
            if atom_type == 'task' and instance.status != Task.STATUS_COMPLETE:
                return {'state': 'not_billable', 'not_billable_reason': 'task_incomplete',
                        'claiming_line_item_id': None, 'claiming_line_number': None,
                        'claiming_invoice_id': None, 'claiming_invoice_number': None}
            if atom_type == 'material' and (
                instance.consumption_state != Material.CONSUMPTION_STATE_CONSUMED
            ):
                return {'state': 'not_billable', 'not_billable_reason': 'material_unconsumed',
                        'claiming_line_item_id': None, 'claiming_line_number': None,
                        'claiming_invoice_id': None, 'claiming_invoice_number': None}
            return None

        tasks = (
            Task.objects.filter(job=job)
            .exclude(status=Task.STATUS_CANCELLED)
            .select_related('service_item')
            .order_by('sort_order', 'pk')
        )
        task_list = []
        for task in tasks:
            atoms = []

            detail = InvoiceWizardService._atom_detail(task)
            key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
            state_info = claims.get(key) or billability('task', task) or default_state
            atoms.append({
                'type': 'task',
                'id': task.pk,
                'description': f'{task.name} ({task.service_item.name})',
                'sub_info': WizardAtomLabels.qty_source_label(task),
                'qty': detail['qty'],
                'rate': detail['rate'],
                'units': detail['units'],
                'amount': detail['amount'],
                **state_info,
            })

            # Material atoms
            materials = (
                Material.objects.filter(task=task, quantity__gt=0)
                .order_by('pk')
            )
            for mat in materials:
                detail = InvoiceWizardService._atom_detail(mat)
                key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
                state_info = claims.get(key) or billability('material', mat) or default_state
                atoms.append({
                    'type': 'material',
                    'id': mat.pk,
                    'description': mat.description,
                    'sub_info': '',
                    'qty': detail['qty'],
                    'rate': detail['rate'],
                    'units': detail['units'],
                    'amount': detail['amount'],
                    **state_info,
                })

            task_list.append({
                'task_id': task.pk,
                'name': task.name,
                'has_billable_atoms': len(atoms) > 0,
                'atoms': atoms,
            })

        # "Materials (no task)" group - task-less Materials with quantity > 0
        loose = (
            Material.objects.filter(job=job, task__isnull=True, quantity__gt=0)
            .order_by('pk')
        )
        loose_atoms = []
        for mat in loose:
            detail = InvoiceWizardService._atom_detail(mat)
            key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
            state_info = claims.get(key) or billability('material', mat) or default_state
            loose_atoms.append({
                'type': 'material',
                'id': mat.pk,
                'description': mat.description,
                'sub_info': '',
                'qty': detail['qty'],
                'rate': detail['rate'],
                'units': detail['units'],
                'amount': detail['amount'],
                **state_info,
            })
        task_list.append({
            'task_id': None,
            'name': 'Materials (no task)',
            'has_billable_atoms': len(loose_atoms) > 0,
            'atoms': loose_atoms,
        })

        # "Expenses" group — material-less, non-rejected expenses on the job.
        # (Material-linked expenses bill through their material, so they are
        # not offered here — that's what prevents double-billing.)
        from apps.expenses.models import Expense
        expenses = (
            Expense.objects.filter(job=job, material__isnull=True)
            .exclude(status=Expense.STATUS_REJECTED)
            .exclude(stock_pli__isnull=False)  # stock receipts are inventory, not billable
            .order_by('pk')
        )
        expense_atoms = []
        for exp in expenses:
            detail = InvoiceWizardService._atom_detail(exp)
            key = (InvoiceLineItemSource.SOURCE_EXPENSE, exp.pk)
            state_info = claims.get(key, default_state)
            expense_atoms.append({
                'type': 'expense',
                'id': exp.pk,
                'description': InvoiceWizardService._atom_description(exp),
                'sub_info': '',
                'qty': detail['qty'],
                'rate': detail['rate'],
                'units': detail['units'],
                'amount': detail['amount'],
                **state_info,
            })
        task_list.append({
            'task_id': None,
            'name': 'Expenses',
            'has_billable_atoms': len(expense_atoms) > 0,
            'atoms': expense_atoms,
        })

        return {'tasks': task_list}

    # ── BaseWizardService hooks ────────────────────────────────────────
    @classmethod
    def _line_item_model(cls):
        return InvoiceLineItem

    @classmethod
    def _source_model(cls):
        from apps.invoicing.models import InvoiceLineItemSource
        return InvoiceLineItemSource

    @classmethod
    def _task_model(cls):
        from apps.jobs.models import Task
        return Task

    @classmethod
    def _material_model(cls):
        from apps.inventory.models import Material
        return Material

    @classmethod
    def _validate_draft(cls, container):
        if container.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Wizard can only modify draft invoices.')

    @classmethod
    def _assert_atom_billable(cls, instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(instance, Task) and instance.status != Task.STATUS_COMPLETE:
            raise ValidationError('Cannot bill a task that is not complete.')
        if isinstance(instance, Material) and (
            instance.consumption_state != Material.CONSUMPTION_STATE_CONSUMED
        ):
            raise ValidationError('Cannot bill a material that is not consumed.')

    @classmethod
    def _expense_model(cls):
        from apps.expenses.models import Expense
        return Expense

    @classmethod
    def _resolve_atom(cls, atom_ref):
        """Given {'type': 'material'|'task'|'expense', 'id': N}, return the instance."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if atom_ref['type'] == 'material':
            return Material.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'task':
            return Task.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'expense':
            return cls._expense_model().objects.get(pk=atom_ref['id'])
        raise ValueError(f"Unknown atom type: {atom_ref['type']}")

    @classmethod
    def _atom_source_type(cls, atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource
        if isinstance(atom_instance, Task):
            return InvoiceLineItemSource.SOURCE_TASK
        if isinstance(atom_instance, Material):
            return InvoiceLineItemSource.SOURCE_MATERIAL
        if isinstance(atom_instance, cls._expense_model()):
            return InvoiceLineItemSource.SOURCE_EXPENSE
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @classmethod
    def _atom_units(cls, atom_instance):
        """Units label for an atom — rate scheme unit, PLI units, or 'none'."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.service_item.unit_label
        if isinstance(atom_instance, Material):
            if atom_instance.inventory_item_id:
                return atom_instance.inventory_item.units
            return 'none'
        return 'none'

    @classmethod
    def _atom_category(cls, atom_instance):
        if isinstance(atom_instance, cls._expense_model()):
            return atom_instance.accounting_category
        return super()._atom_category(atom_instance)

    @classmethod
    def _atom_description(cls, atom_instance):
        if isinstance(atom_instance, cls._expense_model()):
            return atom_instance.description or (
                atom_instance.accounting_category.name
                if atom_instance.accounting_category_id else 'Expense'
            )
        return super()._atom_description(atom_instance)

    @classmethod
    def _atom_qty_and_price(cls, atom_instance, total_price):
        # A material-less expense bills at pass-through cost: qty 1 × amount.
        if isinstance(atom_instance, cls._expense_model()):
            return Decimal('1'), atom_instance.amount
        return super()._atom_qty_and_price(atom_instance, total_price)

    @classmethod
    def _atom_detail(cls, atom_instance):
        if isinstance(atom_instance, cls._expense_model()):
            amount = cls._atom_computed_amount(atom_instance)
            return {'qty': Decimal('1'), 'rate': amount,
                    'units': 'none', 'amount': amount}
        return super()._atom_detail(atom_instance)

    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        # Tasks roll up bleps via the rate scheme — no single qty/price is
        # meaningful across all algorithms, so a single-task line uses qty=1.
        return Decimal('1'), total_price

    @classmethod
    def _task_actual_qty(cls, task):
        return task.service_item.get_actual_qty(task)
