from rest_framework import viewsets
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
