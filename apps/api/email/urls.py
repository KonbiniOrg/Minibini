from django.urls import path
from . import views

urlpatterns = [
    path('', views.email_list, name='email-list'),
    path('refresh/', views.refresh, name='email-refresh'),
    path('<int:pk>/', views.email_detail, name='email-detail'),
    path('<int:pk>/sender-info/', views.sender_info, name='email-sender-info'),
    path('<int:pk>/link-to-job/', views.link_to_job, name='email-link-to-job'),
    path('<int:pk>/unlink-from-job/', views.unlink_from_job, name='email-unlink-from-job'),
    path('<int:pk>/create-job/', views.create_job_from_email, name='email-create-job'),
    path('<int:pk>/link-to-po/', views.link_to_po, name='email-link-to-po'),
    path('<int:pk>/unlink-from-po/', views.unlink_from_po, name='email-unlink-from-po'),
    path('<int:pk>/link-to-bill/', views.link_to_bill, name='email-link-to-bill'),
    path('<int:pk>/unlink-from-bill/', views.unlink_from_bill, name='email-unlink-from-bill'),
    path('<int:pk>/create-po/', views.create_po_from_email, name='email-create-po'),
    path('send/', views._stub_501('POST /api/emails/send/'), name='email-send'),
]
