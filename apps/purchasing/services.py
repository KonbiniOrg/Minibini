import logging
from decimal import Decimal
from apps.core.history import record_history
from django.core.exceptions import ValidationError
from django.db import transaction

logger = logging.getLogger(__name__)

from apps.purchasing.models import (
    PurchaseOrder, Bill, PurchaseOrderLineItem, BillLineItem,
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
        po.status = new_status
        po.full_clean()
        po.save()
        return po

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
        from django.utils import timezone

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
        Receive all remaining items on a PO at full quantity.
        """
        line_items = PurchaseOrderLineItem.objects.filter(purchase_order=po)
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
    def cancel_line_item(po, line_item_id, user, note='', sever_decision=None):
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
                user=user,
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
        """Recalculate PO status based on line item receipt state."""
        all_items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
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
    def get_email_defaults(po):
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
        from apps.core.email_templates import build_object_url
        common = {
            'contact_fname': contact_fname,
            'contact_lname': contact_lname,
            'contact_business': contact_business,
            'my_user_name': '',
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
                extra_attachments=None, user=None):
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
            user=user,
            changes={'_action': f'PO emailed to {", ".join(to)}'},
        )

        return po


class BillService:
    """Service for bill operations."""

    @staticmethod
    def create_bill(**kwargs):
        """Create a new Bill."""
        bill = Bill(**kwargs)
        bill.full_clean()
        bill.save()
        return bill

    @staticmethod
    def update_bill(pk, **kwargs):
        """Update a draft bill's header fields. Draft-only."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        if bill.status != Bill.STATUS_DRAFT:
            raise ValidationError('Can only edit draft bills.')
        for field, value in kwargs.items():
            setattr(bill, field, value)
        bill.full_clean()
        bill.save()
        return bill

    @staticmethod
    @transaction.atomic
    def create_bill_from_po(po_id, **kwargs):
        """Create a bill from a PO, copying its line items."""
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')

        bill = Bill(
            purchase_order=po,
            business=po.business,
            contact=po.contact,
            **kwargs,
        )
        bill.full_clean()
        bill.save()

        # Copy line items from PO
        po_line_items = PurchaseOrderLineItem.objects.filter(
            purchase_order=po
        ).order_by('line_number')
        for po_li in po_line_items:
            BillLineItem.objects.create(
                bill=bill,
                inventory_item=po_li.inventory_item,
                task=po_li.task,
                description=po_li.description,
                qty=po_li.qty,
                units=po_li.units,
                price=po_li.price,
                line_number=po_li.line_number,
                accounting_category=po_li.accounting_category,
            )

        return bill

    @staticmethod
    def update_status(pk, new_status):
        """Update bill status."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        bill.status = new_status
        bill.full_clean()
        bill.save()
        return bill

    @staticmethod
    def delete_bill(pk):
        """Delete a draft bill."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        if bill.status != Bill.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot delete Bill {bill.vendor_invoice_number or bill.pk}. '
                'Only draft bills can be deleted.'
            )
        bill.delete()

    @staticmethod
    def _validate_draft(bill):
        if bill.status != Bill.STATUS_DRAFT:
            raise ValidationError(
                'Can only modify line items on draft bills.'
            )

    @staticmethod
    def add_line_item(bill_id, **kwargs):
        """Add a manual line item to a draft bill."""
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        BillService._validate_draft(bill)
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(BillLineItem, kwargs)
        li = BillLineItem(bill=bill, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(bill_id, inventory_item_id, qty):
        """Add a line item from a InventoryItem to a draft bill."""
        from apps.inventory.models import InventoryItem
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        BillService._validate_draft(bill)
        try:
            pli = InventoryItem.objects.get(pk=inventory_item_id)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {inventory_item_id} not found')
        li = BillLineItem(
            bill=bill,
            inventory_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.purchase_price,
            accounting_category=pli.accounting_category,
        )
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update a bill line item — validates draft status."""
        from apps.core.services import LineItemService
        try:
            li = BillLineItem.objects.get(pk=line_item_id)
        except BillLineItem.DoesNotExist:
            raise NotFoundError(f'BillLineItem {line_item_id} not found')
        BillService._validate_draft(li.bill)
        kwargs = LineItemService.normalize_fk_kwargs(BillLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(bill_id, item_ids):
        """Reorder bill line items by position list — validates draft status."""
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        BillService._validate_draft(bill)
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                BillLineItem.objects.filter(
                    pk=item_id, bill=bill,
                ).update(line_number=position)

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder a bill line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = BillLineItem.objects.get(pk=line_item_id)
        except BillLineItem.DoesNotExist:
            raise NotFoundError(f'BillLineItem {line_item_id} not found')
        if li.bill.status != Bill.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft bill.'
            )
        return LineItemService.reorder_line_item(li, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete a bill line item and renumber — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = BillLineItem.objects.get(pk=line_item_id)
        except BillLineItem.DoesNotExist:
            raise NotFoundError(f'BillLineItem {line_item_id} not found')
        if li.bill.status != Bill.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft bill.'
            )
        return LineItemService.delete_line_item_with_renumber(li)


class BillPaymentService:
    """Sole writer of BillPayment rows; recomputes Bill.status on every change."""

    _PAYABLE = (Bill.STATUS_RECEIVED, Bill.STATUS_PARTLY_PAID)

    @staticmethod
    def _normalize_amount(value):
        """Convert an incoming amount to an exact Decimal. A JSON number arrives
        as a Python float whose binary value (e.g. 33.33 -> 33.32999...) would
        trip the DecimalField's decimal_places=2 validator. ``str()`` yields the
        shortest round-trip decimal, so 33.33 stays 33.33; genuine over-precision
        (e.g. 33.333) survives and is still rejected by ``full_clean``."""
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError('Invalid payment amount.')

    @staticmethod
    @transaction.atomic
    def record_payment(bill, *, amount, payment_date, reference='', payment_account_id='', user=None):
        from apps.purchasing.models import BillPayment
        if bill.status not in BillPaymentService._PAYABLE:
            raise ValidationError(
                f'Cannot record a payment on a bill in status "{bill.status}". '
                'The bill must be received or partly paid.'
            )
        amount = BillPaymentService._normalize_amount(amount)
        payment = BillPayment(
            bill=bill, amount=amount, payment_date=payment_date,
            reference=reference, payment_account_id=payment_account_id or '',
            created_by=user,
        )
        payment.full_clean()
        payment.save()
        bill.recompute_payment_status()
        # Build history string: enrich with account display_name when resolvable.
        history_action = f'Payment recorded: {amount}'
        if payment_account_id:
            try:
                from apps.qbo.services import QBOPaymentAccountService
                display_name = QBOPaymentAccountService.lookup(payment_account_id)['display_name']
                history_action = f'Payment recorded: {amount} from {display_name}'
            except (ValueError, KeyError):
                pass
        if reference:
            history_action += f' (ref {reference})'
        record_history(
            entry_type='action', object_type='bill', object_id=bill.pk,
            user=user,
            changes={'_action': history_action},
        )
        BillPaymentService._push_to_qbo(payment)
        return payment

    @staticmethod
    def _push_to_qbo(payment):
        """Immediate push-on-action. Failure is swallowed-and-logged because
        inbound clearance polling self-heals state later."""
        try:
            from apps.qbo.services import QBOBillSyncService
            QBOBillSyncService.push_bill_payment(payment)
        except Exception:  # noqa: BLE001 - never block recording on a QBO hiccup
            logger.exception('QBO bill-payment push failed for payment %s', payment.pk)

    @staticmethod
    @transaction.atomic
    def update_payment(payment_id, **out_fields):
        from apps.purchasing.models import BillPayment
        try:
            payment = BillPayment.objects.get(pk=payment_id)
        except BillPayment.DoesNotExist:
            raise NotFoundError(f'BillPayment {payment_id} not found')
        if payment.bill.status in (Bill.STATUS_CANCELLED, Bill.STATUS_REFUNDED):
            raise ValidationError(
                'Cannot edit a payment on a cancelled or refunded bill.'
            )
        allowed = {'amount', 'payment_date', 'reference'}
        for field, value in out_fields.items():
            if field in allowed:
                if field == 'amount':
                    value = BillPaymentService._normalize_amount(value)
                setattr(payment, field, value)
        payment.full_clean()
        payment.save()
        payment.bill.recompute_payment_status()
        # QBO resync (best-effort; never blocks the local edit).
        from apps.qbo.services import QBOBillSyncService, QBOSyncService
        if payment.qbo_id:
            QBOSyncService.run_resync(
                payment, lambda: QBOBillSyncService.update_bill_payment(payment))
        else:
            QBOBillSyncService.push_bill_payment(payment)
        return payment

    @staticmethod
    def delete_payment(payment_id):
        from apps.purchasing.models import BillPayment
        try:
            payment = BillPayment.objects.get(pk=payment_id)
        except BillPayment.DoesNotExist:
            raise NotFoundError(f'BillPayment {payment_id} not found')
        # QBO void runs OUTSIDE the atomic block so that mark_failed (a save) can commit
        # even when the delete is refused.  run_delete → mark_failed → re-raises on failure.
        if payment.qbo_id:
            from apps.qbo.services import QBOBillSyncService, QBOSyncService
            try:
                QBOSyncService.run_delete(
                    payment, lambda: QBOBillSyncService.void_bill_payment(payment))
            except Exception:
                raise ValidationError(
                    'Could not delete this payment — its QuickBooks sync failed, so the payment '
                    'was kept (marked sync-failed). Retry once QuickBooks is reachable.'
                )
        # Local delete only runs when QBO void succeeded (or no qbo_id)
        with transaction.atomic():
            payment.delete()
            payment.bill.recompute_payment_status()
