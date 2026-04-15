import json

from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import WorkTemplate, TaskTemplate
from apps.estimates.services import WorkTemplateService
from apps.core.models import Configuration, AccountingCategory
from apps.core.services import ConfigurationService
from apps.api.permissions import CanManageConfig
from apps.inventory.models import TemplateMaterial
from .serializers import (
    WorkTemplateSerializer, TaskTemplateSerializer,
    ConfigurationSerializer, AccountingCategorySerializer,
    TemplateMaterialSerializer,
)


class WorkTemplateViewSet(viewsets.ModelViewSet):
    queryset = WorkTemplate.objects.all().order_by('template_name')
    serializer_class = WorkTemplateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('materials', 'material_detail')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        template = WorkTemplateService.create_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkTemplateService.update_template(self.get_object().pk, **serializer.validated_data)

    def perform_destroy(self, instance):
        WorkTemplateService.delete_template(instance.pk)

    @action(detail=True, methods=['get', 'post'], url_path='materials', url_name='materials')
    def materials(self, request, pk=None):
        template = self.get_object()
        if request.method == 'GET':
            mats = TemplateMaterial.objects.filter(work_template=template)
            serializer = TemplateMaterialSerializer(mats, many=True)
            return Response(serializer.data)

        serializer = TemplateMaterialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mat = TemplateMaterial(work_template=template, **serializer.validated_data)
        mat.save()
        out = TemplateMaterialSerializer(mat)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'patch', 'delete'],
            url_path='materials/(?P<mat_id>[0-9]+)', url_name='material-detail')
    def material_detail(self, request, pk=None, mat_id=None):
        template = self.get_object()
        try:
            mat = TemplateMaterial.objects.get(pk=mat_id, work_template=template)
        except TemplateMaterial.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

        if request.method == 'GET':
            return Response(TemplateMaterialSerializer(mat).data)

        if request.method == 'DELETE':
            mat.delete()
            return Response({'message': 'Template material deleted.'})

        serializer = TemplateMaterialSerializer(mat, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TaskTemplateViewSet(viewsets.ModelViewSet):
    queryset = TaskTemplate.objects.all().order_by('template_name')
    serializer_class = TaskTemplateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        template = WorkTemplateService.create_task_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkTemplateService.update_task_template(
            self.get_object().pk, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        WorkTemplateService.delete_task_template(instance.pk)


class AccountingCategoryViewSet(viewsets.ModelViewSet):
    queryset = AccountingCategory.objects.all()
    serializer_class = AccountingCategorySerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        cat = ConfigurationService.create_accounting_category(**serializer.validated_data)
        serializer.instance = cat

    def perform_update(self, serializer):
        ConfigurationService.update_accounting_category(
            self.get_object().pk, **serializer.validated_data
        )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, CanManageConfig])
def settings_view(request):
    if request.method == 'GET':
        configs = Configuration.objects.all()
        data = {c.key: c.value for c in configs}
        return Response(data)

    # PATCH — update settings
    for key, value in request.data.items():
        Configuration.objects.update_or_create(
            key=key, defaults={'value': str(value)}
        )
    configs = Configuration.objects.all()
    data = {c.key: c.value for c in configs}
    return Response(data)


@api_view(['GET', 'PATCH'])
def units_view(request):
    if request.method == 'GET':
        if not request.user.is_authenticated:
            return Response(status=403)
        config = Configuration.objects.get(key='units_list')
        return Response(json.loads(config.value))

    # PATCH — replace the units list
    if not request.user.has_perm('core.can_manage_config'):
        return Response(status=403)

    units = request.data
    if not isinstance(units, list) or len(units) == 0:
        return Response({'error': 'Units must be a non-empty list.'}, status=400)
    if units[0] != 'none':
        return Response({'error': '"none" must be the first entry.'}, status=400)
    if len(units) != len(set(units)):
        return Response({'error': 'Duplicate units are not allowed.'}, status=400)

    Configuration.objects.update_or_create(
        key='units_list',
        defaults={'value': json.dumps(units)},
    )
    return Response(units)
