from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from .models import Invoice, InvoiceLineItem
from .services import InvoiceService

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


@require_POST
def invoice_reorder_line_item(request, invoice_id, line_item_id, direction):
    """Reorder line items within an Invoice by swapping line numbers."""
    try:
        InvoiceService.reorder_line_item(line_item_id, direction)
    except ValidationError as e:
        messages.error(request, str(e.message))
    return redirect('invoicing:invoice_detail', invoice_id=invoice_id)
