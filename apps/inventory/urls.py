from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_list, name='inventory_list'),
    path('add/', views.inventory_item_add, name='inventory_item_add'),
    path('<int:item_id>/edit/', views.inventory_item_edit, name='inventory_item_edit'),
]
