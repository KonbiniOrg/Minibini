from django.shortcuts import render
from apps.invoicing.models import PriceListItem


def inventory_list(request):
    """Display all active inventory items with stock quantities."""
    items = PriceListItem.objects.filter(is_active=True, is_inventoried=True).order_by('code')
    return render(request, 'inventory/inventory_list.html', {'items': items})
