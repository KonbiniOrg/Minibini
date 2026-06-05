from django.urls import path
from . import views

app_name = 'estimates'

urlpatterns = [
    path('', views.estimate_list, name='estimate_list'),
    path('<int:estimate_id>/', views.estimate_detail, name='estimate_detail'),
    path('<int:estimate_id>/mark-open/', views.estimate_mark_open, name='estimate_mark_open'),
    path('<int:estimate_id>/update-status/', views.estimate_update_status, name='estimate_update_status'),
    path('<int:estimate_id>/add-line-item/', views.estimate_add_line_item, name='estimate_add_line_item'),
    path('<int:estimate_id>/delete-line-item/<int:line_item_id>/', views.estimate_delete_line_item, name='estimate_delete_line_item'),
    path('<int:estimate_id>/reorder-line-item/<int:line_item_id>/<str:direction>/', views.estimate_reorder_line_item, name='estimate_reorder_line_item'),
    path('<int:estimate_id>/revise/', views.estimate_revise, name='estimate_revise'),
    path('create-for-job/<int:job_id>/', views.estimate_create_for_job, name='estimate_create_for_job'),
    path('worksheets/', views.estworksheet_list, name='estworksheet_list'),
    path('worksheets/<int:worksheet_id>/', views.estworksheet_detail, name='estworksheet_detail'),
    path('worksheets/<int:worksheet_id>/add-task-from-template/', views.task_add_from_template, name='task_add_from_template'),
    path('worksheets/<int:worksheet_id>/add-task-manual/', views.task_add_manual, name='task_add_manual'),
    path('worksheets/<int:worksheet_id>/task/<int:task_id>/reorder/<str:direction>/', views.task_reorder_worksheet, name='task_reorder_worksheet'),
    path('worksheets/<int:worksheet_id>/reorder/<str:item_type>/<int:item_id>/<str:direction>/', views.worksheet_reorder_item, name='worksheet_reorder_item'),
    path('worksheets/create-for-job/<int:job_id>/', views.estworksheet_create_for_job, name='estworksheet_create_for_job'),
    path('templates/', views.work_template_list, name='work_template_list'),
    path('templates/add/', views.add_work_template, name='add_work_template'),
    path('templates/<int:template_id>/', views.work_template_detail, name='work_template_detail'),
    path('templates/<int:template_id>/edit/', views.work_template_edit, name='work_template_edit'),
    path('templates/<int:template_id>/delete/', views.work_template_delete, name='work_template_delete'),
    path('templates/<int:template_id>/reorder/<str:item_type>/<int:item_id>/<str:direction>/', views.template_reorder_item, name='template_reorder_item'),
    path('task-templates/', views.task_template_list, name='task_template_list'),
    path('task-templates/add/', views.add_task_template_standalone, name='add_task_template_standalone'),
    path('task-templates/<int:template_id>/edit/', views.task_template_edit, name='task_template_edit'),
    path('task-templates/<int:template_id>/delete/', views.task_template_delete, name='task_template_delete'),
]
