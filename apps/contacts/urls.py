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
    path('tags/', views.tag_list, name='tag_list'),
    path('tags/<int:tag_id>/delete/', views.delete_tag, name='delete_tag'),
    path('<int:contact_id>/tags/add/', views.add_tag_to_contact, name='add_tag_to_contact'),
    path('<int:contact_id>/tags/<int:tag_id>/remove/', views.remove_tag_from_contact, name='remove_tag_from_contact'),
    path('businesses/<int:business_id>/tags/add/', views.add_tag_to_business, name='add_tag_to_business'),
    path('businesses/<int:business_id>/tags/<int:tag_id>/remove/', views.remove_tag_from_business, name='remove_tag_from_business'),
]