from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from apps.api.jobs.views import JobViewSet
from apps.api.contacts.views import ContactViewSet, BusinessViewSet, PaymentTermsViewSet
from apps.api.estimates.views import EstimateViewSet
from apps.api.worksheets.views import EstWorksheetViewSet
from apps.api.work_orders.views import WorkOrderViewSet


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
        'work-orders': '/api/work-orders/',
        'invoices': '/api/invoices/',
        'purchase-orders': '/api/purchase-orders/',
        'bills': '/api/bills/',
        'price-list-items': '/api/price-list-items/',
        'inventory-items': '/api/inventory-items/',
        'search': '/api/search/',
        'emails': '/api/emails/',
        'work-order-templates': '/api/work-order-templates/',
        'task-templates': '/api/task-templates/',
        'settings': '/api/settings/',
        'line-item-types': '/api/line-item-types/',
    })


app_name = 'api'

router = DefaultRouter()
router.register(r'jobs', JobViewSet, basename='job')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'businesses', BusinessViewSet, basename='business')
router.register(r'payment-terms', PaymentTermsViewSet, basename='payment-terms')
router.register(r'estimates', EstimateViewSet, basename='estimate')
router.register(r'est-worksheets', EstWorksheetViewSet, basename='est-worksheet')
router.register(r'work-orders', WorkOrderViewSet, basename='work-order')

urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
] + router.urls
