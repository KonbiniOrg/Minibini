from django.urls import path
from .views import (
    JobDeliverablesView, JobDeliverableDetailView,
    JobDeliverablesReorderView, JobDeliverablesEditabilityView,
    JobShipmentsCreateView, ShipmentsListView, ShipmentDetailView,
    ShipmentPickUpView, ShipmentItemsView, ShipmentItemDetailView,
    ShipmentPackingListView,
)


urlpatterns = [
    # Deliverables
    path(
        'jobs/<int:job_id>/deliverables/',
        JobDeliverablesView.as_view(),
        name='job-deliverables-list',
    ),
    path(
        'jobs/<int:job_id>/deliverables/reorder/',
        JobDeliverablesReorderView.as_view(),
        name='job-deliverables-reorder',
    ),
    path(
        'jobs/<int:job_id>/deliverables/editability/',
        JobDeliverablesEditabilityView.as_view(),
        name='job-deliverables-editability',
    ),
    path(
        'jobs/<int:job_id>/deliverables/<int:deliverable_id>/',
        JobDeliverableDetailView.as_view(),
        name='job-deliverable-detail',
    ),

    # Shipments
    path(
        'jobs/<int:job_id>/shipments/',
        JobShipmentsCreateView.as_view(),
        name='job-shipments-create',
    ),
    path(
        'shipments/',
        ShipmentsListView.as_view(),
        name='shipments-list',
    ),
    path(
        'shipments/<int:shipment_id>/',
        ShipmentDetailView.as_view(),
        name='shipment-detail',
    ),
    path(
        'shipments/<int:shipment_id>/pick-up/',
        ShipmentPickUpView.as_view(),
        name='shipment-pick-up',
    ),
    path(
        'shipments/<int:shipment_id>/items/',
        ShipmentItemsView.as_view(),
        name='shipment-items',
    ),
    path(
        'shipments/<int:shipment_id>/items/<int:item_id>/',
        ShipmentItemDetailView.as_view(),
        name='shipment-item-detail',
    ),
    path(
        'shipments/<int:shipment_id>/packing-list/',
        ShipmentPackingListView.as_view(),
        name='shipment-packing-list',
    ),
]
