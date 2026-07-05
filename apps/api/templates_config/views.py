import json

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import WorkTemplate, ServiceItem
from apps.estimates.services import WorkTemplateService
from apps.core.models import Configuration, AccountingCategory
from apps.core.services import ConfigurationService
from apps.api.permissions import CanManageConfig, CanManageJobsOrConfig
from apps.api.mixins import JSONDestroyMixin
from apps.inventory.models import TemplateMaterialAssociation
from .serializers import (
    WorkTemplateSerializer, ServiceItemSerializer,
    ConfigurationSerializer, AccountingCategorySerializer,
    TemplateMaterialAssociationSerializer,
)


class WorkTemplateViewSet(JSONDestroyMixin, viewsets.ModelViewSet):
    queryset = WorkTemplate.objects.all().order_by('template_name')
    serializer_class = WorkTemplateSerializer
    lookup_field = 'pk'
    destroy_response_message = 'Work template deleted.'

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
            assocs = TemplateMaterialAssociation.objects.filter(work_template=template)
            return Response(TemplateMaterialAssociationSerializer(assocs, many=True).data)

        serializer = TemplateMaterialAssociationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.inventory.services import TemplateMaterialAssociationService
        try:
            a = TemplateMaterialAssociationService.create(
                template, **serializer.validated_data)
        except DjangoValidationError as e:
            return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            TemplateMaterialAssociationSerializer(a).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get', 'patch', 'delete'],
            url_path='materials/(?P<assoc_id>[0-9]+)', url_name='material-detail')
    def material_detail(self, request, pk=None, assoc_id=None):
        template = self.get_object()
        try:
            a = TemplateMaterialAssociation.objects.get(pk=assoc_id, work_template=template)
        except TemplateMaterialAssociation.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

        if request.method == 'GET':
            return Response(TemplateMaterialAssociationSerializer(a).data)

        from apps.inventory.services import TemplateMaterialAssociationService
        if request.method == 'DELETE':
            TemplateMaterialAssociationService.delete(a)
            return Response({'message': 'Template material association deleted.'})

        serializer = TemplateMaterialAssociationSerializer(a, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            a = TemplateMaterialAssociationService.update(
                a, **serializer.validated_data)
        except DjangoValidationError as e:
            return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(TemplateMaterialAssociationSerializer(a).data)


class ServiceItemViewSet(JSONDestroyMixin, viewsets.ModelViewSet):
    queryset = ServiceItem.objects.all().order_by('template_name')
    serializer_class = ServiceItemSerializer
    lookup_field = 'pk'
    destroy_response_message = 'Service item deleted.'

    def get_queryset(self):
        qs = ServiceItem.objects.all().order_by('template_name')
        if self.action == 'list':
            search = self.request.query_params.get('search', '').strip()
            if search:
                from django.db.models import Q
                qs = qs.filter(
                    Q(template_name__icontains=search) | Q(description__icontains=search)
                )
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action == 'create':
            # Inline "save to catalog" while plan-building — not config-gated.
            return [IsAuthenticated(), CanManageJobsOrConfig()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        template = WorkTemplateService.create_service_item(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkTemplateService.update_service_item(
            self.get_object().pk, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        WorkTemplateService.delete_service_item(instance.pk)


class AccountingCategoryViewSet(JSONDestroyMixin, viewsets.ModelViewSet):
    queryset = AccountingCategory.objects.all()
    serializer_class = AccountingCategorySerializer
    lookup_field = 'pk'
    destroy_response_message = 'Accounting category deleted.'

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


def _validate_schedule_keys(data):
    """Validate schedule_* keys in the incoming settings payload.

    Returns an error dict (suitable for a 400 response) or None if valid.
    Reads any keys present in `data` plus falls back to the current stored
    values to evaluate cross-key constraints (workday end after start).
    """
    schedule_keys = (
        'schedule_workday_start', 'schedule_workday_end',
        'schedule_task_buffer_minutes', 'schedule_horizon_days',
    )
    incoming = {k: v for k, v in data.items() if k in schedule_keys}
    if not incoming:
        return None

    # Pull current values for any keys not being set in this request.
    current = {}
    for key in schedule_keys:
        if key in incoming:
            current[key] = incoming[key]
        else:
            try:
                current[key] = Configuration.objects.get(key=key).value
            except Configuration.DoesNotExist:
                current[key] = None

    def parse_hhmm(s, label):
        if s is None:
            return None
        try:
            hh, mm = str(s).split(':')
            hh, mm = int(hh), int(mm)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
            return hh * 60 + mm
        except (ValueError, AttributeError):
            return {'__error__': f"{label} must be HH:MM"}

    def parse_int(s, label, min_v=0):
        if s is None:
            return None
        try:
            n = int(s)
            if n < min_v:
                return {'__error__': f"{label} must be >= {min_v}"}
            return n
        except (TypeError, ValueError):
            return {'__error__': f"{label} must be an integer"}

    errors = {}

    wstart = parse_hhmm(current['schedule_workday_start'], 'schedule_workday_start')
    if isinstance(wstart, dict): errors['schedule_workday_start'] = wstart['__error__']
    wend = parse_hhmm(current['schedule_workday_end'], 'schedule_workday_end')
    if isinstance(wend, dict): errors['schedule_workday_end'] = wend['__error__']
    buf = parse_int(current['schedule_task_buffer_minutes'],
                    'schedule_task_buffer_minutes', min_v=0)
    if isinstance(buf, dict): errors['schedule_task_buffer_minutes'] = buf['__error__']
    horiz = parse_int(current['schedule_horizon_days'],
                      'schedule_horizon_days', min_v=1)
    if isinstance(horiz, dict): errors['schedule_horizon_days'] = horiz['__error__']

    if errors:
        return errors

    # Cross-key checks (only when all relevant values parse).
    if wstart is not None and wend is not None and wstart >= wend:
        errors['schedule_workday_end'] = 'must be after schedule_workday_start'

    return errors or None


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, CanManageConfig])
def settings_view(request):
    if request.method == 'GET':
        configs = Configuration.objects.all()
        data = {c.key: c.value for c in configs}
        return Response(data)

    # PATCH — update settings
    schedule_errors = _validate_schedule_keys(request.data)
    if schedule_errors:
        return Response(schedule_errors, status=400)
    if 'blep_minimum_minutes' in request.data:
        try:
            if int(request.data['blep_minimum_minutes']) < 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {'blep_minimum_minutes': 'must be a non-negative integer'},
                status=400,
            )
    if 'activity_recent_days' in request.data:
        try:
            if int(request.data['activity_recent_days']) < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {'activity_recent_days': 'must be an integer >= 1'},
                status=400,
            )
    if 'average_labor_cost' in request.data:
        from decimal import Decimal, InvalidOperation
        raw = request.data['average_labor_cost']
        raw = '' if raw is None else str(raw).strip()
        # Blank is allowed — it clears the rate (labor then values at $0).
        if raw != '':
            try:
                if Decimal(raw) < 0:
                    raise ValueError
            except (InvalidOperation, ValueError, TypeError):
                return Response(
                    {'average_labor_cost': 'must be a non-negative number'},
                    status=400,
                )
    for key, value in request.data.items():
        ConfigurationService.set(key, str(value))
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

    ConfigurationService.set('units_list', json.dumps(units))
    return Response(units)
