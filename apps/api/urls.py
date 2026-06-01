from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from apps.api.jobs.views import JobViewSet
from apps.api.contacts.views import ContactViewSet, BusinessViewSet, PaymentTermsViewSet, TagViewSet
from apps.api.estimates.views import EstimateViewSet
from apps.api.worksheets.views import EstWorksheetViewSet
from apps.api.invoicing.views import InvoiceViewSet
from apps.api.purchasing.views import PurchaseOrderViewSet, BillViewSet
from apps.api.inventory.views import PriceListItemViewSet, MaterialViewSet
from apps.api.tasks.views import TaskViewSet
from apps.api.plan_tasks.views import PlanTaskViewSet
from apps.api.bleps.views import BlepViewSet
from apps.api.search.views import search_view
from apps.api.schedule.views import schedule_view
from apps.api.jobs.board_views import (
    board_view, pipeline_view, approved_view, unpaid_view, closed_view,
    task_reorder_view, task_assign_view,
)
from apps.api.home.views import current_blep_view, home_view
from apps.api.stubs import stub_501
from apps.api.templates_config.views import (
    WorkTemplateViewSet, TaskTemplateViewSet,
    AccountingCategoryViewSet, settings_view, units_view,
)
from apps.api.rate_schemes.views import RateSchemeViewSet
from apps.api.change_orders.views import ChangeOrderViewSet
from apps.api.shifts.views import (ShiftViewSet, ShiftChangeRequestViewSet,
                                   BlepChangeRequestViewSet)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_root(request):
    """API root — lists available endpoints."""
    return Response({
        'auth': '/api/auth/',
        'jobs': '/api/jobs/',
        'contacts': '/api/contacts/',
        'businesses': '/api/businesses/',
        'payment-terms': '/api/payment-terms/',
        'est-worksheets': '/api/est-worksheets/',
        'estimates': '/api/estimates/',
        'invoices': '/api/invoices/',
        'purchase-orders': '/api/purchase-orders/',
        'bills': '/api/bills/',
        'price-list-items': '/api/price-list-items/',
        'inventory-items': '/api/inventory-items/',
        'search': '/api/search/',
        'schedule': '/api/schedule/',
        'plan-tasks': '/api/plan-tasks/',
        'emails': '/api/emails/',
        'work-templates': '/api/work-templates/',
        'task-templates': '/api/task-templates/',
        'settings': '/api/settings/',
        'accounting-categories': '/api/accounting-categories/',
        'rate-schemes': '/api/rate-schemes/',
    })


app_name = 'api'

router = DefaultRouter()
router.register(r'jobs', JobViewSet, basename='job')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'businesses', BusinessViewSet, basename='business')
router.register(r'payment-terms', PaymentTermsViewSet, basename='payment-terms')
router.register(r'tags', TagViewSet, basename='tag')
router.register(r'estimates', EstimateViewSet, basename='estimate')
router.register(r'est-worksheets', EstWorksheetViewSet, basename='est-worksheet')
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'purchase-orders', PurchaseOrderViewSet, basename='purchase-order')
router.register(r'bills', BillViewSet, basename='bill')
router.register(r'price-list-items', PriceListItemViewSet, basename='price-list-item')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'plan-tasks', PlanTaskViewSet, basename='plan-task')
router.register(r'bleps', BlepViewSet, basename='blep')
router.register(r'work-templates', WorkTemplateViewSet, basename='work-template')
router.register(r'task-templates', TaskTemplateViewSet, basename='task-template')
router.register(r'accounting-categories', AccountingCategoryViewSet, basename='accounting-category')
router.register(r'rate-schemes', RateSchemeViewSet, basename='rate-scheme')
router.register(r'change-orders', ChangeOrderViewSet, basename='change-order')
router.register(r'shifts', ShiftViewSet, basename='shift')
router.register(r'shift-change-requests', ShiftChangeRequestViewSet, basename='shift-change-request')
router.register(r'blep-change-requests', BlepChangeRequestViewSet, basename='blep-change-request')

urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
    path('portal/', include('apps.api.portal.urls')),
    path('emails/', include('apps.api.email.urls')),
    path('search/', search_view, name='api-search'),
    path('schedule/', schedule_view, name='api-schedule'),
    path('settings/units/', units_view, name='api-settings-units'),
    path('settings/', settings_view, name='api-settings'),
    path('shifts/', include('apps.api.time_tracking.urls')),
    path('expenses/', include('apps.api.expenses.urls')),
    path('reimbursements/', include('apps.api.reimbursements.urls')),
    path('qbo/', include('apps.qbo.urls')),
    path('users/', include('apps.api.users.urls')),
    path('', include('apps.api.deliverables.urls')),
    path('jobs/board/pipeline/', pipeline_view, name='board-pipeline'),
    path('jobs/board/approved/', approved_view, name='board-approved'),
    path('jobs/board/unpaid/', unpaid_view, name='board-unpaid'),
    path('jobs/board/closed/', closed_view, name='board-closed'),
    path('jobs/board/', board_view, name='job-board'),
    path('home/', home_view, name='home'),
    path('bleps/current/', current_blep_view, name='bleps-current'),
    path('tasks/reorder/', task_reorder_view, name='task-reorder'),
    path('tasks/<int:task_pk>/assign/', task_assign_view, name='task-assign'),
path('time-tracking/status/', stub_501('GET /api/time-tracking/status/'), name='time-tracking-status'),
    path('time-tracking/active/', stub_501('GET /api/time-tracking/active/'), name='time-tracking-active'),
] + router.urls
