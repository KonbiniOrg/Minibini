from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import WorkOrderTemplate, TaskTemplate
from apps.estimates.services import WorkOrderTemplateService
from apps.core.models import Configuration, LineItemType
from apps.core.services import ConfigurationService
from apps.api.permissions import CanManageConfig
from .serializers import (
    WorkOrderTemplateSerializer, TaskTemplateSerializer,
    ConfigurationSerializer, LineItemTypeSerializer,
)


class WorkOrderTemplateViewSet(viewsets.ModelViewSet):
    queryset = WorkOrderTemplate.objects.all().order_by('template_name')
    serializer_class = WorkOrderTemplateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        template = WorkOrderTemplateService.create_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkOrderTemplateService.update_template(self.get_object().pk, **serializer.validated_data)

    def perform_destroy(self, instance):
        WorkOrderTemplateService.delete_template(instance.pk)


class TaskTemplateViewSet(viewsets.ModelViewSet):
    queryset = TaskTemplate.objects.all().order_by('template_name')
    serializer_class = TaskTemplateSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        template = WorkOrderTemplateService.create_task_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkOrderTemplateService.update_task_template(
            self.get_object().pk, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        WorkOrderTemplateService.delete_task_template(instance.pk)


class LineItemTypeViewSet(viewsets.ModelViewSet):
    queryset = LineItemType.objects.all()
    serializer_class = LineItemTypeSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        lit = ConfigurationService.create_line_item_type(**serializer.validated_data)
        serializer.instance = lit

    def perform_update(self, serializer):
        ConfigurationService.update_line_item_type(
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
