from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import (
    F, Sum, Value, Case, When, DecimalField, ExpressionWrapper,
    OuterRef, Subquery, Q,
)
from django.db.models.functions import Coalesce
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import (
    PurchaseOrderService, PurchaseOrderEmailService,
    PurchaseOrderReceivingService,
)
from apps.core.services import ServiceError, NotFoundError
from apps.core.models import PurchasingHistory
from apps.core.history import record_history
from apps.api.mixins import StatusTransitionMixin, LineItemMixin, JSONDestroyMixin
from apps.api.permissions import CanManageFinancials
from apps.api.history.serializers import HistoryEntrySerializer
from .serializers import (
    PurchaseOrderSerializer, POLineItemSerializer,
)

_BILL_MONEY = DecimalField(max_digits=12, decimal_places=2)


def _coerce_sever_decisions(raw):
    """Normalize a sever-decisions map from the request body. JSON object keys
    arrive as strings ({"42": "keep"}), but the service looks up line items by
    int pk, so coerce keys to int. Returns None when nothing was supplied.
    Raises ValueError on a non-int key."""
    if not raw:
        return None
    return {int(k): v for k, v in raw.items()}




class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().prefetch_related(
        'purchaseorderlineitem_set__task__job',
    ).order_by('-created_date')
    serializer_class = PurchaseOrderSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in (
            'list', 'retrieve', 'history', 'notes', 'send_defaults',
            'receive', 'receive_all', 'receipts', 'cancel_line_item', 'reverse_receipt',
        ):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    def get_queryset(self):
        qs = super().get_queryset()
        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        job = self.request.query_params.get('job')
        if job:
            from apps.inventory.models import Material
            line_ids = Material.objects.filter(
                job=job, po_line_item__isnull=False,
            ).values_list('po_line_item_id', flat=True)
            qs = qs.filter(purchaseorderlineitem__in=line_ids).distinct()
        po_status = self.request.query_params.get('status')
        if po_status:
            qs = qs.filter(status=po_status)
        awaiting = self.request.query_params.get('awaiting_reconciliation')
        if awaiting is not None and awaiting.lower() in ('true', '1', 'yes'):
            qs = qs.awaiting_reconciliation()
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(po_number__icontains=search)
                | Q(business__business_name__icontains=search)
            )
        return qs

    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'
    line_item_service_class = PurchaseOrderService

    # Note: 'cancel' and 'destroy' are explicitly overridden below to accept
    # `sever_decisions`, so we only register 'issue' here.
    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, PurchaseOrder.STATUS_ISSUED),
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = PurchaseOrderService.create_po(**data)
        serializer.instance = po

    def perform_update(self, serializer):
        po = PurchaseOrderService.update_po(self.get_object().pk, **serializer.validated_data)
        serializer.instance = po

    def destroy(self, request, *args, **kwargs):
        """Delete a draft PO. Accepts `sever_decisions` in body for lines
        with pending linked Materials."""
        po = self.get_object()
        try:
            sever_decisions = _coerce_sever_decisions(
                request.data.get('sever_decisions') if request.data else None)
        except (ValueError, AttributeError):
            return Response({'detail': 'Invalid sever_decisions.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            PurchaseOrderService.delete_po(po.pk, sever_decisions=sever_decisions)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': f'PO {po.po_number} deleted.'})

    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        """Line-item list (GET) / create (POST). POST accepts transient job, material_id."""
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        service = self.line_item_service_class
        data = request.data.copy()
        pli_id = data.get('inventory_item')
        has_manual_fields = data.get('description') or data.get('price')
        job = data.pop('job', None)
        material_id = data.pop('material_id', None)
        # `task` is writable (task-owned-money Phase 5, spec §7 rule 1):
        # cost→sell link. Model-level `clean()` rejects a subtask link
        # (400, field-shaped) and requires the task be job-bearing.

        try:
            if pli_id and not has_manual_fields:
                qty = data.get('qty', 0)
                item = service.add_line_item_from_pli(
                    parent.pk, pli_id, qty, job=job, material_id=material_id,
                )
            else:
                if job is not None:
                    data['job'] = job
                if material_id is not None:
                    data['material_id'] = material_id
                item = service.add_line_item(parent.pk, **data)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        """Line-item PATCH/DELETE. PATCH dispatches to change_line_job if payload
        has only 'job' (and optional 'sever_decision')."""
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)
        service = self.line_item_service_class

        if request.method == 'DELETE':
            try:
                service.delete_line_item(item.pk)
            except NotFoundError as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'message': 'Line item deleted.'})

        data = request.data.copy()
        job_keys = {'job', 'sever_decision'}
        is_job_only = set(data.keys()).issubset(job_keys) and 'job' in data
        try:
            if is_job_only:
                service.change_line_job(
                    item.pk, data.get('job'), sever_decision=data.get('sever_decision'),
                )
                item.refresh_from_db()
            else:
                # Strip transient/job-routing fields before generic update
                data.pop('job', None)
                data.pop('sever_decision', None)
                data.pop('material_id', None)
                item = service.update_line_item(item.pk, **data)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='cancel', url_name='cancel')
    def cancel(self, request, pk=None):
        """Cancel an issued PO. Accepts `reason` (optional, audit) and
        `sever_decisions` ({line_item_id: 'keep'|'delete'})."""
        reason = request.data.get('reason', '').strip() if request.data else ''
        if not reason:
            return Response(
                {'reason': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            sever_decisions = _coerce_sever_decisions(request.data.get('sever_decisions'))
        except (ValueError, AttributeError):
            return Response({'detail': 'Invalid sever_decisions.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            po = PurchaseOrderService.cancel_po(pk, sever_decisions=sever_decisions)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Audit history entry mirroring StatusTransitionMixin behaviour
        from apps.core.history import get_history_context
        obj_type = po.__class__.__name__.lower()
        attached = False
        ctx = get_history_context()
        if ctx:
            for entry in reversed(ctx.pending):
                if (entry.get('object_type') == obj_type
                        and entry.get('entry_type') == 'audit'):
                    entry['text'] = reason
                    attached = True
                    break
        if not attached:
            record_history(
                entry_type='audit',
                object_type=obj_type,
                object_id=po.pk,
                text=reason,
            )

        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        po = self.get_object()
        entries = PurchasingHistory.objects.filter(
            object_type='purchaseorder', object_id=po.pk
        ).select_related('user')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='send-defaults', url_name='send-defaults')
    def send_defaults(self, request, pk=None):
        """Get pre-populated email fields for sending a PO."""
        po = self.get_object()
        defaults = PurchaseOrderEmailService.get_email_defaults(po, user=request.user)
        return Response(defaults)

    @action(detail=True, methods=['post'], url_path='send', url_name='send')
    def send(self, request, pk=None):
        """Send a PO to the vendor via email with PDF attachment.
        Accepts to/subject/body plus optional cc/bcc (comma-separated)
        and multipart 'attachments' uploads beyond the auto-attached PDF."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        po = self.get_object()
        to = request.data.get('to', '').strip()
        subject = request.data.get('subject', '').strip()
        body = request.data.get('body', '').strip()

        if not to:
            return Response(
                {'to': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not subject:
            return Response(
                {'subject': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cc = [c.strip() for c in request.data.get('cc', '').split(',') if c.strip()]
        bcc = [b.strip() for b in request.data.get('bcc', '').split(',') if b.strip()]
        extra_attachments = []
        for uploaded in request.FILES.getlist('attachments'):
            extra_attachments.append((
                uploaded.name, uploaded.read(),
                uploaded.content_type or 'application/octet-stream',
            ))

        try:
            po = PurchaseOrderEmailService.send_po(
                po, to=to, subject=subject, body=body,
                cc=cc, bcc=bcc, extra_attachments=extra_attachments,
            )
        except DjangoValidationError:
            raise  # plain validation errors render via the contract handler
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='notes', url_name='notes')
    def notes(self, request, pk=None):
        obj = self.get_object()
        text = request.data.get('text', '').strip()
        if not text:
            return Response(
                {'text': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = record_history(
            entry_type='note',
            object_type='purchaseorder',
            object_id=obj.pk,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='receive', url_name='receive')
    def receive(self, request, pk=None):
        """Record receipt of specific line items."""
        po = self.get_object()
        items = request.data.get('items', [])
        if not items:
            return Response(
                {'items': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.receive_items(
                po, items, request.user,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='receive-all', url_name='receive-all')
    def receive_all(self, request, pk=None):
        """Receive all remaining items at full quantity."""
        po = self.get_object()
        try:
            po = PurchaseOrderReceivingService.receive_all(po, request.user)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='cancel-line-item', url_name='cancel-line-item')
    def cancel_line_item(self, request, pk=None):
        """Cancel a line item that won't be shipped. Accepts optional
        `sever_decision` for lines with pending linked Materials."""
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        sever_decision = request.data.get('sever_decision')
        if not line_item_id:
            return Response(
                {'line_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.cancel_line_item(
                po, line_item_id, note=note,
                sever_decision=sever_decision,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reverse-receipt', url_name='reverse-receipt')
    def reverse_receipt(self, request, pk=None):
        """Reverse all received quantity on a line item."""
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        if not line_item_id:
            return Response(
                {'line_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.reverse_receipt(
                po, line_item_id, request.user, note=note,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reconcile', url_name='reconcile')
    def reconcile(self, request, pk=None):
        """Record vendor-bill reconciliation data against this PO (spec §7
        rule 3; CanManageFinancials, via the default `get_permissions()`
        gate below — reconcile isn't in the IsAuthenticated-only action
        list). Body: `bill_total`, `vendor_invoice_ref`, `line_finals`
        ({line_item_id: Decimal}), `appended_lines` (invoice_only lines —
        append-only mirror of the bill; see
        `PurchaseOrderService.reconcile` docstring for drop/replace/keep
        semantics).

        Response is the updated PO plus `rate_prompts` (spec §7 rule 4) —
        this endpoint never mutates a task; the client offers each prompt
        and, on accept, PATCHes the task itself through the existing
        money-gated path.
        """
        po = self.get_object()
        bill_total = request.data.get('bill_total')
        vendor_invoice_ref = request.data.get('vendor_invoice_ref', '')
        raw_line_finals = request.data.get('line_finals') or {}
        appended_lines = request.data.get('appended_lines') or []

        try:
            line_finals = {int(k): v for k, v in raw_line_finals.items()}
        except (ValueError, TypeError, AttributeError):
            return Response(
                {'line_finals': ['Must be an object keyed by line item id.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            po = PurchaseOrderService.reconcile(
                po.pk, bill_total=bill_total, vendor_invoice_ref=vendor_invoice_ref,
                line_finals=line_finals, appended_lines=appended_lines,
            )
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        rate_prompts, markup_applied = PurchaseOrderService.compute_rate_prompts(po)
        serializer = self.get_serializer(po)
        data = serializer.data
        data['rate_prompts'] = rate_prompts
        data['markup_applied'] = markup_applied
        return Response(data)
