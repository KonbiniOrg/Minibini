from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.inventory.models import PriceListItem, Material
from apps.inventory.services import InventoryService, MaterialService
from apps.api.permissions import CanManageFinancials
from .serializers import PriceListItemSerializer, MaterialSerializer, MaterialOpSerializer


class PriceListItemViewSet(viewsets.ModelViewSet):
    queryset = PriceListItem.objects.all().order_by('code')
    serializer_class = PriceListItemSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    def perform_create(self, serializer):
        item = InventoryService.create_item(**serializer.validated_data)
        serializer.instance = item

    def perform_update(self, serializer):
        InventoryService.update_item(self.get_object().pk, **serializer.validated_data)


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.all()
    serializer_class = MaterialSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        # Creation goes through /api/jobs/{id}/materials/; deny top-level create.
        return Response({'error': 'Create via /api/jobs/{id}/materials/'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Delete via Restock (manual-add) or expense rejection.'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=['post'])
    def consume(self, request, pk=None):
        m = self.get_object()
        try:
            MaterialService.consume(m)
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        try:
            MaterialService.restock(m, s.validated_data['quantity'])
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            m.refresh_from_db()
            return Response(MaterialSerializer(m).data)
        except Material.DoesNotExist:
            return Response({'deleted': True})

    @action(detail=True, methods=['post'], url_path='draw-more')
    def draw_more(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        try:
            MaterialService.draw_more(m, s.validated_data['quantity'])
        except DjangoValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)
