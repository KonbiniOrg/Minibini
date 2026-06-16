from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin, CreateModelMixin
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial
from apps.inventory.services import InventoryService
from apps.core.services import ServiceError, NotFoundError
from apps.api.permissions import CanManageJobOrPM
from apps.api.mixins import JobScopedPermissionMixin
from .serializers import PlanTaskDetailSerializer, PlanMaterialSerializer, PlanMaterialWriteSerializer


class PlanTaskViewSet(JobScopedPermissionMixin,
                      RetrieveModelMixin, ListModelMixin, CreateModelMixin,
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
    job_object_path = 'est_worksheet.job'

    def list(self, request, *args, **kwargs):
        raise MethodNotAllowed('GET')

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed('POST')

    def get_permissions(self):
        if self.action in ('materials', 'material_detail'):
            if self.request.method == 'GET':
                return [IsAuthenticated()]
            return [IsAuthenticated(), CanManageJobOrPM()]
        return [IsAuthenticated()]

    @action(detail=True, methods=['get', 'post'], url_path='materials', url_name='materials')
    def materials(self, request, pk=None):
        plan_task = self.get_object()
        if request.method == 'GET':
            materials = PlanMaterial.objects.filter(plan_task=plan_task)
            serializer = PlanMaterialSerializer(materials, many=True)
            return Response(serializer.data)

        serializer = PlanMaterialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        create_data = {k: v for k, v in serializer.validated_data.items()
                       if k != 'propagate_to_pli'}
        try:
            mat = InventoryService.create_plan_material(
                plan_task.pk, **create_data
            )
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            PlanMaterialSerializer(mat).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch', 'delete'],
            url_path='materials/(?P<mid>[0-9]+)', url_name='material-detail')
    def material_detail(self, request, pk=None, mid=None):
        plan_task = self.get_object()
        try:
            material = PlanMaterial.objects.get(pk=mid, plan_task=plan_task)
        except PlanMaterial.DoesNotExist:
            raise NotFound()

        if request.method == 'DELETE':
            try:
                InventoryService.delete_plan_material(material.pk)
            except NotFoundError as e:
                return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
            return Response({'message': 'Material deleted.'})

        serializer = PlanMaterialWriteSerializer(material, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        propagate = serializer.validated_data.get('propagate_to_pli', False)
        if material.inventory_item_id is not None and (
            'unit_cost' in serializer.validated_data
            or 'sell_price' in serializer.validated_data
        ):
            InventoryService.update_plan_material_pricing(
                material,
                unit_cost=serializer.validated_data.get('unit_cost'),
                sell_price=serializer.validated_data.get('sell_price'),
                propagate_to_pli=propagate,
            )
            material.refresh_from_db()
            return Response(PlanMaterialSerializer(material).data)
        mat = serializer.save()
        return Response(PlanMaterialSerializer(mat).data)
