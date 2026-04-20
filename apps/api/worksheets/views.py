from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import EstWorksheet
from apps.estimates.services import WorksheetService, EstimateGenerationService
from django.core.exceptions import ValidationError
from apps.core.services import ServiceError, NotFoundError
from apps.api.mixins import StatusTransitionMixin, PlanTaskBundleMixin
from apps.api.permissions import CanManageJobs
from .serializers import EstWorksheetSerializer, PlanTaskSerializer, PlanBundleSerializer, PlanMaterialWriteSerializer


class EstWorksheetViewSet(StatusTransitionMixin, PlanTaskBundleMixin, viewsets.ModelViewSet):
    queryset = EstWorksheet.objects.all().order_by('-created_date')
    serializer_class = EstWorksheetSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('tasks', 'bundles', 'plan_materials', 'plan_material_detail')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    # PlanTaskBundleMixin config
    plan_task_serializer_class = PlanTaskSerializer
    plan_bundle_serializer_class = PlanBundleSerializer

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

    @action(detail=True, methods=['post'], url_path='reorder')
    def reorder(self, request, pk=None):
        worksheet = self.get_object()
        item_type = request.data.get('item_type')
        item_id = request.data.get('item_id')
        direction = request.data.get('direction')
        errors = {}
        if item_type not in ('task', 'bundle'):
            errors['item_type'] = ['Must be "task" or "bundle".']
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

    @action(detail=True, methods=['post'], url_path='reorder-in-bundle')
    def reorder_in_bundle(self, request, pk=None):
        worksheet = self.get_object()
        task_id = request.data.get('task_id')
        direction = request.data.get('direction')
        errors = {}
        if not task_id:
            errors['task_id'] = ['This field is required.']
        if direction not in ('up', 'down'):
            errors['direction'] = ['Must be "up" or "down".']
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            WorksheetService.reorder_in_bundle(worksheet.pk, task_id, direction)
        except (ServiceError, ValidationError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'Reordered.'})

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        worksheet = self.get_object()
        task_template_id = request.data.get('task_template_id')
        est_qty = request.data.get('est_qty', '1.00')
        if not task_template_id:
            return Response(
                {'task_template_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from decimal import Decimal
            task = WorksheetService.add_task_from_template(
                worksheet.pk, task_template_id, Decimal(str(est_qty))
            )
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
        kwargs = {k: v for k, v in serializer.validated_data.items() if k != 'plan_task'}
        if plan_task is not None:
            kwargs['plan_task'] = plan_task
            from apps.inventory.models import PlanMaterial
            mat = PlanMaterial(est_worksheet=worksheet, **kwargs)
            mat.save()
        else:
            from apps.inventory.services import InventoryService
            mat = InventoryService.create_plan_material_on_worksheet(worksheet, **kwargs)
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
        serializer.save()
        return Response(serializer.data)

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
