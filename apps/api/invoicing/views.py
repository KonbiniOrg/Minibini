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
