from rest_framework.exceptions import MethodNotAllowed
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin, CreateModelMixin
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.jobs.models import PlanTask
from .serializers import PlanTaskDetailSerializer


class PlanTaskViewSet(RetrieveModelMixin, ListModelMixin, CreateModelMixin,
                      viewsets.GenericViewSet):
    """Read-only detail for PlanTasks.

    CRUD operations live on the worksheet nested endpoints:
    /api/est-worksheets/{id}/tasks/

    This standalone endpoint provides a detail view with full context
    (materials, worksheet, job) for use by the SPA when navigating
    directly to a plan task.
    """
    queryset = PlanTask.objects.select_related(
        'est_worksheet__job',
    ).prefetch_related('plan_materials')
    serializer_class = PlanTaskDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'

    def list(self, request, *args, **kwargs):
        raise MethodNotAllowed('GET')

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed('POST')
