from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from apps.api.permissions import CanManageFinancials
from .serializers import InvoiceSerializer, InvoiceLineItemSerializer


class InvoiceViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Invoice.objects.all().order_by('-created_date')
    serializer_class = InvoiceSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    # Line item mixin config
    line_item_serializer_class = InvoiceLineItemSerializer
    line_item_parent_field = 'invoice'
    line_item_service_class = InvoiceService

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: Invoice.objects.filter(pk=pk).update(status=Invoice.STATUS_CANCELLED),
            'requires_reason': True,
        },
    }

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)
        return qs

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool tree for the wizard."""
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        pool = InvoiceWizardService.get_source_pool(invoice)
        # Decimals need to be serialized as strings
        return Response(_serialize_pool(pool))

    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new line item from a list of atoms."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict
        invoice = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = InvoiceWizardService.add_atoms_to_new_line_item(invoice, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=201)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        atoms = request.data.get('atoms', [])
        try:
            InvoiceWizardService.add_atoms_to_line_item(line_item, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        line_item.refresh_from_db()
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=200)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        source_ids = request.data.get('source_ids', [])
        try:
            result = InvoiceWizardService.remove_atoms_from_line_item(
                line_item, source_ids,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': InvoiceLineItemSerializer(line_item).data,
        })

    @action(detail=True, methods=['post'], url_path='send-to-qbo')
    def send_to_qbo(self, request, pk=None):
        """Push this invoice to QBO, attach PDF, and send to customer."""
        invoice = self.get_object()
        send_to = request.data.get('send_to')
        if not send_to:
            return Response(
                {'error': 'send_to email address is required'},
                status=400,
            )

        cc = request.data.get('cc', None)
        bcc = request.data.get('bcc', None)

        try:
            from apps.qbo.services import QBOInvoiceSyncService
            qbo_id = QBOInvoiceSyncService.push_invoice(
                invoice, send_to=send_to, cc=cc, bcc=bcc,
            )
            return Response({
                'qbo_id': qbo_id,
                'status': 'sent',
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


def _serialize_pool(pool):
    """Convert Decimal values in the pool structure to strings for JSON."""
    from decimal import Decimal
    def _s(value):
        if isinstance(value, Decimal):
            return str(value)
        return value
    return {
        'work_orders': [
            {
                'work_order_id': wo['work_order_id'],
                'tasks': [
                    {
                        'task_id': t['task_id'],
                        'name': t['name'],
                        'has_billable_atoms': t['has_billable_atoms'],
                        'atoms': [
                            {k: _s(v) for k, v in atom.items()}
                            for atom in t['atoms']
                        ],
                    }
                    for t in wo['tasks']
                ],
            }
            for wo in pool['work_orders']
        ],
    }
