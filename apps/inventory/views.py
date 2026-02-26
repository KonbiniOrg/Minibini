from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import InventoryItem
from .forms import InventoryItemForm


def inventory_list(request):
    """Display all active inventory items with stock quantities."""
    items = InventoryItem.objects.filter(is_active=True).order_by('code')
    return render(request, 'inventory/inventory_list.html', {'items': items})


def inventory_item_add(request):
    """Add a new item to the inventory."""
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
    """Edit an existing inventory item."""
    item = get_object_or_404(InventoryItem, inventory_item_id=item_id)

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
