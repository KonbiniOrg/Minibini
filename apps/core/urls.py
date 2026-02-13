from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('line-item-types/', views.line_item_type_list, name='line_item_type_list'),
    path('line-item-types/create/', views.line_item_type_create, name='line_item_type_create'),
    path('line-item-types/<int:pk>/', views.line_item_type_detail, name='line_item_type_detail'),
    path('line-item-types/<int:pk>/edit/', views.line_item_type_edit, name='line_item_type_edit'),
]