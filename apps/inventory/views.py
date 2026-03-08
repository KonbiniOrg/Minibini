from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from apps.inventory.models import PriceListItem
from .forms import InventoryItemForm, PriceListItemForm


def inventory_list(request):
    """Display all active inventoried items with stock quantities."""
    items = PriceListItem.objects.filter(
        is_inventoried=True, is_active=True,
    ).prefetch_related('earmark_set').order_by('code')
    return render(request, 'inventory/inventory_list.html', {'items': items})


def inventory_item_add(request):
    """Add a new inventoried item."""
    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Inventory item "{item.code}" added successfully.')
            return redirect('inventory:inventory_list')
    else:
        form = InventoryItemForm()

    return render(request, 'inventory/inventory_item_form.html', {
        'form': form,
        'title': 'Add Inventory Item',
        'button_text': 'Add Item',
    })


def inventory_item_edit(request, item_id):
    """Edit an existing inventoried item."""
    item = get_object_or_404(PriceListItem, price_list_item_id=item_id, is_inventoried=True)

    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Inventory item "{item.code}" updated successfully.')
            return redirect('inventory:inventory_list')
    else:
        form = InventoryItemForm(instance=item)

    return render(request, 'inventory/inventory_item_form.html', {
        'form': form,
        'item': item,
        'title': f'Edit Inventory Item: {item.code}',
        'button_text': 'Update Item',
    })


def price_list_item_list(request):
    """Display price list items, filtered by active status."""
    show_archived = request.GET.get('show_archived') == '1'

    if show_archived:
        items = PriceListItem.objects.all().order_by('code')
    else:
        items = PriceListItem.objects.filter(is_active=True).order_by('code')

    return render(request, 'invoicing/price_list_item_list.html', {
        'items': items,
        'show_archived': show_archived
    })


def price_list_item_add(request):
    """Add a new price list item."""
    if request.method == 'POST':
        form = PriceListItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Price List Item "{item.code}" created successfully.')
            return redirect('inventory:price_list_item_list')
    else:
        form = PriceListItemForm()

    return render(request, 'invoicing/price_list_item_form.html', {
        'form': form,
        'title': 'Add Price List Item',
        'button_text': 'Create Item'
    })


def price_list_item_edit(request, item_id):
    """Edit an existing price list item."""
    item = get_object_or_404(PriceListItem, price_list_item_id=item_id)

    if request.method == 'POST':
        form = PriceListItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Price List Item "{item.code}" updated successfully.')
            return redirect('inventory:price_list_item_list')
    else:
        form = PriceListItemForm(instance=item)

    return render(request, 'invoicing/price_list_item_form.html', {
        'form': form,
        'item': item,
        'title': f'Edit Price List Item: {item.code}',
        'button_text': 'Update Item'
    })
