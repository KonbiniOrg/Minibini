from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_list, name='inventory_list'),
    path('add/', views.inventory_item_add, name='inventory_item_add'),
    path('<int:item_id>/edit/', views.inventory_item_edit, name='inventory_item_edit'),

    # Price List Item URLs
    path('price-list-items/', views.inventory_item_list, name='inventory_item_list'),
    path('price-list-items/add/', views.inventory_item_add, name='inventory_item_add'),
    path('price-list-items/<int:item_id>/edit/', views.inventory_item_edit, name='inventory_item_edit'),
]
