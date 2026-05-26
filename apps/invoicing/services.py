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
        """Add a line item from a PriceListItem to a draft invoice."""
        from apps.inventory.models import PriceListItem
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        try:
            pli = PriceListItem.objects.get(pk=pli_pk)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {pli_pk} not found')
        li = InvoiceLineItem(
            invoice=invoice,
            price_list_item=pli,
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
        from apps.jobs.models import RateScheme
        scheme = task.rate_scheme
        if scheme.algorithm == RateScheme.ELAPSED_TIME:
            qty = scheme.get_actual_qty(task)
            return f'{qty:.2f} {scheme.unit_label} from bleps'
        if scheme.algorithm == RateScheme.ENTERED_QTY:
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
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_line_number': None,
                    'claiming_invoice_id': inv.pk,
                    'claiming_invoice_number': inv.invoice_number,
                }

        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_line_number': None,
            'claiming_invoice_id': None,
            'claiming_invoice_number': None,
        }

        tasks = (
            Task.objects.filter(job=job)
            .exclude(status=Task.STATUS_CANCELLED)
            .select_related('rate_scheme')
            .order_by('sort_order', 'pk')
        )
        task_list = []
        for task in tasks:
            atoms = []

            detail = InvoiceWizardService._atom_detail(task)
            key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'task',
                'id': task.pk,
                'description': f'{task.name} ({task.rate_scheme.name})',
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
                state_info = claims.get(key, default_state)
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
            state_info = claims.get(key, default_state)
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
    def _resolve_atom(cls, atom_ref):
        """Given {'type': 'material'|'task', 'id': N}, return the concrete instance."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if atom_ref['type'] == 'material':
            return Material.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'task':
            return Task.objects.get(pk=atom_ref['id'])
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
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @classmethod
    def _atom_units(cls, atom_instance):
        """Units label for an atom — rate scheme unit, PLI units, or 'none'."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.rate_scheme.unit_label
        if isinstance(atom_instance, Material):
            if atom_instance.price_list_item_id:
                return atom_instance.price_list_item.units
            return 'none'
        return 'none'

    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        # Tasks roll up bleps via the rate scheme — no single qty/price is
        # meaningful across all algorithms, so a single-task line uses qty=1.
        return Decimal('1'), total_price

    @classmethod
    def _task_actual_qty(cls, task):
        return task.rate_scheme.get_actual_qty(task)
