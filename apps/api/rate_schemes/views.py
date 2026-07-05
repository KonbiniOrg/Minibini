from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.api.permissions import CanManageConfig
from apps.core.services import ConfigurationService
from apps.jobs.models import RateScheme
from .serializers import RateSchemeSerializer


class RateSchemeViewSet(viewsets.ModelViewSet):
    """CRUD routes through ConfigurationService — the referenced-freeze
    decision lives there; this viewset only translates it into the SPA's
    409 payload (supersede_url + reference_counts)."""
    queryset = RateScheme.objects.all().order_by('name')
    serializer_class = RateSchemeSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        qs = RateScheme.objects.all().order_by('name')
        if self.action == 'list':
            include = self.request.query_params.get('include_superseded') == 'true'
            only = self.request.query_params.get('only_superseded') == 'true'
            if only:
                qs = qs.filter(replaced_by__isnull=False)
            elif not include:
                qs = qs.filter(replaced_by__isnull=True)
            if self.request.query_params.get('task_applicable') == 'true':
                qs = qs.exclude(algorithm=RateScheme.PERCENTAGE)
            search = self.request.query_params.get('search', '').strip()
            if search:
                from django.db.models import Q
                qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def _referenced_conflict(self, instance, request):
        return Response(
            {
                'detail': 'Scheme is referenced; create a new version instead of editing.',
                'supersede_url': request.build_absolute_uri(
                    f'/api/rate-schemes/{instance.pk}/supersede/'
                ),
                'reference_counts': instance.reference_counts(),
            },
            status=status.HTTP_409_CONFLICT,
        )

    def perform_create(self, serializer):
        serializer.instance = ConfigurationService.create_rate_scheme(
            **serializer.validated_data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data,
                                  partial=kwargs.get('partial', False))
        ser.is_valid(raise_exception=True)
        try:
            ConfigurationService.update_rate_scheme(
                instance, **ser.validated_data)
        except DjangoValidationError as e:
            if getattr(e, 'code', None) == 'referenced':
                return self._referenced_conflict(instance, request)
            raise  # plain validation errors render via the contract handler
        return Response(self.get_serializer(instance).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            ConfigurationService.delete_rate_scheme(instance)
        except DjangoValidationError as e:
            if getattr(e, 'code', None) == 'referenced':
                return self._referenced_conflict(instance, request)
            raise  # plain validation errors render via the contract handler
        return Response({'message': f'Service item "{instance.name}" deleted.'})

    @action(detail=True, methods=['post'], url_path='supersede',
            permission_classes=[IsAuthenticated, CanManageConfig])
    def supersede(self, request, pk=None):
        old = self.get_object()
        # Validate the new scheme's payload using the standard serializer.
        # Pass instance=old so DRF's UniqueValidator excludes the old row
        # from the name-uniqueness check — the model's supersede() renames
        # the old row before inserting the new one, so the DB won't collide,
        # but without instance= the serializer would reject same-name payloads
        # before reaching the model.
        serializer = RateSchemeSerializer(old, data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            new = ConfigurationService.supersede_rate_scheme(
                old, **serializer.validated_data)
        except DjangoValidationError as e:
            if getattr(e, 'code', None) == 'superseded':
                return Response({'detail': e.messages[0]},
                                status=status.HTTP_409_CONFLICT)
            raise  # plain validation errors render via the contract handler
        return Response(
            RateSchemeSerializer(new).data,
            status=status.HTTP_201_CREATED,
        )
