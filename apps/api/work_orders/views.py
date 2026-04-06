from decimal import Decimal, InvalidOperation
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from apps.jobs.models import WorkOrder, Task
from apps.jobs.services import WorkOrderService
from apps.estimates.models import WorkOrderTemplate, Estimate, EstWorksheet, TaskTemplate
from apps.api.mixins import StatusTransitionMixin, WorkOrderTaskMixin
from apps.api.permissions import CanManageJobs
from .serializers import WorkOrderSerializer, TaskSerializer


class WorkOrderViewSet(StatusTransitionMixin, WorkOrderTaskMixin, viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all().order_by('-pk')
    serializer_class = WorkOrderSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        # reorder and add_from_template are IsAuthenticated only
        authenticated_only_actions = ('reorder', 'add_from_template')
        if self.action in read_actions or self.action in authenticated_only_actions:
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

        # Soft warning: job already has planning artifacts
        confirm = request.query_params.get('confirm') == 'true'
        if not confirm:
            warnings = self._check_template_workflow_warnings(job)
            if warnings:
                return Response({'warnings': warnings})

        try:
            wo = WorkOrderService.create_from_template(template, job)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _check_template_workflow_warnings(job):
        warnings = []
        has_worksheet = EstWorksheet.objects.filter(job=job).exists()
        has_estimate = Estimate.objects.filter(job=job).exists()
        if has_worksheet and has_estimate:
            warnings.append(
                'This job already has a Worksheet and an Estimate. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        elif has_worksheet:
            warnings.append(
                'This job already has a Worksheet. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        elif has_estimate:
            warnings.append(
                'This job already has an Estimate. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        return warnings

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

        # Soft warning: job has a worksheet
        confirm = request.query_params.get('confirm') == 'true'
        if not confirm:
            warnings = self._check_estimate_workflow_warnings(estimate)
            if warnings:
                return Response({'warnings': warnings})

        try:
            wo = WorkOrderService.create_from_estimate(estimate)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _check_estimate_workflow_warnings(estimate):
        warnings = []
        has_worksheet = EstWorksheet.objects.filter(job=estimate.job).exists()
        if has_worksheet:
            warnings.append(
                'This job has a Worksheet. Usually the Worksheet is the '
                'source for the WorkOrder, not the Estimate. Proceed anyway?'
            )
        return warnings

    @action(detail=False, methods=['post'], url_path='copy-from-worksheet')
    def copy_from_worksheet(self, request):
        job_pk = request.data.get('job')
        worksheet_pk = request.data.get('worksheet')
        if not job_pk:
            return Response(
                {'job': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not worksheet_pk:
            return Response(
                {'worksheet': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            return Response(
                {'worksheet': ['Worksheet not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db import transaction
        with transaction.atomic():
            wo = WorkOrderService.create_direct(job, template=ws.template)
            WorkOrderService.copy_from_worksheet(wo.pk, ws.pk)

        wo.refresh_from_db()
        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='reorder')
    def reorder(self, request, pk=None):
        work_order = self.get_object()
        task_id = request.data.get('task_id')
        direction = request.data.get('direction')

        if not task_id:
            return Response(
                {'task_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if direction not in ('up', 'down'):
            return Response(
                {'direction': ['Must be "up" or "down".']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = Task.objects.get(pk=task_id, work_order=work_order)
        except Task.DoesNotExist:
            return Response(
                {'task_id': ['Task not found on this work order.']},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Find the neighbor in the given direction
        tasks = Task.objects.filter(work_order=work_order).order_by('sort_order')
        task_list = list(tasks)
        idx = next((i for i, t in enumerate(task_list) if t.pk == task.pk), None)

        if direction == 'up' and idx == 0:
            return Response({'detail': 'Already at top.'}, status=status.HTTP_400_BAD_REQUEST)
        if direction == 'down' and idx == len(task_list) - 1:
            return Response({'detail': 'Already at bottom.'}, status=status.HTTP_400_BAD_REQUEST)

        neighbor_idx = idx - 1 if direction == 'up' else idx + 1
        neighbor = task_list[neighbor_idx]

        # Swap sort_order values
        task.sort_order, neighbor.sort_order = neighbor.sort_order, task.sort_order
        task.save(update_fields=['sort_order'])
        neighbor.save(update_fields=['sort_order'])

        return Response({'status': 'ok'})

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        work_order = self.get_object()
        task_template_id = request.data.get('task_template_id')
        est_qty_raw = request.data.get('est_qty')

        if not task_template_id:
            return Response(
                {'task_template_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            template = TaskTemplate.objects.get(pk=task_template_id)
        except TaskTemplate.DoesNotExist:
            return Response(
                {'task_template_id': ['Task template not found.']},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            est_qty = Decimal(str(est_qty_raw)) if est_qty_raw is not None else Decimal('1')
        except (InvalidOperation, ValueError):
            return Response(
                {'est_qty': ['Invalid decimal value.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = template.generate_task(work_order, est_qty)
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
