from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.core.services import NotFoundError, TaxCalculationService


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


class InvoiceWizardService:
    """Orchestration layer for the invoice wizard.

    Composes on top of InvoiceService rather than replacing it. The wizard service
    handles the atom-based flows; manual line item CRUD continues to use InvoiceService.
    """

    # Job statuses that allow invoicing
    BILLABLE_JOB_STATUSES = {
        Job.STATUS_APPROVED,
        Job.STATUS_IN_PROGRESS,  # NEW
        Job.STATUS_WORK_COMPLETE,
        Job.STATUS_COMPLETED,
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

            amount = task.compute_amount().quantize(Decimal('0.01'))
            key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'atom_type': 'task',
                'atom_id': task.pk,
                'description': f'{task.name} ({task.rate_scheme.name})',
                'sub_info': WizardAtomLabels.qty_source_label(task),
                'computed_amount': amount,
                **state_info,
            })

            # Material atoms
            materials = (
                Material.objects.filter(task=task, quantity__gt=0)
                .order_by('pk')
            )
            for mat in materials:
                amount = (mat.quantity * mat.sell_price).quantize(Decimal('0.01'))
                key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
                state_info = claims.get(key, default_state)
                atoms.append({
                    'atom_type': 'material',
                    'atom_id': mat.pk,
                    'description': mat.description,
                    'sub_info': '',
                    'computed_amount': amount,
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
            amount = (mat.quantity * mat.sell_price).quantize(Decimal('0.01'))
            key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
            state_info = claims.get(key, default_state)
            loose_atoms.append({
                'atom_type': 'material',
                'atom_id': mat.pk,
                'description': mat.description,
                'sub_info': '',
                'computed_amount': amount,
                **state_info,
            })
        task_list.append({
            'task_id': None,
            'name': 'Materials (no task)',
            'has_billable_atoms': len(loose_atoms) > 0,
            'atoms': loose_atoms,
        })

        return {'tasks': task_list}

    @staticmethod
    def _validate_draft(invoice):
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Wizard can only modify draft invoices.')

    @staticmethod
    def _resolve_atom(atom_ref):
        """Given {'type': 'material'|'task', 'id': N}, return the concrete instance."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if atom_ref['type'] == 'material':
            return Material.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'task':
            return Task.objects.get(pk=atom_ref['id'])
        raise ValueError(f"Unknown atom type: {atom_ref['type']}")

    @staticmethod
    def _atom_computed_amount(atom_instance):
        """Compute the billable amount for an atom."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.compute_amount().quantize(Decimal('0.01'))
        if isinstance(atom_instance, Material):
            return (atom_instance.quantity * atom_instance.sell_price).quantize(Decimal('0.01'))
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @staticmethod
    def _atom_category(atom_instance):
        """Return the accounting_category of an atom.

        For Tasks, walks through Task → RateScheme via
        effective_accounting_category. For Materials, direct.
        """
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.effective_accounting_category
        if isinstance(atom_instance, Material):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource
        if isinstance(atom_instance, Task):
            return InvoiceLineItemSource.SOURCE_TASK
        if isinstance(atom_instance, Material):
            return InvoiceLineItemSource.SOURCE_MATERIAL
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @staticmethod
    def _atom_description(atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.name
        if isinstance(atom_instance, Material):
            return atom_instance.description
        return ''

    @staticmethod
    def _atom_units(atom_instance):
        """Return the units label for an atom, sourced from related rate
        scheme or price list item. Falls back to 'none' (the only literal
        unit guaranteed to exist in the configured units list)."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.rate_scheme.unit_label
        if isinstance(atom_instance, Material):
            if atom_instance.price_list_item_id:
                return atom_instance.price_list_item.units
            return 'none'
        return 'none'

    @staticmethod
    def _atom_qty_and_price(atom_instance, total_price):
        """Return (qty, price) for a single-atom copy-over so qty * price = total.

        Materials decompose cleanly into intrinsic qty/price. Tasks roll up
        bleps via Task.rate_scheme — there is no single qty/price per Task that's
        meaningful across all rate algorithms, so default to qty=1.
        """
        from apps.inventory.models import Material
        if isinstance(atom_instance, Material):
            return atom_instance.quantity, atom_instance.sell_price
        return Decimal('1'), total_price  # Task or unknown

    @staticmethod
    def _uniform_scheme_bundle(instances):
        """If every atom is a Task sharing one RateScheme and identical
        `active_modifiers`, return `(units, qty, price)` summarizing the
        bundle — units from the scheme, qty = summed actual quantities,
        price = the common effective rate. Otherwise None, and the caller
        falls back to qty=1 / units='none'."""
        from apps.jobs.models import Task
        if not instances or not all(isinstance(i, Task) for i in instances):
            return None
        if len({i.rate_scheme_id for i in instances}) != 1:
            return None
        modifier_sets = {
            tuple(sorted(i.active_modifiers or [])) for i in instances
        }
        if len(modifier_sets) != 1:
            return None
        scheme = instances[0].rate_scheme
        modifiers = instances[0].active_modifiers or []
        qty = sum(
            (scheme.get_actual_qty(t) for t in instances), Decimal('0'),
        )
        price = scheme.effective_rate(modifiers).quantize(Decimal('0.01'))
        return scheme.unit_label, qty, price

    @staticmethod
    def _resync_in_sync_line_item(line_item):
        """After a source-set change on an in-sync line item, re-derive its
        units/qty/price. If the sources form a uniform same-scheme task
        bundle, summarize; otherwise keep qty and recompute the per-unit
        price. Saves the line item."""
        instances = [src.resolve() for src in line_item.sources.all()]
        summary = InvoiceWizardService._uniform_scheme_bundle(instances)
        if summary is not None:
            line_item.units, line_item.qty, line_item.price = summary
        else:
            new_sum = InvoiceWizardService._sum_sources(line_item)
            line_item.price = InvoiceWizardService._expected_per_unit(
                new_sum, line_item.qty,
            )
        line_item.save()

    @staticmethod
    def _sum_sources(line_item):
        """Sum the computed amounts of all source atoms on a line item."""
        total = Decimal('0.00')
        for src in line_item.sources.all():
            instance = src.resolve()
            total += InvoiceWizardService._atom_computed_amount(instance)
        return total

    @staticmethod
    def _expected_per_unit(sum_value, qty):
        """The per-unit price the wizard would compute right now: round(sum/qty, 2)."""
        if not qty:
            return Decimal('0.00')
        return (sum_value / qty).quantize(Decimal('0.01'))

    @staticmethod
    def _is_in_sync(line_item, sum_value):
        """In sync iff price == round(sum / qty, 2). Rounding-safe."""
        if not line_item.qty:
            return False
        return line_item.price == InvoiceWizardService._expected_per_unit(sum_value, line_item.qty)

    @staticmethod
    def add_atoms_to_line_item(line_item, atoms):
        """Append N atoms as sources to an existing line item.

        Recomputes the line item's price if it was in sync before the operation;
        preserves an overridden price otherwise.
        """
        from django.db import transaction, IntegrityError
        from apps.invoicing.models import InvoiceLineItemSource

        InvoiceWizardService._validate_draft(line_item.invoice)

        old_sum = InvoiceWizardService._sum_sources(line_item)
        was_in_sync = InvoiceWizardService._is_in_sync(line_item, old_sum)

        instances = [InvoiceWizardService._resolve_atom(a) for a in atoms]

        try:
            with transaction.atomic():
                for atom_ref, instance in zip(atoms, instances):
                    InvoiceLineItemSource.objects.create(
                        invoice_line_item=line_item,
                        source_type=InvoiceWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
                if was_in_sync:
                    InvoiceWizardService._resync_in_sync_line_item(line_item)
        except IntegrityError:
            existing = set(
                InvoiceLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [
                a for a in atoms
                if (a['type'], a['id']) in existing
            ]
            raise ClaimConflict(atom_ids=conflicts)

        return line_item

    @staticmethod
    def remove_atoms_from_line_item(line_item, source_ids):
        """Remove a subset of source rows from a line item.

        - Recomputes price if the line item was in sync before.
        - Preserves price if it was overridden.
        - Deletes the line item if all sources are removed, regardless of override.

        Returns: {'line_item_deleted': bool}
        """
        from django.db import transaction
        from apps.core.services import LineItemService

        InvoiceWizardService._validate_draft(line_item.invoice)

        old_sum = InvoiceWizardService._sum_sources(line_item)
        was_in_sync = InvoiceWizardService._is_in_sync(line_item, old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                LineItemService.delete_line_item_with_renumber(line_item)
                return {'line_item_deleted': True}

            if was_in_sync:
                InvoiceWizardService._resync_in_sync_line_item(line_item)

        return {'line_item_deleted': False}

    @staticmethod
    def add_atoms_to_new_line_item(invoice, atoms):
        """Create a new InvoiceLineItem on `invoice` with the given atoms as sources.

        atoms: list of {'type': 'task'|'material', 'id': N} dicts.
        """
        from django.db import transaction, IntegrityError
        from apps.invoicing.models import InvoiceLineItemSource

        InvoiceWizardService._validate_draft(invoice)

        # Resolve all atoms up front; fail fast if any are invalid
        instances = [InvoiceWizardService._resolve_atom(a) for a in atoms]

        # Compute defaults
        total_price = sum(
            (InvoiceWizardService._atom_computed_amount(i) for i in instances),
            Decimal('0.00'),
        )
        categories = {InvoiceWizardService._atom_category(i) for i in instances}
        # Uniform category -> use it; mixed -> leave null
        category = categories.pop() if len(categories) == 1 else None

        # Single atom: copy over description, units, qty, price from the atom.
        # Multi-atom: if it's a uniform same-scheme task bundle, summarize it
        # (units/qty/price from the scheme); otherwise blank description,
        # units='none', qty=1, price=total.
        if len(instances) == 1:
            description = InvoiceWizardService._atom_description(instances[0])
            units = InvoiceWizardService._atom_units(instances[0])
            qty, price = InvoiceWizardService._atom_qty_and_price(
                instances[0], total_price,
            )
        else:
            description = ''
            summary = InvoiceWizardService._uniform_scheme_bundle(instances)
            if summary is not None:
                units, qty, price = summary
            else:
                units = 'none'
                qty = Decimal('1')
                price = total_price

        try:
            with transaction.atomic():
                line_item = InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=description,
                    qty=qty,
                    units=units,
                    price=price,
                    accounting_category=category,
                )
                for atom_ref, instance in zip(atoms, instances):
                    InvoiceLineItemSource.objects.create(
                        invoice_line_item=line_item,
                        source_type=InvoiceWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
        except IntegrityError:
            # Re-query to find which atoms are already claimed
            existing = set(
                InvoiceLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [
                a for a in atoms
                if (a['type'], a['id']) in existing
            ]
            raise ClaimConflict(atom_ids=conflicts)

        return line_item

