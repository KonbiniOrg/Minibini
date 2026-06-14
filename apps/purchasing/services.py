from decimal import Decimal
from apps.core.history import record_history
from django.core.exceptions import ValidationError
from django.db import transaction

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
            price_list_item=li.price_list_item,
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
    def add_line_item_from_pli(po_id, price_list_item_id, qty, job=None, material_id=None):
        """Add a line item from a PriceListItem to a draft PO. Accepts optional job, material_id."""
        from apps.inventory.models import PriceListItem
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)
        try:
            pli = PriceListItem.objects.get(pk=price_list_item_id)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {price_list_item_id} not found')
        with transaction.atomic():
            li = PurchaseOrderLineItem(
                purchase_order=po,
                price_list_item=pli,
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
                    price_list_item=li.price_list_item,
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
        from apps.inventory.models import InventoryAdjustment
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
                if li.price_list_item and li.price_list_item.is_inventoried:
                    li.price_list_item.qty_on_hand += qty
                    li.price_list_item.save(update_fields=['qty_on_hand'])
                    InventoryAdjustment.objects.create(
                        price_list_item=li.price_list_item,
                        quantity_change=qty,
                        reason=f'Received on {po.po_number}',
                    )
                    inventory_updates.append(li.price_list_item.code)

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
        from apps.inventory.models import InventoryAdjustment, Material

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

            if li.price_list_item and li.price_list_item.is_inventoried:
                li.price_list_item.qty_on_hand -= reversed_qty
                li.price_list_item.save(update_fields=['qty_on_hand'])
                InventoryAdjustment.objects.create(
                    price_list_item=li.price_list_item,
                    quantity_change=-reversed_qty,
                    reason=f'Reversed receipt on {po.po_number}',
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
                price_list_item=po_li.price_list_item,
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
    def add_line_item_from_pli(bill_id, price_list_item_id, qty):
        """Add a line item from a PriceListItem to a draft bill."""
        from apps.inventory.models import PriceListItem
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        BillService._validate_draft(bill)
        try:
            pli = PriceListItem.objects.get(pk=price_list_item_id)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {price_list_item_id} not found')
        li = BillLineItem(
            bill=bill,
            price_list_item=pli,
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
