from rest_framework import viewsets
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import EstimateSerializer, EstimateLineItemSerializer


class EstimateViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Estimate.objects.all().order_by('-created_date')
    serializer_class = EstimateSerializer
    lookup_field = 'pk'

    # Line item mixin config
    line_item_serializer_class = EstimateLineItemSerializer
    line_item_parent_field = 'estimate'

    # Status actions
    status_actions = {
        'mark-open': {'service': EstimateService.mark_open},
        'revise': {'service': EstimateService.revise_estimate},
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        estimate = EstimateService.create_for_job(job_pk)
        serializer.instance = estimate

    def perform_update(self, serializer):
        serializer.save()
