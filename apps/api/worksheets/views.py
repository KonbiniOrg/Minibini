from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import EstWorksheet
from apps.estimates.services import WorksheetService, EstimateGenerationService
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin, TaskBundleMixin
from apps.api.permissions import CanManageJobs
from .serializers import EstWorksheetSerializer, TaskSerializer, TaskBundleSerializer


class EstWorksheetViewSet(StatusTransitionMixin, TaskBundleMixin, viewsets.ModelViewSet):
    queryset = EstWorksheet.objects.all().order_by('-created_date')
    serializer_class = EstWorksheetSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('tasks', 'bundles')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    # TaskBundleMixin config
    task_serializer_class = TaskSerializer
    bundle_serializer_class = TaskBundleSerializer
    container_field = 'est_worksheet'

    status_actions = {
        'revise': {'service': WorksheetService.revise_worksheet},
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
        kwargs = {}
        template = data.get('template')
        if template:
            kwargs['template'] = template
        ws = WorksheetService.create_worksheet(job_pk, **kwargs)
        serializer.instance = ws

    @action(detail=True, methods=['post'], url_path='generate-estimate')
    def generate_estimate(self, request, pk=None):
        worksheet = self.get_object()
        try:
            service = EstimateGenerationService()
            estimate = service.generate_estimate_from_worksheet(worksheet)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'detail': 'Estimate generated.',
            'estimate_id': estimate.pk,
            'estimate_number': estimate.estimate_number,
        })
