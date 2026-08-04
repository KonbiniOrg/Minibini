import logging
from decimal import Decimal
from apps.core.history import record_history, record_action
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.purchasing.models import (
    PurchaseOrder, PurchaseOrderLineItem,
)
from apps.core.services import NotFoundError, NumberGenerationService


class PurchaseOrderService:
    """Service for purchase order operations."""

    @staticmethod
    def create_po(**kwargs):
        """Create a new PurchaseOrder with auto-generated number."""
        po_number = NumberGenerationService.generate_next_number('po')
        po = PurchaseOrder(po_number=po_number, **kwargs)
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def update_po(pk, **kwargs):
        """Update an existing PurchaseOrder by PK."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        for field, value in kwargs.items():
            setattr(po, field, value)
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def update_status(pk, new_status):
        """Update PO status."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if new_status == PurchaseOrder.STATUS_ISSUED and po.business_id is None:
            raise ValidationError(
                {'business': ['A purchase order needs a vendor before it can be issued.']})
        po.status = new_status
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def reconcile(po_id, bill_total=None, vendor_invoice_ref='',
                   line_finals=None, appended_lines=None):
        """Record vendor-bill reconciliation data against a PO (spec §7 rule
        3). The bill is entered once in QBO by whoever does payables —
        Minibini captures only the delta.

        Allowed once the PO has been ISSUED (any non-draft status,
        including cancelled — a vendor bill can still land for whatever
        actually shipped before cancellation). NOT gated on receiving
        state: `awaiting_reconciliation` is a downstream nudge, not a
        precondition here — the plan explicitly decided "reconcile allowed
        once ISSUED".

        Reconcile is editable, not a lifecycle lock: calling this again on
        an already-reconciled PO overwrites the PO-level fields — it's
        bookkeeping, not a one-shot transition. `reconciled`/
        `reconciled_date` are always (re)set. `bill_total` = None if not
        supplied (allowed once ISSUED — see above; a cancelled PO can still
        be reconciled, since a vendor bill can land for whatever actually
        shipped before cancellation).

        `line_finals`: {line_item_id: Decimal} — sets the optional
        per-line `final_price` (null elsewhere means "as ordered"). Every
        key must reference a line item that belongs to THIS PO (invoice_only
        lines included, if one was targeted deliberately).

        REPLACE semantics, not merge: each call mirrors the vendor's bill
        wholesale — every non-`invoice_only` line on the PO that is NOT a
        key in this call's `line_finals` has its `final_price` cleared back
        to `None` ("as ordered"), even if a *previous* reconcile call had
        set it. A smaller `line_finals` set on a later call is therefore
        not additive; it is the new complete statement of which lines carry
        a final price. `invoice_only` lines are never auto-cleared by this
        sweep (they aren't "ordered" lines to begin with) — one is only
        touched if its id is explicitly present in `line_finals`.

        `appended_lines`: a list of PurchaseOrderLineItem field kwargs
        (same shape as `add_line_item`, task may be included for optional
        attribution) for the `invoice_only=True` lines this call's vendor
        bill carries — e.g. freight or other vendor-invoice-only charges
        that were never ordered/received.

        APPEND-ONLY MIRROR, not additive (task-owned-money Phase 5, Task 2
        carry-note requirement): each reconcile call is the complete,
        current statement of the bill's invoice_only detail, mirroring the
        vendor bill wholesale the same way `line_finals` does for ordered
        lines' `final_price`. Each dict may carry an optional
        `line_item_id` key to target an existing invoice_only line on this
        PO for an in-place update; omit it to create a new one. Any
        invoice_only line already on the PO whose id is NOT present in
        this call's `appended_lines` is DELETED via
        `LineItemService.delete_line_item_with_renumber` (repo law: never
        `.delete()` a line item directly — see CLAUDE.md). Every entry
        (new or updated) goes through the model's normal `full_clean()`,
        including the task-link validation in
        `PurchaseOrderLineItem.clean()`.
        """
        from apps.core.services import LineItemService

        line_finals = line_finals or {}
        appended_lines = appended_lines or []

        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')

        if po.status == PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Cannot reconcile a purchase order before it has been issued.'
            )

        all_lines_by_id = {
            li.pk: li for li in PurchaseOrderLineItem.objects.filter(purchase_order=po)
        }
        missing = set(line_finals.keys()) - set(all_lines_by_id.keys())
        if missing:
            raise ValidationError({'line_finals': [
                f'Line item {line_id} does not belong to PO {po.po_number}.'
                for line_id in sorted(missing)
            ]})

        existing_invoice_only = {
            pk: li for pk, li in all_lines_by_id.items() if li.invoice_only
        }
        appended_ids = {
            int(entry['line_item_id']) for entry in appended_lines
            if entry.get('line_item_id') is not None
        }
        bad_ids = appended_ids - set(existing_invoice_only.keys())
        if bad_ids:
            raise ValidationError({'appended_lines': [
                f'Invoice-only line {line_id} does not belong to PO {po.po_number}.'
                for line_id in sorted(bad_ids)
            ]})

        with transaction.atomic():
            for li in all_lines_by_id.values():
                if li.pk in line_finals:
                    value = line_finals[li.pk]
                    li.final_price = (
                        value if isinstance(value, Decimal) else Decimal(str(value))
                    )
                elif not li.invoice_only:
                    # REPLACE semantics: an omitted ordered line reverts to
                    # "as ordered" — see docstring. invoice_only lines not
                    # targeted this call are left untouched entirely.
                    if li.final_price is None:
                        continue
                    li.final_price = None
                else:
                    continue
                li.full_clean()
                li.save()

            seen_invoice_only_ids = set()
            for line_data in appended_lines:
                data = dict(line_data)
                line_id = data.pop('line_item_id', None)
                data['invoice_only'] = True
                data = LineItemService.normalize_fk_kwargs(PurchaseOrderLineItem, data)
                if line_id is not None:
                    line_id = int(line_id)
                    li = existing_invoice_only[line_id]
                    for field, value in data.items():
                        setattr(li, field, value)
                    li.full_clean()
                    li.save()
                    seen_invoice_only_ids.add(line_id)
                else:
                    li = PurchaseOrderLineItem(purchase_order=po, **data)
                    li.full_clean()
                    li.save()

            # Append-only mirror: any previously-appended invoice_only line
            # not re-sent this call exists only on a stale prior statement
            # of the bill — drop it, per-line via the repo's mandated
            # renumbering delete path (never raw QuerySet/.delete()).
            for pk, li in existing_invoice_only.items():
                if pk not in seen_invoice_only_ids:
                    LineItemService.delete_line_item_with_renumber(li)

            po.bill_total = (
                None if bill_total is None
                else (bill_total if isinstance(bill_total, Decimal)
                      else Decimal(str(bill_total)))
            )
            po.vendor_invoice_ref = vendor_invoice_ref or ''
            po.reconciled = True
            po.reconciled_date = timezone.now()
            po.full_clean()
            po.save()

        return po

    @staticmethod
    def _default_markup_percent():
        """The system's one "default markup" Configuration row. Named
        `default_material_markup_percent` (materials app) and used
        elsewhere to derive InventoryItem `selling_price` from
        `purchase_price` — but it's already reused beyond that literal
        scope (`MaterialService.establish_reverse_markup` uses it to price
        a bare-material hand-line at crystallization), so it functions as
        the codebase's one generic cost→sell markup rather than something
        InventoryItem-exclusive. No task/service-specific markup
        Configuration key exists anywhere in the codebase (verified by
        grep) — this is the config `compute_rate_prompts` below reuses for
        spec §7 rule 4's "final × markup" task-rate suggestion.

        Returns (percent: Decimal | None, found: bool).
        """
        from apps.core.models import Configuration
        try:
            raw = Configuration.objects.get(key='default_material_markup_percent').value
        except Configuration.DoesNotExist:
            return None, False
        try:
            return Decimal(raw), True
        except Exception:
            return None, False

    @staticmethod
    def compute_rate_prompts(po):
        """Task-rate prompt support (spec §7 rule 4, task-owned-money Phase
        5 Task 2): for each PO line with a clean (non-null) `final_price`
        whose linked task is not yet on a live invoice, suggest updating
        that task's rate. NEVER mutates anything — purely a read: the
        client offers the prompt and, on accept, PATCHes the task itself
        through the existing money-gated path (no endpoint here accepts
        the suggestion).

        suggested_rate = final_price × (1 + markup/100) when
        `default_material_markup_percent` exists (see
        `_default_markup_percent`); otherwise suggested_rate = final_price
        and the caller should surface `markup_applied=False`.

        Returns (prompts: list[dict], markup_applied: bool). Each prompt:
        {'task_id', 'task_name', 'current_rate', 'suggested_rate'}.
        """
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource

        markup_percent, markup_applied = PurchaseOrderService._default_markup_percent()

        prompts = []
        lines = (
            PurchaseOrderLineItem.objects
            .filter(purchase_order=po, final_price__isnull=False, task__isnull=False)
            .select_related('task')
        )
        for li in lines:
            task = li.task
            if InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, task.pk):
                continue
            if markup_applied:
                suggested = (
                    li.final_price * (Decimal('1') + markup_percent / Decimal('100'))
                ).quantize(Decimal('0.01'))
            else:
                suggested = li.final_price
            prompts.append({
                'task_id': task.pk,
                'task_name': task.name,
                'current_rate': task.rate,
                'suggested_rate': suggested,
            })
        return prompts, markup_applied

    @staticmethod
    def _sever_line_material(li, sever_decision):
        """If line has a pending linked Material, require decision and apply.
        No-op if no Material or Material is consumed."""
        from apps.inventory.models import Material
        from apps.inventory.services import MaterialService
        existing = li.linked_material
        if existing is None or existing.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            return
        if sever_decision is None:
            raise ValidationError(
                f'sever_decision is required; line #{li.line_number} has a linked Material.'
            )
        MaterialService.sever(existing, sever_decision)

    @staticmethod
    def _validate_sever_decisions(line_items, sever_decisions):
        """Raise ValidationError if any line needs a sever decision and none was supplied."""
        from apps.inventory.models import Material
        for li in line_items:
            existing = li.linked_material
            if existing is None or existing.consumption_state != Material.CONSUMPTION_STATE_PENDING:
                continue
            if sever_decisions.get(li.pk) is None:
                raise ValidationError(
                    f'sever_decision is required; line #{li.line_number} has a linked Material.'
                )

    @staticmethod
    def cancel_po(pk, sever_decisions=None):
        """Cancel an issued PO and mark all line items as cancelled.

        Any line with a pending linked Material requires an entry in
        `sever_decisions` ({line_item_id: 'keep'|'delete'}). The validation
        pass runs before the atomic block so we don't open a transaction
        we'll just abort.
        """
        sever_decisions = sever_decisions or {}
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != PurchaseOrder.STATUS_ISSUED:
            raise ValidationError(
                f'Cannot cancel PO {po.po_number}. Only issued POs can be cancelled.'
            )

        line_items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))

        PurchaseOrderService._validate_sever_decisions(line_items, sever_decisions)

        with transaction.atomic():
            for li in line_items:
                PurchaseOrderService._sever_line_material(li, sever_decisions.get(li.pk))
                li.qty_cancelled = li.qty - li.qty_received
                li.save(update_fields=['qty_cancelled'])
            po.status = PurchaseOrder.STATUS_CANCELLED
            po.full_clean()
            po.save()
        return po

    @staticmethod
    def delete_po(pk, sever_decisions=None):
        """Delete a draft PO.

        Any line with a pending linked Material requires an entry in
        `sever_decisions` ({line_item_id: 'keep'|'delete'}). The validation
        pass runs before the atomic block.
        """
        sever_decisions = sever_decisions or {}
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot delete PO {po.po_number}. Only draft POs can be deleted.'
            )

        line_items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))

        PurchaseOrderService._validate_sever_decisions(line_items, sever_decisions)

        with transaction.atomic():
            for li in line_items:
                PurchaseOrderService._sever_line_material(li, sever_decisions.get(li.pk))
            po.delete()

    @staticmethod
    def _validate_draft(po):
        if po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Can only modify line items on draft purchase orders.'
            )

    @staticmethod
    def _resolve_material_for_line(li, job_id, material_id):
        """Common job/material resolution for newly-created PO lines.

        Looks up the Job by id (raises ValidationError on miss), then delegates
        to MaterialService.resolve_or_create_for_line. No-op if both are None.
        """
        if job_id is None and material_id is None:
            return
        from apps.inventory.services import MaterialService
        job_obj = None
        if job_id is not None:
            from apps.jobs.models import Job
            try:
                job_obj = Job.objects.get(pk=job_id)
            except Job.DoesNotExist:
                raise ValidationError(f'Job {job_id} not found')
        MaterialService.resolve_or_create_for_line(
            li,
            job=job_obj,
            inventory_item=li.inventory_item,
            qty=li.qty,
            unit_cost=li.price,
            description=li.description,
            accounting_category=li.accounting_category,
            material_id=material_id,
        )

    @staticmethod
    def add_line_item(po_id, **kwargs):
        """Add a manual line item to a draft PO. Accepts optional transient job, material_id."""
        from apps.core.services import LineItemService
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)

        # Pop transient params before they hit the model constructor
        job_id = kwargs.pop('job', None)
        material_id = kwargs.pop('material_id', None)

        kwargs = LineItemService.normalize_fk_kwargs(PurchaseOrderLineItem, kwargs)
        with transaction.atomic():
            li = PurchaseOrderLineItem(purchase_order=po, **kwargs)
            li.full_clean()
            li.save()
            PurchaseOrderService._resolve_material_for_line(li, job_id, material_id)
        return li

    @staticmethod
    def add_line_item_from_pli(po_id, inventory_item_id, qty, job=None, material_id=None):
        """Add a line item from a InventoryItem to a draft PO. Accepts optional job, material_id."""
        from apps.inventory.models import InventoryItem
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)
        try:
            pli = InventoryItem.objects.get(pk=inventory_item_id)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {inventory_item_id} not found')
        with transaction.atomic():
            li = PurchaseOrderLineItem(
                purchase_order=po,
                inventory_item=pli,
                description=pli.description,
                qty=qty,
                units=pli.units,
                price=pli.purchase_price,
                accounting_category=pli.accounting_category,
            )
            li.full_clean()
            li.save()
            PurchaseOrderService._resolve_material_for_line(li, job, material_id)
        return li

    @staticmethod
    def change_line_job(line_item_id, new_job_id, sever_decision=None):
        """Change a PO line's job attribution. Allowed on any non-cancelled PO
        as long as the linked Material (if any) is pending.

        If the line already has a linked Material, `sever_decision` ('keep'|'delete')
        is required. 'keep' unlinks the existing Material from the PO line (it stays
        on the old job); 'delete' removes the Material and backs out its earmark.

        If `new_job_id` is None, the line is left unattributed (no new Material
        is created). Otherwise the resolver runs against the new job to attach
        a new Material.
        """
        from apps.inventory.services import MaterialService
        from apps.jobs.models import Job

        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status == PurchaseOrder.STATUS_CANCELLED:
            raise ValidationError('Cannot change job on a cancelled PO.')

        new_job_obj = None
        if new_job_id is not None:
            try:
                new_job_obj = Job.objects.get(pk=new_job_id)
            except Job.DoesNotExist:
                raise ValidationError(f'Job {new_job_id} not found')

        with transaction.atomic():
            existing = li.linked_material
            if existing is not None:
                if sever_decision is None:
                    raise ValidationError(
                        'sever_decision is required when the line has a linked Material.'
                    )
                MaterialService.sever(existing, sever_decision)

            if new_job_obj is not None:
                # Inlined (not via _resolve_material_for_line) because we already have new_job_obj.
                MaterialService.resolve_or_create_for_line(
                    li,
                    job=new_job_obj,
                    inventory_item=li.inventory_item,
                    qty=li.qty,
                    unit_cost=li.price,
                    description=li.description,
                    accounting_category=li.accounting_category,
                )
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update a PO line item — validates draft status."""
        from apps.core.services import LineItemService
        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        PurchaseOrderService._validate_draft(li.purchase_order)
        kwargs = LineItemService.normalize_fk_kwargs(PurchaseOrderLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(po_id, item_ids):
        """Reorder PO line items by position list — validates draft status."""
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                PurchaseOrderLineItem.objects.filter(
                    pk=item_id, purchase_order=po,
                ).update(line_number=position)

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder a PO line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft purchase order.'
            )
        return LineItemService.reorder_line_item(li, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete a PO line item and renumber — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft purchase order.'
            )
        return LineItemService.delete_line_item_with_renumber(li)


class PurchaseOrderReceivingService:
    """Service for receiving goods against purchase orders."""

    @staticmethod
    def receive_items(po, items, user):
        """Record receipt of items on a PO.
        Material.quantity is unchanged — planned consumption is set at line-add time.
        QOH bumps by received qty for inventoried PLIs. Overage is accepted."""
        from apps.inventory.services import InventoryService

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot receive items on a PO in status "{po.status}".'
            )

        now = timezone.now()
        history_lines = []
        inventory_updates = []

        with transaction.atomic():
            for item_data in items:
                li = PurchaseOrderLineItem.objects.select_for_update().get(
                    pk=item_data['line_item_id'],
                    purchase_order=po,
                )
                if li.invoice_only:
                    raise ValidationError(
                        f'Line item #{li.line_number} is invoice-only and '
                        'excluded from receiving.'
                    )
                qty = Decimal(str(item_data['qty_received']))
                if qty <= 0:
                    continue

                li.qty_received = li.qty_received + qty
                li.received_by = user
                li.received_date = now
                if item_data.get('note'):
                    li.receipt_note = item_data['note']
                li.save()

                history_lines.append(
                    f'#{li.line_number} {li.description}: received {qty}'
                    + (f' — {item_data["note"]}' if item_data.get('note') else '')
                )

                # QOH for inventoried PLI-backed lines
                if li.inventory_item:
                    li.inventory_item.qty_on_hand += qty
                    li.inventory_item.save(update_fields=['qty_on_hand'])
                    li.inventory_item.refresh_from_db()
                    InventoryService._record_qoh_history(
                        li.inventory_item, qty, action='PO receipt',
                        reason=f'Received on {po.po_number}',
                        user=user, document=po.po_number,
                    )
                    inventory_updates.append(li.inventory_item.code)

            PurchaseOrderReceivingService._update_po_status(po)

            if history_lines:
                action_text = f'Items received by {user.get_full_name() or user.username}'
                if inventory_updates:
                    action_text += f'. Inventory updated: {", ".join(inventory_updates)}'
                record_history(
                    entry_type='action',
                    object_type='purchaseorder',
                    object_id=po.pk,
                    user=user,
                    changes={'_action': action_text},
                    text='\n'.join(history_lines),
                )
        return po

    @staticmethod
    def receive_all(po, user):
        """
        Receive all remaining items on a PO at full quantity. `invoice_only`
        lines (reconciliation-appended, e.g. freight) are excluded — they
        were never ordered/received and take no part in receiving flows.
        """
        line_items = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, invoice_only=False,
        )
        items = []
        for li in line_items:
            remaining = li.qty - li.qty_received - li.qty_cancelled
            if remaining > 0:
                items.append({
                    'line_item_id': li.pk,
                    'qty_received': remaining,
                })

        if not items:
            raise ValidationError('No items remaining to receive.')

        return PurchaseOrderReceivingService.receive_items(po, items, user)

    @staticmethod
    def cancel_line_item(po, line_item_id, note='', sever_decision=None):
        """Cancel remaining quantity on a line item.

        If the line has a pending linked Material, `sever_decision`
        ('keep'|'delete') is required.
        """

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot cancel line items on a PO in status "{po.status}".'
            )

        with transaction.atomic():
            li = PurchaseOrderLineItem.objects.select_for_update().get(
                pk=line_item_id, purchase_order=po,
            )
            if li.qty_received + li.qty_cancelled >= li.qty:
                raise ValidationError(
                    f'Line item #{li.line_number} has no outstanding quantity to cancel.'
                )

            PurchaseOrderService._sever_line_material(li, sever_decision)

            qty_to_cancel = li.qty - li.qty_received - li.qty_cancelled
            li.qty_cancelled = li.qty - li.qty_received
            li.save(update_fields=['qty_cancelled'])

            record_history(
                entry_type='action',
                object_type='purchaseorder',
                object_id=po.pk,
                changes={'_action': f'Line #{li.line_number} cancelled ({qty_to_cancel} remaining): {li.description}'},
                text=note,
            )

            PurchaseOrderReceivingService._update_po_status(po)

        return po

    @staticmethod
    def reverse_receipt(po, line_item_id, user, note=''):
        """Reverse all received quantity on a line item (data correction).

        Bumps QOH back down and resets the line's receipt fields. The linked
        Material (if any) is NOT touched — its quantity and earmark stay as
        they were planned. If the linked Material has already been consumed,
        the reversal is rejected (the caller must restock the Material first).
        """
        from apps.inventory.models import Material
        from apps.inventory.services import InventoryService

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
            PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        ):
            raise ValidationError(
                f'Cannot reverse receipts on a PO in status "{po.status}".'
            )

        with transaction.atomic():
            li = PurchaseOrderLineItem.objects.select_for_update().get(
                pk=line_item_id, purchase_order=po,
            )
            if li.qty_received <= 0:
                raise ValidationError(
                    f'Line item #{li.line_number} has no received quantity to reverse.'
                )

            existing_mat = li.linked_material
            if (existing_mat is not None
                    and existing_mat.consumption_state == Material.CONSUMPTION_STATE_CONSUMED):
                raise ValidationError(
                    f'Cannot reverse receipt on line #{li.line_number}: '
                    f'linked Material has been consumed. Restock the Material first.'
                )

            reversed_qty = li.qty_received

            if li.inventory_item:
                li.inventory_item.qty_on_hand -= reversed_qty
                li.inventory_item.save(update_fields=['qty_on_hand'])
                li.inventory_item.refresh_from_db()
                InventoryService._record_qoh_history(
                    li.inventory_item, -reversed_qty, action='PO receipt reversal',
                    reason=f'Reversed receipt on {po.po_number}',
                    user=user, document=po.po_number,
                )

            li.qty_received = Decimal('0.00')
            li.qty_cancelled = Decimal('0.00')
            li.received_by = None
            li.received_date = None
            li.receipt_note = ''
            li.save(update_fields=[
                'qty_received', 'qty_cancelled',
                'received_by', 'received_date', 'receipt_note',
            ])

            record_history(
                entry_type='action',
                object_type='purchaseorder',
                object_id=po.pk,
                user=user,
                changes={'_action': f'Line #{li.line_number} receipt reversed ({reversed_qty}): {li.description}'},
                text=note,
            )

            PurchaseOrderReceivingService._update_po_status(po)

        return po

    @staticmethod
    def _update_po_status(po):
        """Recalculate PO status based on line item receipt state.

        `invoice_only` lines (reconciliation-appended) are excluded from
        this computation (spec §7 rule 3) — they were never ordered or
        received, so their permanently-zero qty_received must never hold
        the PO back from (or knock it out of) `received_in_full`.
        """
        all_items = list(PurchaseOrderLineItem.objects.filter(
            purchase_order=po, invoice_only=False,
        ))
        if not all_items:
            return

        all_done = all(li.qty_received + li.qty_cancelled >= li.qty for li in all_items)
        any_received = any(li.qty_received > 0 for li in all_items)

        if all_done and any_received:
            if po.status != PurchaseOrder.STATUS_RECEIVED_IN_FULL:
                po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
                po.full_clean()
                po.save()
        elif all_done and not any_received:
            # Everything cancelled, nothing received — delegate to cancel_po
            # which handles status change AND sets qty_cancelled on all line items
            if po.status != PurchaseOrder.STATUS_CANCELLED:
                PurchaseOrderService.cancel_po(po.pk)
                po.refresh_from_db()
        elif any_received:
            if po.status != PurchaseOrder.STATUS_PARTLY_RECEIVED:
                po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
                po.full_clean()
                po.save()
        else:
            # Nothing received, not all done — back to issued
            if po.status not in (PurchaseOrder.STATUS_ISSUED, PurchaseOrder.STATUS_DRAFT):
                po.status = PurchaseOrder.STATUS_ISSUED
                po.full_clean()
                po.save()


class PurchaseOrderEmailService:
    """Service for sending purchase orders to vendors via email."""

    DEFAULT_SUBJECT = 'Purchase Order {po_number}'
    DEFAULT_BODY = (
        'Please find attached Purchase Order {po_number}.\n\n'
        'If you have any questions, please contact us.\n\n'
        'Thank you.'
    )

    @staticmethod
    def get_email_defaults(po, user=None):
        """Get the pre-populated email fields for a PO."""
        from apps.core.models import Configuration

        subject_template = PurchaseOrderEmailService.DEFAULT_SUBJECT
        body_template = PurchaseOrderEmailService.DEFAULT_BODY

        try:
            subject_template = Configuration.objects.get(
                key='po_email_subject_template'
            ).value
        except Configuration.DoesNotExist:
            pass

        try:
            body_template = Configuration.objects.get(
                key='po_email_body_template'
            ).value
        except Configuration.DoesNotExist:
            pass

        vendor_name = po.business.business_name if po.business else ''

        replacements = {
            'po_number': po.po_number,
            'vendor_name': vendor_name,
        }

        # Extend the legacy {po_number} / {vendor_name} variables with the
        # common set used by Estimate and Invoice templates, via the safe
        # render helper (unknown placeholders pass through unchanged).
        from apps.core.email_templates import render_email_template
        contact = po.contact
        contact_fname = contact.first_name if contact else ''
        contact_lname = contact.last_name if contact else ''
        contact_business = ''
        if contact and contact.business:
            contact_business = contact.business.business_name
        from apps.core.email_templates import build_object_url, user_display_name
        common = {
            'contact_fname': contact_fname,
            'contact_lname': contact_lname,
            'contact_business': contact_business,
            'my_user_name': user_display_name(user),
            'document_number': po.po_number,
            'object_url': build_object_url('purchase_order', po.po_id),
        }
        all_values = {**common, **replacements}
        subject = render_email_template(subject_template, **all_values)
        body = render_email_template(body_template, **all_values)

        to = ''
        if po.contact and po.contact.email:
            to = po.contact.email

        attachments_preview = [
            {'filename': f'{po.po_number}.pdf',
             'content_type': 'application/pdf', 'size': 0},
        ]
        return {
            'to': to, 'subject': subject, 'body': body,
            'attachments_preview': attachments_preview,
        }

    @staticmethod
    def send_po(po, to, subject, body, cc=None, bcc=None,
                extra_attachments=None):
        """
        Send a PO as a PDF attachment via email through the tracked
        outbound flow (an outbound EmailRecord is persisted, linked to
        this PO; the email_records relation makes it show up in the Job
        overview Email panel and reply-correlation chain).

        If the PO is in draft status, it is issued first.
        Returns the updated PO.

        Raises ValidationError for missing recipient / no line items /
        invalid status. SMTP failures re-raise after the outbound
        EmailRecord has captured last_send_error.
        """
        from apps.core.services import OutboundEmailService
        from apps.purchasing.pdf import generate_purchase_order_pdf

        if not to:
            raise ValidationError('Recipient email address is required.')
        if isinstance(to, str):
            to = [addr.strip() for addr in to.split(',') if addr.strip()]
            if not to:
                raise ValidationError('Recipient email address is required.')

        if po.status == PurchaseOrder.STATUS_DRAFT:
            if not po.purchaseorderlineitem_set.exists():
                raise ValidationError(
                    'Cannot issue a PO with no line items.'
                )
            if po.business_id is None:
                raise ValidationError(
                    {'business': ['A purchase order needs a vendor before it can be issued.']})
            po.status = PurchaseOrder.STATUS_ISSUED
            po.full_clean()
            po.save()

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot send a PO in status "{po.status}".'
            )

        pdf_bytes = generate_purchase_order_pdf(po)
        filename = f'{po.po_number}.pdf'
        attachments = [(filename, pdf_bytes, 'application/pdf')]
        if extra_attachments:
            attachments.extend(extra_attachments)

        OutboundEmailService.send_tracked(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachments=attachments,
            associate_with={'purchase_order': po},
        )

        record_history(
            entry_type='action',
            object_type='purchaseorder',
            object_id=po.pk,
            changes={'_action': f'PO emailed to {", ".join(to)}'},
        )

        return po
