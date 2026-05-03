from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.api.permissions import CanManageConfig
from apps.jobs.models import RateScheme
from .serializers import RateSchemeSerializer


class RateSchemeViewSet(viewsets.ModelViewSet):
    queryset = RateScheme.objects.all().order_by('name')
    serializer_class = RateSchemeSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response({'message': f'Rate scheme "{instance.name}" deleted.'})

    def _block_if_referenced(self, instance, request):
        if instance.is_referenced():
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
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        blocked = self._block_if_referenced(instance, request)
        if blocked:
            return blocked
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        blocked = self._block_if_referenced(instance, request)
        if blocked:
            return blocked
        return super().partial_update(request, *args, **kwargs)
