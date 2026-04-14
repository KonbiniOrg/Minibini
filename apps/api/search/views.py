from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.search.services import SearchService
from apps.api.jobs.serializers import JobSummarySerializer
from apps.api.contacts.serializers import ContactSummarySerializer, BusinessSummarySerializer
from apps.api.invoicing.serializers import InvoiceSerializer
from apps.api.estimates.serializers import EstimateSerializer
from apps.api.purchasing.serializers import BillSummarySerializer, PurchaseOrderSummarySerializer
from apps.api.inventory.serializers import PriceListItemSerializer


def _serialize_categories(categories):
    out = {}

    if 'jobs' in categories:
        groups = categories['jobs'].get('grouped_items', [])
        out['jobs'] = [
            {
                'job': JobSummarySerializer(g['parent']).data,
                'tasks': [{'task_id': t.pk, 'name': t.name} for t in g['tasks']],
            }
            for g in groups
        ]

    if 'contacts' in categories:
        out['contacts'] = ContactSummarySerializer(
            categories['contacts']['items'], many=True
        ).data

    if 'businesses' in categories:
        out['businesses'] = BusinessSummarySerializer(
            categories['businesses']['items'], many=True
        ).data

    if 'invoices' in categories:
        items = categories['invoices'].get('grouped_items', [])
        out['invoices'] = InvoiceSerializer(items, many=True).data

    if 'estimates' in categories:
        items = categories['estimates'].get('grouped_items', [])
        out['estimates'] = EstimateSerializer(items, many=True).data

    if 'bills' in categories:
        out['bills'] = BillSummarySerializer(
            categories['bills']['items'], many=True
        ).data

    if 'purchase_orders' in categories:
        out['purchase_orders'] = PurchaseOrderSummarySerializer(
            categories['purchase_orders']['items'], many=True
        ).data

    if 'price_list_items' in categories:
        out['price_list_items'] = PriceListItemSerializer(
            categories['price_list_items']['items'], many=True
        ).data

    if 'est_worksheets' in categories:
        out['est_worksheets'] = [
            {
                'worksheet_id': ws.pk,
                'job_number': ws.job.job_number if ws.job else None,
                'estimate_number': ws.estimate.estimate_number if ws.estimate else None,
            }
            for ws in categories['est_worksheets']
        ]

    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_view(request):
    query = request.query_params.get('q', '').strip()
    if not query:
        return Response(
            {'detail': 'Query parameter "q" is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    category = request.query_params.get('category', '').strip()

    categories = SearchService.search_all_entities(query)

    if category:
        filter_id = SearchService.get_category_id_from_string(category)
        if filter_id is not None:
            categories = SearchService.apply_category_filter(categories, filter_id)

    total = SearchService.calculate_total_count(categories)
    serialized = _serialize_categories(categories)

    return Response({
        'query': query,
        'total': total,
        'results': serialized,
    })
