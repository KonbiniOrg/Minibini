from rest_framework import viewsets
from apps.invoicing.models import Invoice
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import InvoiceSerializer, InvoiceLineItemSerializer


class InvoiceViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Invoice.objects.all().order_by('-created_date')
    serializer_class = InvoiceSerializer
    lookup_field = 'pk'

    # Line item mixin config
    line_item_serializer_class = InvoiceLineItemSerializer
    line_item_parent_field = 'invoice'

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: Invoice.objects.filter(pk=pk).update(status='cancelled'),
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
