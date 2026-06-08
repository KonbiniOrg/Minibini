from django.urls import path

from apps.api.portal import views
from apps.api.portal import change_order_views as co_views

urlpatterns = [
    path('estimates/<str:token>/', views.portal_estimate,
         name='portal-estimate'),
    path('estimates/<str:token>/accept/', views.portal_estimate_accept,
         name='portal-estimate-accept'),
    path('estimates/<str:token>/reject/', views.portal_estimate_reject,
         name='portal-estimate-reject'),
    path('estimates/<str:token>/request-changes/',
         views.portal_estimate_request_changes,
         name='portal-estimate-request-changes'),

    path('change-orders/<str:token>/', co_views.portal_change_order,
         name='portal-change-order'),
    path('change-orders/<str:token>/accept/',
         co_views.portal_change_order_accept,
         name='portal-change-order-accept'),
    path('change-orders/<str:token>/reject/',
         co_views.portal_change_order_reject,
         name='portal-change-order-reject'),
    path('change-orders/<str:token>/request-changes/',
         co_views.portal_change_order_request_changes,
         name='portal-change-order-request-changes'),
]
