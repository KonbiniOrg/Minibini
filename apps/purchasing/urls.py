from django.urls import path
from . import views

app_name = 'purchasing'

urlpatterns = [
    path('purchase-orders/', views.purchase_order_list, name='purchase_order_list'),
    path('purchase-orders/create/', views.purchase_order_create, name='purchase_order_create'),
    path('purchase-orders/create-for-job/<int:job_id>/', views.purchase_order_create_for_job, name='purchase_order_create_for_job'),
    path('purchase-orders/<int:po_id>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('purchase-orders/<int:po_id>/edit/', views.purchase_order_edit, name='purchase_order_edit'),
    path('purchase-orders/<int:po_id>/delete/', views.purchase_order_delete, name='purchase_order_delete'),
    path('purchase-orders/<int:po_id>/cancel/', views.purchase_order_cancel, name='purchase_order_cancel'),
    path('purchase-orders/<int:po_id>/add-line-item/', views.purchase_order_add_line_item, name='purchase_order_add_line_item'),
    path('purchase-orders/<int:po_id>/reorder-line-item/<int:line_item_id>/<str:direction>/', views.purchase_order_reorder_line_item, name='purchase_order_reorder_line_item'),
    path('purchase-orders/<int:po_id>/delete-line-item/<int:line_item_id>/', views.purchase_order_delete_line_item, name='purchase_order_delete_line_item'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/create/', views.bill_create, name='bill_create'),
    path('bills/create-for-po/<int:po_id>/', views.bill_create_for_po, name='bill_create_for_po'),
    path('bills/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('bills/<int:bill_id>/delete/', views.bill_delete, name='bill_delete'),
    path('bills/<int:bill_id>/add-line-item/', views.bill_add_line_item, name='bill_add_line_item'),
    path('bills/<int:bill_id>/reorder-line-item/<int:line_item_id>/<str:direction>/', views.bill_reorder_line_item, name='bill_reorder_line_item'),
    path('bills/<int:bill_id>/delete-line-item/<int:line_item_id>/', views.bill_delete_line_item, name='bill_delete_line_item'),
]