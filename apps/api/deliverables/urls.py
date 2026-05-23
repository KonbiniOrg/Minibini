from django.urls import path
from .views import DeliverableViewSet, ShipmentViewSet


deliverable_list = DeliverableViewSet.as_view({'get': 'list', 'post': 'create'})
deliverable_detail = DeliverableViewSet.as_view({
    'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy',
})
deliverable_reorder = DeliverableViewSet.as_view({'post': 'reorder'})
deliverable_editability = DeliverableViewSet.as_view({'get': 'editability'})

shipment_create = ShipmentViewSet.as_view({'post': 'create_for_job'})
shipment_list = ShipmentViewSet.as_view({'get': 'list'})
shipment_detail = ShipmentViewSet.as_view({
    'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy',
})
shipment_pick_up = ShipmentViewSet.as_view({'post': 'pick-up'})
shipment_items = ShipmentViewSet.as_view({'get': 'items', 'post': 'items'})
shipment_item_detail = ShipmentViewSet.as_view({
    'patch': 'item_detail', 'delete': 'item_detail',
})
shipment_packing_list = ShipmentViewSet.as_view({'get': 'packing_list'})


urlpatterns = [
    # Deliverables (job-nested)
    path(
        'jobs/<int:job_id>/deliverables/',
        deliverable_list,
        name='job-deliverables-list',
    ),
    path(
        'jobs/<int:job_id>/deliverables/reorder/',
        deliverable_reorder,
        name='job-deliverables-reorder',
    ),
    path(
        'jobs/<int:job_id>/deliverables/editability/',
        deliverable_editability,
        name='job-deliverables-editability',
    ),
    path(
        'jobs/<int:job_id>/deliverables/<int:deliverable_id>/',
        deliverable_detail,
        name='job-deliverable-detail',
    ),

    # Shipments (flat, job-nested create)
    path(
        'jobs/<int:job_id>/shipments/',
        shipment_create,
        name='job-shipments-create',
    ),
    path(
        'shipments/',
        shipment_list,
        name='shipments-list',
    ),
    path(
        'shipments/<int:pk>/',
        shipment_detail,
        name='shipment-detail',
    ),
    path(
        'shipments/<int:pk>/pick-up/',
        shipment_pick_up,
        name='shipment-pick-up',
    ),
    path(
        'shipments/<int:pk>/items/',
        shipment_items,
        name='shipment-items',
    ),
    path(
        'shipments/<int:pk>/items/<int:item_id>/',
        shipment_item_detail,
        name='shipment-item-detail',
    ),
    path(
        'shipments/<int:pk>/packing-list/',
        shipment_packing_list,
        name='shipment-packing-list',
    ),
]
