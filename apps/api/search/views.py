from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.search.services import SearchService
from apps.api.jobs.serializers import JobSummarySerializer, JobSearchSerializer
from apps.api.invoicing.serializers import InvoiceSerializer
from apps.api.estimates.serializers import EstimateSerializer
from apps.api.purchasing.serializers import BillSummarySerializer, PurchaseOrderSummarySerializer
from apps.api.inventory.serializers import InventoryItemSerializer
from apps.contacts.models import Contact, Business


class ContactSearchSerializer(drf_serializers.ModelSerializer):
    name = drf_serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = ['contact_id', 'name', 'email', 'mobile_number', 'work_number', 'home_number', 'city']


class BusinessSearchSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ['business_id', 'business_name', 'our_reference_code', 'business_address', 'business_phone']


def _serialize_categories(categories):
    out = {}

    if 'jobs' in categories:
        groups = categories['jobs'].get('grouped_items', [])
        out['jobs'] = [
            {
                'job': JobSearchSerializer(g['parent']).data,
                'tasks': [{'task_id': t.pk, 'name': t.name} for t in g['tasks']],
            }
            for g in groups
        ]

    if 'contacts' in categories:
        out['contacts'] = ContactSearchSerializer(
            categories['contacts']['items'], many=True
        ).data

    if 'businesses' in categories:
        out['businesses'] = BusinessSearchSerializer(
            categories['businesses']['items'], many=True
        ).data

    if 'invoices' in categories:
        result = []
        for item in categories['invoices'].get('grouped_items', []):
            data = dict(InvoiceSerializer(item).data)
            data['matching_descriptions'] = [
                li.description for li in getattr(item, 'matching_line_items', []) if li.description
            ]
            result.append(data)
        out['invoices'] = result

    if 'estimates' in categories:
        result = []
        for item in categories['estimates'].get('grouped_items', []):
            data = dict(EstimateSerializer(item).data)
            data['matching_descriptions'] = [
                li.description for li in getattr(item, 'matching_line_items', []) if li.description
            ]
            result.append(data)
        out['estimates'] = result

    if 'bills' in categories:
        result = []
        for item in categories['bills']['items']:
            data = dict(BillSummarySerializer(item).data)
            data['matching_descriptions'] = [
                li.description for li in getattr(item, 'matching_line_items', []) if li.description
            ]
            result.append(data)
        out['bills'] = result

    if 'purchase_orders' in categories:
        result = []
        for item in categories['purchase_orders']['items']:
            data = dict(PurchaseOrderSummarySerializer(item).data)
            data['matching_descriptions'] = [
                li.description for li in getattr(item, 'matching_line_items', []) if li.description
            ]
            result.append(data)
        out['purchase_orders'] = result

    if 'inventory_items' in categories:
        out['inventory_items'] = InventoryItemSerializer(
            categories['inventory_items']['items'], many=True
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
    date_from = request.query_params.get('date_from', '').strip() or None
    date_to = request.query_params.get('date_to', '').strip() or None
    start_date_from = request.query_params.get('start_date_from', '').strip() or None
    start_date_to = request.query_params.get('start_date_to', '').strip() or None
    job_statuses = request.query_params.getlist('job_status')
    price_min_str = request.query_params.get('price_min', '').strip()
    price_max_str = request.query_params.get('price_max', '').strip()
    price_min, price_max = SearchService.parse_price_filters(price_min_str, price_max_str)

    categories = SearchService.search_all_entities(query)

    if category:
        filter_id = SearchService.get_category_id_from_string(category)
        if filter_id is not None:
            categories = SearchService.apply_category_filter(categories, filter_id)

    if date_from or date_to:
        categories = SearchService.apply_date_and_price_filters(
            categories, date_from, date_to, None, None
        )

    if start_date_from or start_date_to:
        categories = SearchService.apply_start_date_filter(
            categories, start_date_from, start_date_to
        )

    if job_statuses:
        categories = SearchService.apply_job_status_filter(categories, job_statuses)

    if price_min is not None or price_max is not None:
        categories = SearchService.apply_price_filter(categories, price_min, price_max)

    within = request.query_params.get('within', '').strip()
    if within:
        result_ids = SearchService.build_result_ids_for_session(categories)
        categories = SearchService.search_within_stored_results(result_ids, within)

    total = SearchService.calculate_total_count(categories)
    serialized = _serialize_categories(categories)

    return Response({
        'query': query,
        'total': total,
        'results': serialized,
    })
