from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    path('', views.job_list, name='list'),
    path('create/', views.job_create, name='create'),
    path('<int:job_id>/', views.job_detail, name='detail'),
    path('<int:job_id>/edit/', views.job_edit, name='edit'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/<int:task_id>/', views.task_detail, name='task_detail'),
    path('tasks/<int:task_id>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:task_id>/add-material/', views.material_add, name='material_add'),
    path('materials/<int:material_id>/edit/', views.material_edit, name='material_edit'),
    path('materials/<int:material_id>/delete/', views.material_delete, name='material_delete'),
]
