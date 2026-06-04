from django.urls import path

from apps.api.portal import views

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
]
