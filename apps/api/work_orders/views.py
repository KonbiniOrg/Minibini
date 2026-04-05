from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.jobs.models import WorkOrder
from apps.jobs.services import WorkOrderService
from apps.api.mixins import StatusTransitionMixin, WorkOrderTaskMixin
from apps.api.permissions import CanManageJobs
from .serializers import WorkOrderSerializer, TaskSerializer


class WorkOrderViewSet(StatusTransitionMixin, WorkOrderTaskMixin, viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all().order_by('-pk')
    serializer_class = WorkOrderSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action == 'tasks':
            # GET and POST are open to any authenticated user;
            # PATCH and DELETE on individual tasks require can_manage_jobs
            if self.request.method in ('GET', 'POST'):
                return [IsAuthenticated()]
            return [IsAuthenticated(), CanManageJobs()]
        return [IsAuthenticated(), CanManageJobs()]

    # WorkOrderTaskMixin config
    task_serializer_class = TaskSerializer

    status_actions = {
        'complete': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_COMPLETE),
            'requires_reason': True,
        },
        'block': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_BLOCKED),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_INCOMPLETE),
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
        data = serializer.validated_data
        job = data.get('job')
        wo = WorkOrderService.create_direct(job)
        serializer.instance = wo
