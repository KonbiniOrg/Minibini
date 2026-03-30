from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('inbox/', views.email_inbox, name='email_inbox'),
    path('inbox/<int:email_record_id>/', views.email_detail, name='email_detail'),
    path('inbox/<int:email_record_id>/create-job/', views.create_job_from_email, name='create_job_from_email'),
    path('inbox/<int:email_record_id>/associate-job/', views.associate_email_with_job, name='associate_email_with_job'),
    path('inbox/<int:email_record_id>/disassociate-job/', views.disassociate_email_from_job, name='disassociate_email_from_job'),
    path('compose/', views.compose_email, name='compose_email'),
    path('accounting-categories/', views.accounting_category_list, name='accounting_category_list'),
    path('accounting-categories/create/', views.accounting_category_create, name='accounting_category_create'),
    path('accounting-categories/<int:pk>/', views.accounting_category_detail, name='accounting_category_detail'),
    path('accounting-categories/<int:pk>/edit/', views.accounting_category_edit, name='accounting_category_edit'),
]