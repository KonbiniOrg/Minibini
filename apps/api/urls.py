from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


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

urlpatterns = [
    path('', api_root, name='api-root'),
    # Submodule URLs added in subsequent tasks
]
