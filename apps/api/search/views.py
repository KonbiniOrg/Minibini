from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.search.services import SearchService


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

    return Response({
        'query': query,
        'total': total,
        'results': categories,
    })
