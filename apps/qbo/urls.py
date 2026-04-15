from django.urls import path
from . import views

urlpatterns = [
    path('connect/', views.qbo_connect, name='qbo-connect'),
    path('callback/', views.qbo_callback, name='qbo-callback'),
    path('status/', views.qbo_status, name='qbo-status'),
    path('disconnect/', views.qbo_disconnect, name='qbo-disconnect'),
    path('accounts/', views.qbo_accounts, name='qbo-accounts'),
    path('payment-accounts/', views.qbo_payment_accounts, name='qbo-payment-accounts'),
]
