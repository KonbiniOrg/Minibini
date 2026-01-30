from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Invoice, InvoiceLineItem, PriceListItem
from .forms import PriceListItemForm

def invoice_list(request):
    invoices = Invoice.objects.all().order_by('-invoice_id')
    return render(request, 'invoicing/invoice_list.html', {'invoices': invoices})

def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(Invoice, invoice_id=invoice_id)
    line_items = InvoiceLineItem.objects.filter(invoice=invoice).order_by('line_item_id')
    # Calculate total amount
    total_amount = sum(item.total_amount for item in line_items)
    return render(request, 'invoicing/invoice_detail.html', {
        'invoice': invoice,
        'line_items': line_items,
        'total_amount': total_amount,
        'show_reorder': invoice.status == 'draft',
        'reorder_url_name': 'invoicing:invoice_reorder_line_item',
        'parent_id': invoice.invoice_id
    })


def price_list_item_list(request):
    """Display all price list items."""
    items = PriceListItem.objects.all().order_by('code')
    return render(request, 'invoicing/price_list_item_list.html', {
        'items': items
    })


def price_list_item_add(request):
    """Add a new price list item."""
    if request.method == 'POST':
        form = PriceListItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Price List Item "{item.code}" created successfully.')
            return redirect('invoicing:price_list_item_list')
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
            return redirect('invoicing:price_list_item_list')
    else:
        form = PriceListItemForm(instance=item)

    return render(request, 'invoicing/price_list_item_form.html', {
        'form': form,
        'item': item,
        'title': f'Edit Price List Item: {item.code}',
        'button_text': 'Update Item'
    })


@require_POST
def invoice_reorder_line_item(request, invoice_id, line_item_id, direction):
    """Reorder line items within an Invoice by swapping line numbers."""
    invoice = get_object_or_404(Invoice, invoice_id=invoice_id)
    line_item = get_object_or_404(InvoiceLineItem, line_item_id=line_item_id, invoice=invoice)

    # Prevent reordering non-draft invoices
    if invoice.status != 'draft':
        messages.error(request, f'Cannot reorder line items in a {invoice.get_status_display().lower()} invoice.')
        return redirect('invoicing:invoice_detail', invoice_id=invoice_id)

    # Get all line items for this invoice ordered by line_number
    all_items = list(InvoiceLineItem.objects.filter(invoice=invoice).order_by('line_number', 'line_item_id'))

    # Find the index of the current line item
    try:
        current_index = next(i for i, item in enumerate(all_items) if item.line_item_id == line_item.line_item_id)
    except StopIteration:
        messages.error(request, 'Line item not found in invoice.')
        return redirect('invoicing:invoice_detail', invoice_id=invoice_id)

    # Determine the swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        swap_index = current_index + 1
    else:
        messages.error(request, 'Cannot move line item in that direction.')
        return redirect('invoicing:invoice_detail', invoice_id=invoice_id)

    # Swap line numbers
    current_item = all_items[current_index]
    swap_item = all_items[swap_index]
    current_item.line_number, swap_item.line_number = swap_item.line_number, current_item.line_number

    current_item.save()
    swap_item.save()

    return redirect('invoicing:invoice_detail', invoice_id=invoice_id)