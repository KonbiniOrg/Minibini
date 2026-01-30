from django.shortcuts import render
from .services import SearchService


def search_view(request):
    """
    Search across all models and return categorized results.
    Case-insensitive search across relevant fields.
    Results are organized into supercategories with subcategories for line items.
    """
    # Extract request parameters
    query = request.GET.get('q', '').strip()
    filter_category = request.GET.get('category', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    # Initialize context
    context = {
        'query': query,
        'categories': {},
        'total_count': 0,
        'filter_category': filter_category,
        'date_from': date_from,
        'date_to': date_to,
        'price_min': price_min,
        'price_max': price_max,
        'available_categories': SearchService.AVAILABLE_CATEGORIES,
    }

    if not query:
        return render(request, 'search/search_results.html', context)

    # Parse price filters
    price_min_value, price_max_value = SearchService.parse_price_filters(price_min, price_max)

    # Search all entities
    categories = SearchService.search_all_entities(query)

    # Apply category filter
    categories = SearchService.apply_category_filter(categories, filter_category)

    # Apply date and price filters
    filtered_categories = SearchService.apply_date_and_price_filters(
        categories, date_from, date_to, price_min_value, price_max_value
    )

    # Calculate total count
    total_count = SearchService.calculate_total_count(filtered_categories)

    # Store result IDs in session for "search within results" functionality
    if query and total_count > 0:
        result_ids = SearchService.build_result_ids_for_session(filtered_categories)
        request.session['search_result_ids'] = result_ids
        request.session['search_original_query'] = query
        context['has_stored_results'] = True
    else:
        context['has_stored_results'] = False

    # Update context with results
    context['categories'] = filtered_categories
    context['total_count'] = total_count

    return render(request, 'search/search_results.html', context)


def search_within_results(request):
    """
    Search within previously saved search results.
    Filters the stored result IDs based on a new search query and additional criteria.
    """
    # Extract request parameters
    within_query = request.GET.get('within_q', '').strip()
    filter_category = request.GET.get('category', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    # Get stored result IDs from session
    result_ids = request.session.get('search_result_ids', {})
    original_query = request.session.get('search_original_query', '')

    # Initialize context
    context = {
        'query': original_query,
        'within_query': within_query,
        'categories': {},
        'total_count': 0,
        'is_within_results': True,
        'filter_category': filter_category,
        'date_from': date_from,
        'date_to': date_to,
        'price_min': price_min,
        'price_max': price_max,
        'available_categories': SearchService.AVAILABLE_CATEGORIES,
    }

    if not result_ids:
        context['has_stored_results'] = False
        return render(request, 'search/search_results.html', context)

    context['has_stored_results'] = True

    if not within_query:
        return render(request, 'search/search_results.html', context)

    # Parse price filters
    price_min_value, price_max_value = SearchService.parse_price_filters(price_min, price_max)

    # Search within stored results
    categories = SearchService.search_within_stored_results(result_ids, within_query)

    # Apply category filter
    categories = SearchService.apply_category_filter(categories, filter_category)

    # Apply date and price filters
    filtered_categories = SearchService.apply_date_and_price_filters(
        categories, date_from, date_to, price_min_value, price_max_value
    )

    # Calculate total count
    total_count = SearchService.calculate_total_count(filtered_categories)

    # Update context with results
    context['categories'] = filtered_categories
    context['total_count'] = total_count

    return render(request, 'search/search_results.html', context)
