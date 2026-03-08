from django.urls import path
from . import views

app_name = 'invoicing'

urlpatterns = [
    path('', views.invoice_list, name='invoice_list'),
    path('<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('<int:invoice_id>/reorder-line-item/<int:line_item_id>/<str:direction>/', views.invoice_reorder_line_item, name='invoice_reorder_line_item'),
]
