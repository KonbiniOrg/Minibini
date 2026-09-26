from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.api.permissions import CanManageConfig
from apps.core.services import ConfigurationService
from apps.jobs.models import RateScheme
from .serializers import RateSchemeSerializer


class RateSchemeViewSet(viewsets.ModelViewSet):
    """CRUD routes through ConfigurationService. RateSchemes are freely
    editable presets (task-owned-money Phase 1): a stamped Task owns a
    permanent copy of its own money fields at creation time, so editing —
    or even deleting — a preset never reprices or orphans anything already
    stamped from it. ``retire``/``reactivate`` flip ``is_active``, the sole
    retirement signal read by the task-creation guard (SchemeInactiveError).
    A scheme still referenced by a ServiceItem can't be deleted (PROTECT at
    the DB level); that surfaces as a 409 via the central exception handler,
    not view-level shaping."""
    queryset = RateScheme.objects.all().order_by('name')
    serializer_class = RateSchemeSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        qs = RateScheme.objects.all().order_by('name')
        if self.action == 'list':
            include_inactive = self.request.query_params.get('include_inactive') == 'true'
            if not include_inactive:
                qs = qs.filter(is_active=True)
            if self.request.query_params.get('task_applicable') == 'true':
                # Task-creation pickers need non-percentage AND active,
                # regardless of include_inactive — an inactive preset is
                # never offered for a new stamping.
                qs = qs.exclude(algorithm=RateScheme.PERCENTAGE).filter(is_active=True)
            search = self.request.query_params.get('search', '').strip()
            if search:
                from django.db.models import Q
                qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def perform_create(self, serializer):
        serializer.instance = ConfigurationService.create_rate_scheme(
            **serializer.validated_data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data,
                                  partial=kwargs.get('partial', False))
        ser.is_valid(raise_exception=True)
        ConfigurationService.update_rate_scheme(instance, **ser.validated_data)
        return Response(self.get_serializer(instance).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # ConfigurationService.delete_rate_scheme() may raise ProtectedError
        # (ServiceItem.rate_scheme is PROTECT) — uncaught, it renders as a
        # 409 via the central exception handler.
        ConfigurationService.delete_rate_scheme(instance)
        return Response({'message': f'Rate scheme "{instance.name}" deleted.'})

    @action(detail=True, methods=['post'], url_path='retire',
            permission_classes=[IsAuthenticated, CanManageConfig])
    def retire(self, request, pk=None):
        instance = self.get_object()
        ConfigurationService.retire_rate_scheme(instance.pk)
        instance.refresh_from_db()
        return Response({'message': f'Rate scheme "{instance.name}" retired.'})

    @action(detail=True, methods=['post'], url_path='reactivate',
            permission_classes=[IsAuthenticated, CanManageConfig])
    def reactivate(self, request, pk=None):
        instance = self.get_object()
        ConfigurationService.reactivate_rate_scheme(instance.pk)
        instance.refresh_from_db()
        return Response({'message': f'Rate scheme "{instance.name}" reactivated.'})
