from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import EstWorksheet
from apps.estimates.services import WorksheetService
from django.core.exceptions import ValidationError
from apps.core.services import ServiceError, NotFoundError, SchemeSupersededError
from apps.api.mixins import StatusTransitionMixin, PlanTaskMixin, JobScopedPermissionMixin
from apps.api.permissions import CanManageJobOrPM
from .serializers import (
    EstWorksheetSerializer, PlanTaskSerializer,
    PlanMaterialWriteSerializer, PlanMaterialAssignTaskSerializer,
)


class EstWorksheetViewSet(JobScopedPermissionMixin, StatusTransitionMixin, PlanTaskMixin, viewsets.ModelViewSet):
    queryset = EstWorksheet.objects.all().order_by('-created_date')
    serializer_class = EstWorksheetSerializer
    lookup_field = 'pk'
    job_object_path = 'job'
    job_create_field = 'job'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('tasks', 'plan_materials', 'plan_material_detail')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobOrPM()]

    # PlanTaskMixin config
    plan_task_serializer_class = PlanTaskSerializer

    # One mutable worksheet per job — no revise/version actions.
    status_actions = {}

    def get_queryset(self):
        from django.db.models import Prefetch
        from apps.jobs.models import PlanTask
        qs = super().get_queryset().prefetch_related(
            Prefetch(
                'plan_tasks',
                queryset=PlanTask.objects.select_related('service_item').order_by('sort_order'),
            )
        )
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except SchemeSupersededError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)

    def destroy(self, request, *args, **kwargs):
        worksheet = self.get_object()
        try:
            WorksheetService.delete_worksheet(worksheet)
        except ValidationError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'message': 'Worksheet deleted.'})

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        template = data.pop('template', None)
        ws = WorksheetService.create_worksheet(job_pk)
        if template:
            task_pairing = template.generate_tasks_for_worksheet(ws)
            template.generate_materials_for_worksheet(ws, task_pairing=task_pairing)
        serializer.instance = ws

    @action(detail=True, methods=['post'], url_path='reorder')
    def reorder(self, request, pk=None):
        worksheet = self.get_object()
        item_type = request.data.get('item_type')
        item_id = request.data.get('item_id')
        direction = request.data.get('direction')
        errors = {}
        if item_type not in ('task',):
            errors['item_type'] = ['Must be "task".']
        if not item_id:
            errors['item_id'] = ['This field is required.']
        if direction not in ('up', 'down'):
            errors['direction'] = ['Must be "up" or "down".']
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            WorksheetService.reorder_items(worksheet.pk, item_type, item_id, direction)
        except (ServiceError, ValidationError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'Reordered.'})

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        worksheet = self.get_object()
        task_template_id = request.data.get('task_template_id')
        est_qty = request.data.get('est_qty')
        service_item = request.data.get('service_item')
        active_modifiers = request.data.get('active_modifiers')
        est_worker_time = request.data.get('est_worker_time')
        name = request.data.get('name') or None
        description = request.data.get('description')  # None means "not provided"
        if not task_template_id:
            return Response(
                {'task_template_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from decimal import Decimal
            task = WorksheetService.add_task_from_template(
                worksheet.pk,
                task_template_id,
                service_item_id=int(service_item) if service_item else None,
                active_modifiers=active_modifiers,
                est_qty=(
                    Decimal(str(est_qty))
                    if est_qty is not None and est_qty != ''
                    else None
                ),
                est_worker_time=est_worker_time if est_worker_time else None,
                name=name,
                description=description,
            )
        except SchemeSupersededError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except (ServiceError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = PlanTaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='plan-materials', url_name='plan-materials')
    def plan_materials(self, request, pk=None):
        worksheet = self.get_object()
        if request.method == 'GET':
            from apps.inventory.models import PlanMaterial
            mats = PlanMaterial.objects.filter(est_worksheet=worksheet)
            serializer = PlanMaterialWriteSerializer(mats, many=True)
            return Response(serializer.data)

        serializer = PlanMaterialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan_task = serializer.validated_data.get('plan_task')
        EXCLUDE_FROM_CREATE = {'plan_task', 'propagate_to_pli'}
        kwargs = {k: v for k, v in serializer.validated_data.items()
                  if k not in EXCLUDE_FROM_CREATE}
        try:
            if plan_task is not None:
                kwargs['plan_task'] = plan_task
                from apps.inventory.models import PlanMaterial
                mat = PlanMaterial(est_worksheet=worksheet, **kwargs)
                mat.save()
            else:
                from apps.inventory.services import InventoryService
                mat = InventoryService.create_plan_material_on_worksheet(worksheet, **kwargs)
        except ValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
        out = PlanMaterialWriteSerializer(mat)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='plan-materials/(?P<mat_id>[0-9]+)', url_name='plan-material-detail')
    def plan_material_detail(self, request, pk=None, mat_id=None):
        worksheet = self.get_object()
        from apps.inventory.models import PlanMaterial
        try:
            mat = PlanMaterial.objects.get(pk=mat_id, est_worksheet=worksheet)
        except PlanMaterial.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

        if request.method == 'DELETE':
            mat.delete()
            return Response({'message': 'Plan material deleted.'})

        serializer = PlanMaterialWriteSerializer(mat, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        propagate = serializer.validated_data.get('propagate_to_pli', False)
        if mat.inventory_item_id is not None and (
            'unit_cost' in serializer.validated_data
            or 'sell_price' in serializer.validated_data
        ):
            from apps.inventory.services import InventoryService
            InventoryService.update_plan_material_pricing(
                mat,
                unit_cost=serializer.validated_data.get('unit_cost'),
                sell_price=serializer.validated_data.get('sell_price'),
                propagate_to_pli=propagate,
            )
            mat.refresh_from_db()
            return Response(PlanMaterialWriteSerializer(mat).data)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='plan-materials/(?P<mat_id>[0-9]+)/assign-task',
            url_name='plan-material-assign-task')
    def plan_material_assign_task(self, request, pk=None, mat_id=None):
        from apps.inventory.models import PlanMaterial
        from apps.inventory.services import InventoryService
        from django.core.exceptions import ValidationError as DjangoValidationError
        from rest_framework.exceptions import NotFound
        worksheet = self.get_object()
        try:
            mat = PlanMaterial.objects.get(pk=mat_id, est_worksheet=worksheet)
        except PlanMaterial.DoesNotExist:
            raise NotFound()
        s = PlanMaterialAssignTaskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            InventoryService.assign_plan_task(mat, s.validated_data['plan_task'])
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        mat.refresh_from_db()
        return Response(PlanMaterialWriteSerializer(mat).data)

    @action(detail=True, methods=['post'], url_path='send-all-atoms-to-estimate')
    def send_all_atoms_to_estimate(self, request, pk=None):
        """Bulk 1:1 conversion of unclaimed atoms to EstimateLineItems."""
        from apps.estimates.services import EstimateWizardService

        worksheet = self.get_object()
        try:
            result = EstimateWizardService.send_all_atoms_to_estimate(worksheet)
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        return Response({
            'estimate_id': result['estimate'].pk,
            'estimate_number': result['estimate'].estimate_number,
            'created_count': result['created_count'],
        })

    @action(detail=True, methods=['post'], url_path='open-estimate')
    def open_estimate(self, request, pk=None):
        """Return (creating if needed) the worksheet's draft estimate.

        Does NOT auto-claim atoms — used by the "Open wizard to group atoms"
        button to land in the wizard with a fresh estimate the user can
        populate manually.
        """
        from apps.estimates.services import EstimateWizardService

        worksheet = self.get_object()
        try:
            estimate = EstimateWizardService.open_for_worksheet(worksheet)
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        return Response({
            'estimate_id': estimate.pk,
            'estimate_number': estimate.estimate_number,
        })

