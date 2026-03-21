from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from apps.api.permissions import CanViewJobs, CanManageJobs
from .serializers import EstimateSerializer, EstimateLineItemSerializer


class EstimateViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Estimate.objects.all().order_by('-created_date')
    serializer_class = EstimateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), CanViewJobs()]
        return [IsAuthenticated(), CanManageJobs()]

    # Line item mixin config
    line_item_serializer_class = EstimateLineItemSerializer
    line_item_parent_field = 'estimate'

    # Status actions
    status_actions = {
        'mark-open': {'service': EstimateService.mark_open},
        'revise': {'service': EstimateService.revise_estimate},
    }

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)
        return qs

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        estimate = EstimateService.create_for_job(job_pk)
        serializer.instance = estimate

    def perform_update(self, serializer):
        serializer.save()
