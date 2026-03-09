from rest_framework import viewsets
from apps.jobs.models import WorkOrder
from apps.jobs.services import WorkOrderService
from apps.api.mixins import StatusTransitionMixin, TaskBundleMixin
from apps.api.worksheets.serializers import TaskSerializer, TaskBundleSerializer
from .serializers import WorkOrderSerializer


class WorkOrderViewSet(StatusTransitionMixin, TaskBundleMixin, viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all().order_by('-pk')
    serializer_class = WorkOrderSerializer
    lookup_field = 'pk'

    # TaskBundleMixin config
    task_serializer_class = TaskSerializer
    bundle_serializer_class = TaskBundleSerializer
    container_field = 'work_order'

    status_actions = {
        'complete': {
            'service': lambda pk: WorkOrderService.update_status(pk, 'complete'),
        },
        'block': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, 'blocked'),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, 'incomplete'),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        wo = WorkOrderService.create_direct(job)
        serializer.instance = wo
