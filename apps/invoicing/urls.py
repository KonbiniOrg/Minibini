from django.urls import path
from . import views

app_name = 'invoicing'

urlpatterns = [
    path('', views.invoice_list, name='invoice_list'),
    path('<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('<int:invoice_id>/reorder-line-item/<int:line_item_id>/<str:direction>/', views.invoice_reorder_line_item, name='invoice_reorder_line_item'),

    # Price List Item URLs
    path('price-list-items/', views.price_list_item_list, name='price_list_item_list'),
    path('price-list-items/add/', views.price_list_item_add, name='price_list_item_add'),
    path('price-list-items/<int:item_id>/edit/', views.price_list_item_edit, name='price_list_item_edit'),
]