from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import InventoryService, MaterialService
from apps.api.permissions import CanManageFinancials, CanManageFinancialsOrConfig
from apps.api.mixins import JSONDestroyMixin
from .serializers import (
    InventoryItemSerializer, MaterialSerializer, MaterialOpSerializer,
    MaterialAssignTaskSerializer, StockOrderSerializer,
)


class InventoryItemViewSet(JSONDestroyMixin, viewsets.ModelViewSet):
    queryset = InventoryItem.objects.all().order_by('code')
    serializer_class = InventoryItemSerializer
    lookup_field = 'pk'
    destroy_response_message = 'Inventory item deleted.'

    def get_queryset(self):
        qs = super().get_queryset()
        # Only the LIST (and pickers, which list) is scoped by is_active.
        # Detail, update, delete, and detail-actions must reach ANY item by
        # pk — get_object() runs through get_queryset(), so scoping it here
        # would 404 a deactivated item and make it impossible to retrieve or
        # edit (e.g. to re-activate it).
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
        search = self.request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(code__icontains=search) | Q(description__icontains=search))
        # Order: alphabetical by code (the base queryset's order_by). The main
        # /#/inventory list is browsed, not searched, so alphabetical wins;
        # typeahead pickers are already narrowed by ?search and need no rank.
        # (An in-stock-first ranking was tried 2026-07-05 and reverted.)
        return qs

    def get_permissions(self):
        # B7: inventory items are owned by both the money role (financials) and
        # the admin role (config) — either atom grants full CRUD + write-off/merge.
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancialsOrConfig()]

    def destroy(self, request, *args, **kwargs):
        """Hard delete is mistake correction: never-referenced rows only.

        Referenced items retire by deactivation (is_active) — inventory rows
        are shop history.
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
        # The row always survives a write-off now — inventory rows are kept as
        # history, never auto-collected.
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

    @action(detail=True, methods=['post'],
            permission_classes=[IsAuthenticated, CanManageFinancials])
    def order(self, request, pk=None):
        """Order this item to stock — plain PO line, no material link.
        Optional body po_id appends to that draft (same contract as the
        material order action)."""
        from django.shortcuts import get_object_or_404
        from apps.purchasing.models import PurchaseOrder
        s = StockOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        item = self.get_object()
        po = None
        if s.validated_data.get('po_id'):
            po = get_object_or_404(PurchaseOrder, pk=s.validated_data['po_id'])
        po, _li = InventoryService.order_stock(
            item, s.validated_data['quantity'], po=po)
        data = self.get_serializer(item).data
        data['po_id'], data['po_number'] = po.pk, po.po_number
        return Response(data)


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

    @action(detail=True, methods=['post'], url_path='mark-on-hand')
    def mark_on_hand(self, request, pk=None):
        """Deliberate no-document receipt (Path 3) / customer-delivery
        receipt (Path 4) — shop-floor arrival marking, no extra permission
        beyond the viewset default."""
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.mark_on_hand(
            m, s.validated_data['quantity'], user=request.user)
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

    @action(detail=True, methods=['post'],
            permission_classes=[IsAuthenticated, CanManageFinancials])
    def order(self, request, pk=None):
        """Start (or append to) a draft PO with a line linked to this material
        (spec Path 1). Optional body {"po_id": <int>} appends to that draft."""
        from django.shortcuts import get_object_or_404
        from apps.purchasing.models import PurchaseOrder
        m = self.get_object()
        po = None
        po_id = request.data.get('po_id')
        if po_id:
            po = get_object_or_404(PurchaseOrder, pk=po_id)
        po, _li = MaterialService.order(m, po=po)
        m.refresh_from_db()
        data = MaterialSerializer(m).data
        data['po_id'], data['po_number'] = po.pk, po.po_number
        return Response(data)
