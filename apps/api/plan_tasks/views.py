from rest_framework import status
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin, CreateModelMixin
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from apps.jobs.models import PlanTask, PlanCharge
from apps.inventory.models import PlanMaterial
from apps.inventory.services import InventoryService
from apps.core.services import ServiceError, NotFoundError
from apps.api.permissions import CanManageJobs
from .serializers import PlanTaskDetailSerializer, PlanMaterialSerializer, PlanMaterialWriteSerializer


class PlanChargeSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = PlanCharge
        fields = [
            'plan_charge_id', 'rate_scheme', 'active_modifiers',
            'estimated_billable_qty',
        ]
        read_only_fields = ['plan_charge_id']


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def plan_charge_view(request, ws_pk, pt_pk):
    try:
        plan_task = PlanTask.objects.get(pk=pt_pk, est_worksheet_id=ws_pk)
    except PlanTask.DoesNotExist:
        return Response({'detail': 'Plan task not found.'}, status=404)

    if request.method == 'GET':
        try:
            charge = plan_task.charge
        except PlanCharge.DoesNotExist:
            return Response(None)
        return Response(PlanChargeSerializer(charge).data)

    if not request.user.has_perm('core.can_manage_jobs'):
        return Response(status=403)

    if request.method == 'POST':
        try:
            plan_task.charge
            return Response(
                {'detail': 'Charge already exists. Use PATCH to update.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        except PlanCharge.DoesNotExist:
            pass
        serializer = PlanChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(plan_task=plan_task)
        return Response(serializer.data, status=http_status.HTTP_201_CREATED)

    # PATCH
    try:
        charge = plan_task.charge
    except PlanCharge.DoesNotExist:
        return Response({'detail': 'No charge to update.'}, status=404)
    serializer = PlanChargeSerializer(charge, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


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

    def get_permissions(self):
        if self.action in ('materials', 'material_detail'):
            if self.request.method == 'GET':
                return [IsAuthenticated()]
            return [IsAuthenticated(), CanManageJobs()]
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
        try:
            mat = InventoryService.create_plan_material(
                plan_task.pk, **serializer.validated_data
            )
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
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
        try:
            mat = InventoryService.update_plan_material(
                material.pk, **serializer.validated_data
            )
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PlanMaterialSerializer(mat).data)
