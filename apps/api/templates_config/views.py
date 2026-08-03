import json

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import WorkTemplate, ServiceItem
from apps.estimates.services import WorkTemplateService
from django.core.mail import get_connection
from imap_tools import MailBox

from apps.core.models import Configuration, AccountingCategory
from apps.core.services import ConfigurationService
from apps.core.units import HOUR_UNIT
from apps.jobs.models import RateScheme
from apps.api.permissions import CanManageConfig, CanManageJobsOrFinancialsOrConfig
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
        a = TemplateMaterialAssociationService.create(
            template, **serializer.validated_data)
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
        a = TemplateMaterialAssociationService.update(
            a, **serializer.validated_data)
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
        # Catalog management is shared: jobs | financials | config.
        return [IsAuthenticated(), CanManageJobsOrFinancialsOrConfig()]

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

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            ConfigurationService.delete_accounting_category(instance.pk)
        except DjangoValidationError as e:
            # PROTECT'd references — a friendly 409, not a ProtectedError 500.
            return Response({'detail': e.messages[0]},
                            status=status.HTTP_409_CONFLICT)
        return Response({'message': self.destroy_response_message})


def _validate_schedule_keys(data):
    """Validate schedule_* keys in the incoming settings payload.

    Returns an error dict (suitable for a 400 response) or None if valid.
    `schedule_week_envelope` may arrive as a dict or a JSON string; the
    per-day interval rules (HH:MM, ordered, non-overlapping) live in
    apps.schedule.calendar_arithmetic.validate_week_envelope.
    """
    errors = {}

    if 'schedule_week_envelope' in data:
        from apps.schedule.calendar_arithmetic import validate_week_envelope
        raw = data['schedule_week_envelope']
        parsed = raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
        if parsed is None:
            errors['schedule_week_envelope'] = 'must be valid envelope JSON'
        else:
            messages = validate_week_envelope(parsed)
            if messages:
                errors['schedule_week_envelope'] = ' '.join(messages)

    def parse_int(s, label, min_v=0):
        try:
            n = int(s)
            if n < min_v:
                return {'__error__': f"{label} must be >= {min_v}"}
            return n
        except (TypeError, ValueError):
            return {'__error__': f"{label} must be an integer"}

    if 'schedule_task_buffer_minutes' in data:
        buf = parse_int(data['schedule_task_buffer_minutes'],
                        'schedule_task_buffer_minutes', min_v=0)
        if isinstance(buf, dict):
            errors['schedule_task_buffer_minutes'] = buf['__error__']
    if 'schedule_horizon_days' in data:
        horiz = parse_int(data['schedule_horizon_days'],
                          'schedule_horizon_days', min_v=1)
        if isinstance(horiz, dict):
            errors['schedule_horizon_days'] = horiz['__error__']

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
    if 'default_material_accounting_category' in request.data:
        raw = request.data['default_material_accounting_category']
        raw = '' if raw is None else str(raw).strip()
        if raw != '':
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {'default_material_accounting_category': 'must be a category id'},
                    status=400)
            if not AccountingCategory.objects.filter(pk=pk, is_active=True).exists():
                return Response(
                    {'default_material_accounting_category': 'unknown or inactive category'},
                    status=400)
    if 'default_deposit_accounting_category' in request.data:
        raw = request.data['default_deposit_accounting_category']
        raw = '' if raw is None else str(raw).strip()
        if raw != '':
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {'default_deposit_accounting_category': 'must be a category id'},
                    status=400)
            if not AccountingCategory.objects.filter(
                    pk=pk, is_active=True, is_deposit=True).exists():
                return Response(
                    {'default_deposit_accounting_category':
                     'unknown, inactive, or not a deposit category'},
                    status=400)
    if 'default_rate_scheme' in request.data:
        raw = request.data['default_rate_scheme']
        raw = '' if raw is None else str(raw).strip()
        if raw != '':
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {'default_rate_scheme': 'must be a rate scheme id'},
                    status=400)
            if not RateScheme.objects.filter(
                    pk=pk, is_active=True
            ).exclude(algorithm=RateScheme.PERCENTAGE).exists():
                return Response(
                    {'default_rate_scheme':
                     'unknown, inactive, or a percentage rate scheme'},
                    status=400)
    for key, value in request.data.items():
        # The envelope is stored as canonical JSON; a dict payload must be
        # serialized (str(dict) would write unparseable Python repr).
        if key == 'schedule_week_envelope' and not isinstance(value, str):
            ConfigurationService.set(key, json.dumps(value))
        else:
            ConfigurationService.set(key, str(value))
    configs = Configuration.objects.all()
    data = {c.key: c.value for c in configs}
    return Response(data)


@api_view(['GET', 'PATCH'])
def units_view(request):
    if request.method == 'GET':
        if not request.user.is_authenticated:
            return Response(status=403)
        try:
            config = Configuration.objects.get(key='units_list')
        except Configuration.DoesNotExist:
            # Seeded by migration normally; fall back to the same built-in
            # list the rest of the app uses rather than 500.
            from apps.core.units import DEFAULT_UNITS
            return Response(DEFAULT_UNITS)
        return Response(json.loads(config.value))

    # PATCH — replace the units list
    if not request.user.has_perm('core.can_manage_config'):
        return Response(status=403)

    units = request.data
    if not isinstance(units, list) or len(units) == 0:
        return Response({'detail': 'Units must be a non-empty list.'}, status=400)
    if units[0] != 'none':
        return Response({'detail': '"none" must be the first entry.'}, status=400)
    if len(units) != len(set(units)):
        return Response({'detail': 'Duplicate units are not allowed.'}, status=400)
    if HOUR_UNIT not in units:
        return Response(
            {'detail': f'"{HOUR_UNIT}" must be included — time-based '
                       'billing and scheduling depend on it.'},
            status=400)

    ConfigurationService.set('units_list', json.dumps(units))
    return Response(units)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def email_verify_view(request):
    """Attempt an IMAP login and an SMTP connection with the resolved
    email account; report each independently. Never 500s — failures are
    data, not errors. can_manage_config only."""
    if not request.user.has_perm('core.can_manage_config'):
        return Response(status=403)
    from apps.core.email_account import email_account
    account = email_account()

    result = {'imap': {'ok': False, 'error': ''},
              'smtp': {'ok': False, 'error': ''}}
    try:
        with MailBox(account['imap_server']).login(
                account['address'], account['password']):
            pass
        result['imap']['ok'] = True
    except Exception as e:  # noqa: BLE001 — reported, not raised
        result['imap']['error'] = str(e)

    try:
        conn = get_connection(
            host=account['smtp_host'],
            port=int(account['smtp_port'] or 587),
            username=account['address'],
            password=account['password'],
            use_tls=True,
        )
        conn.open()
        conn.close()
        result['smtp']['ok'] = True
    except Exception as e:  # noqa: BLE001
        result['smtp']['error'] = str(e)

    return Response(result)
