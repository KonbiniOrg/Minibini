from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import InventoryService, MaterialService
from apps.api.permissions import CanManageFinancials, CanManageFinancialsOrConfig
from apps.api.mixins import JSONDestroyMixin
from .serializers import InventoryItemSerializer, MaterialSerializer, MaterialOpSerializer, MaterialAssignTaskSerializer


class InventoryItemViewSet(JSONDestroyMixin, viewsets.ModelViewSet):
    queryset = InventoryItem.objects.all().order_by('code')
    serializer_class = InventoryItemSerializer
    lookup_field = 'pk'
    destroy_response_message = 'Inventory item deleted.'

    def get_queryset(self):
        qs = super().get_queryset()
        # Only the LIST (and pickers, which list) is scoped by is_active /
        # hide-on-spend. Detail, update, delete, and detail-actions must reach
        # ANY item by pk — get_object() runs through get_queryset(), so scoping
        # it here would 404 a finished/hidden lot or a deactivated item and make
        # it impossible to retrieve or edit (e.g. to re-promote it to catalog).
        if self.action != 'list':
            return qs
        # Optional filter: ?is_active=true|false (omit to include all).
        # Pickers (Material modal, etc.) pass is_active=true so deactivated
        # PLIs don't appear as selection options. Catalog management omits
        # the param so admins can still see and re-activate deactivated rows.
        is_active_param = self.request.query_params.get('is_active')
        if is_active_param is not None:
            value = is_active_param.lower() in ('true', '1', 'yes')
            qs = qs.filter(is_active=value)
        # Hide-on-spend: a finished transient lot (not catalog, QOH 0, no
        # earmarks) is filtered from the active list and allocation pickers.
        # Catalog management opts back in with ?include_finished=true to reach
        # finished lots for merge/write-off.
        include_finished = self.request.query_params.get(
            'include_finished', '').lower() in ('true', '1', 'yes')
        if not include_finished:
            from decimal import Decimal
            from django.db.models import Count
            qs = qs.annotate(_em_count=Count('earmark')).exclude(
                is_catalog=False, qty_on_hand=Decimal('0.00'), _em_count=0,
            )
        is_catalog_param = self.request.query_params.get('is_catalog')
        if is_catalog_param is not None:
            is_catalog_value = is_catalog_param.lower() in ('true', '1', 'yes')
            qs = qs.filter(is_catalog=is_catalog_value)
        search = self.request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(code__icontains=search) | Q(description__icontains=search))
        return qs

    def get_permissions(self):
        # B7: inventory items are owned by both the money role (financials) and
        # the admin role (config) — either atom grants full CRUD + write-off/merge.
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancialsOrConfig()]

    def destroy(self, request, *args, **kwargs):
        """Hard delete is mistake correction: never-referenced rows only.

        Referenced items retire by deactivation (is_active) or live on as
        hidden finished lots — inventory rows are shop history.
        """
        item = self.get_object()
        InventoryService.assert_item_deletable(item)
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        item = InventoryService.create_item(**serializer.validated_data)
        serializer.instance = item

    def perform_update(self, serializer):
        InventoryService.update_item(self.get_object().pk, **serializer.validated_data)

    @action(detail=True, methods=['post'], url_path='write-off')
    def write_off(self, request, pk=None):
        """Write off the item's remaining on-hand stock as wasted."""
        item = self.get_object()
        InventoryService.write_off(
            item, qty=request.data.get('qty'),
            reason=request.data.get('reason', '') or 'Write-off',
        )
        # The row always survives a write-off now (finished lots are kept as
        # hidden history, never auto-collected).
        item.refresh_from_db()
        return Response(self.get_serializer(item).data)

    @action(detail=False, methods=['post'], url_path='merge')
    def merge(self, request):
        """Consolidate two items: move the discard's stock + references onto the
        keep, then delete the discard. Body: keep_id, discard_id, optional
        overrides (final field values for keep)."""
        keep_id = request.data.get('keep_id')
        discard_id = request.data.get('discard_id')
        if not keep_id or not discard_id:
            return Response({'detail': 'keep_id and discard_id are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            keep = InventoryService.merge(
                keep_id, discard_id,
                overrides=request.data.get('overrides') or {},
            )
        except InventoryItem.DoesNotExist:
            return Response({'detail': 'Item not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(keep).data)


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.select_related('inventory_item').all()
    serializer_class = MaterialSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        # Creation goes through /api/jobs/{id}/materials/; deny top-level create.
        return Response({'detail': 'Create via /api/jobs/{id}/materials/'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete via Restock (manual-add) or expense rejection.'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        propagate = fields.pop('propagate_to_pli', False)
        instance = MaterialService.update_fields(
            instance, propagate_to_pli=propagate, **fields)
        return Response(MaterialSerializer(instance).data)

    @action(detail=True, methods=['post'])
    def consume(self, request, pk=None):
        m = self.get_object()
        MaterialService.consume(m)
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.restock(m, s.validated_data['quantity'])
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
        MaterialService.draw_more(m, s.validated_data['quantity'])
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)

    @action(detail=True, methods=['post'], url_path='assign-task')
    def assign_task(self, request, pk=None):
        s = MaterialAssignTaskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.assign_task(m, s.validated_data['task'])
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)
