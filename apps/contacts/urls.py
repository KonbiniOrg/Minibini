from django.urls import path
from . import views

app_name = 'contacts'

urlpatterns = [
    path('', views.contact_list, name='contact_list'),
    path('add/', views.add_contact, name='add_contact'),
    path('confirm-create-business/', views.confirm_create_business, name='confirm_create_business'),
    path('<int:contact_id>/', views.contact_detail, name='contact_detail'),
    path('<int:contact_id>/edit/', views.edit_contact, name='edit_contact'),
    path('<int:contact_id>/set-default/', views.set_default_contact, name='set_default_contact'),
    path('<int:contact_id>/delete/', views.delete_contact, name='delete_contact'),
    path('businesses/', views.business_list, name='business_list'),
    path('businesses/add/', views.add_business, name='add_business'),
    path('businesses/<int:business_id>/', views.business_detail, name='business_detail'),
    path('businesses/<int:business_id>/edit/', views.edit_business, name='edit_business'),
    path('businesses/<int:business_id>/delete/', views.delete_business, name='delete_business'),
    path('businesses/<int:business_id>/add-contact/', views.add_business_contact, name='add_business_contact'),
]