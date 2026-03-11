from rest_framework import viewsets
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService
from .serializers import PriceListItemSerializer


class PriceListItemViewSet(viewsets.ModelViewSet):
    queryset = PriceListItem.objects.all().order_by('code')
    serializer_class = PriceListItemSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        item = InventoryService.create_item(**serializer.validated_data)
        serializer.instance = item

    def perform_update(self, serializer):
        InventoryService.update_item(self.get_object().pk, **serializer.validated_data)
