from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from apps.jobs.models import WorkOrder
from apps.jobs.services import WorkOrderService
from apps.estimates.models import WorkOrderTemplate, Estimate
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

    @action(detail=False, methods=['post'], url_path='create-from-template')
    def create_from_template(self, request):
        job_pk = request.data.get('job')
        template_pk = request.data.get('template')
        if not job_pk:
            return Response(
                {'job': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not template_pk:
            return Response(
                {'template': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            template = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            return Response(
                {'template': ['Template not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            wo = WorkOrderService.create_from_template(template, job)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='create-from-estimate')
    def create_from_estimate(self, request):
        estimate_pk = request.data.get('estimate')
        if not estimate_pk:
            return Response(
                {'estimate': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            return Response(
                {'estimate': ['Estimate not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            wo = WorkOrderService.create_from_estimate(estimate)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
