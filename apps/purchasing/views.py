from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import PurchaseOrder, Bill, BillLineItem, PurchaseOrderLineItem
from .forms import PurchaseOrderForm, PurchaseOrderLineItemForm, PurchaseOrderStatusForm, BillForm, BillLineItemForm, BillStatusForm

def purchase_order_list(request):
    purchase_orders = PurchaseOrder.objects.all().order_by('-po_id')
    return render(request, 'purchasing/purchase_order_list.html', {'purchase_orders': purchase_orders})

def purchase_order_detail(request, po_id):
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    # Handle status update POST request
    if request.method == 'POST' and 'update_status' in request.POST:
        # Check if status transitions are allowed
        if PurchaseOrderStatusForm.has_valid_transitions(purchase_order.status):
            form = PurchaseOrderStatusForm(request.POST, current_status=purchase_order.status)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                if new_status != purchase_order.status:
                    try:
                        purchase_order.status = new_status
                        purchase_order.save()
                        messages.success(request, f'Purchase Order status updated to {purchase_order.get_status_display()}')
                    except Exception as e:
                        messages.error(request, f'Error updating status: {str(e)}')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
        else:
            messages.error(request, f'Cannot update status from {purchase_order.get_status_display()} (terminal state).')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    bills = Bill.objects.filter(purchase_order=purchase_order).order_by('-bill_id')
    line_items = PurchaseOrderLineItem.objects.filter(purchase_order=purchase_order).order_by('line_number', 'line_item_id')
    # Calculate total amount
    total_amount = sum(item.total_amount for item in line_items)

    # Create status form for display only if there are valid transitions
    status_form = None
    if PurchaseOrderStatusForm.has_valid_transitions(purchase_order.status):
        status_form = PurchaseOrderStatusForm(current_status=purchase_order.status)

    return render(request, 'purchasing/purchase_order_detail.html', {
        'purchase_order': purchase_order,
        'bills': bills,
        'line_items': line_items,
        'total_amount': total_amount,
        'status_form': status_form,
        'show_reorder': purchase_order.status == 'draft',
        'reorder_url_name': 'purchasing:purchase_order_reorder_line_item',
        'parent_id': purchase_order.po_id
    })

def purchase_order_create(request):
    """Create a new PurchaseOrder"""
    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            purchase_order = form.save()
            messages.success(request, f'Purchase Order {purchase_order.po_number} created successfully.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm()

    return render(request, 'purchasing/purchase_order_create.html', {'form': form})

def purchase_order_create_for_job(request, job_id):
    """Create a new PurchaseOrder for a specific job"""
    from apps.jobs.models import Job
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, job=job)
        if form.is_valid():
            purchase_order = form.save()
            messages.success(request, f'Purchase Order {purchase_order.po_number} created successfully for Job {job.job_number}.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm(job=job)

    return render(request, 'purchasing/purchase_order_create.html', {'form': form, 'job': job})

def purchase_order_add_line_item(request, po_id):
    """Add line item to PurchaseOrder from Price List"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        form = PurchaseOrderLineItemForm(request.POST)
        if form.is_valid():
            price_list_item = form.cleaned_data['price_list_item']
            qty = form.cleaned_data['qty']

            # Create line item from price list item, copying purchase_price
            line_item = PurchaseOrderLineItem.objects.create(
                purchase_order=purchase_order,
                price_list_item=price_list_item,
                description=price_list_item.description,
                qty=qty,
                units=price_list_item.units,
                price_currency=price_list_item.purchase_price  # Use purchase_price
            )

            messages.success(request, f'Line item "{line_item.description}" added from price list')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderLineItemForm()

    return render(request, 'purchasing/purchase_order_add_line_item.html', {
        'form': form,
        'purchase_order': purchase_order
    })

def bill_list(request):
    bills = Bill.objects.all().order_by('-bill_id')
    return render(request, 'purchasing/bill_list.html', {'bills': bills})

def bill_detail(request, bill_id):
    bill = get_object_or_404(Bill, bill_id=bill_id)

    # Handle status update POST request
    if request.method == 'POST' and 'update_status' in request.POST:
        # Check if status transitions are allowed
        if BillStatusForm.has_valid_transitions(bill.status):
            form = BillStatusForm(request.POST, current_status=bill.status)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                if new_status != bill.status:
                    try:
                        bill.status = new_status
                        bill.save()
                        messages.success(request, f'Bill status updated to {bill.get_status_display()}')
                    except Exception as e:
                        messages.error(request, f'Error updating status: {str(e)}')
            else:
                messages.error(request, 'Error: Invalid status transition.')
            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
        else:
            messages.error(request, f'Cannot update status from {bill.get_status_display()} (terminal state).')
            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    line_items = BillLineItem.objects.filter(bill=bill).order_by('line_number', 'line_item_id')
    # Calculate total amount
    total_amount = sum(item.total_amount for item in line_items)

    # Create status form for display only if there are valid transitions
    status_form = None
    if BillStatusForm.has_valid_transitions(bill.status):
        status_form = BillStatusForm(current_status=bill.status)

    return render(request, 'purchasing/bill_detail.html', {
        'bill': bill,
        'line_items': line_items,
        'total_amount': total_amount,
        'status_form': status_form,
        'show_reorder': bill.status == 'draft',
        'reorder_url_name': 'purchasing:bill_reorder_line_item',
        'parent_id': bill.bill_id
    })

def purchase_order_edit(request, po_id):
    """Edit an existing PurchaseOrder (job and requested_date only)"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, instance=purchase_order)
        if form.is_valid():
            form.save()
            messages.success(request, f'Purchase Order {purchase_order.po_number} updated successfully.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm(instance=purchase_order)

    return render(request, 'purchasing/purchase_order_edit.html', {
        'form': form,
        'purchase_order': purchase_order
    })

def purchase_order_delete(request, po_id):
    """Delete a PurchaseOrder (only allowed in Draft status)"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    # Only allow deletion if PO is in Draft status
    if purchase_order.status != 'draft':
        messages.error(request, f'Cannot delete Purchase Order {purchase_order.po_number}. Only Draft POs can be deleted.')
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    if request.method == 'POST':
        po_number = purchase_order.po_number
        purchase_order.delete()
        messages.success(request, f'Purchase Order {po_number} deleted successfully.')
        return redirect('purchasing:purchase_order_list')

    return render(request, 'purchasing/purchase_order_delete.html', {
        'purchase_order': purchase_order
    })

def purchase_order_cancel(request, po_id):
    """Cancel a PurchaseOrder (only allowed in Issued status)"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    # Only allow cancellation if PO is in Issued status
    if purchase_order.status != 'issued':
        messages.error(request, f'Cannot cancel Purchase Order {purchase_order.po_number}. Only Issued POs can be cancelled.')
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    if request.method == 'POST':
        purchase_order.status = 'cancelled'
        purchase_order.save()
        messages.success(request, f'Purchase Order {purchase_order.po_number} has been cancelled.')
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    return render(request, 'purchasing/purchase_order_cancel.html', {
        'purchase_order': purchase_order
    })

def bill_create(request):
    """Create a new Bill"""
    if request.method == 'POST':
        form = BillForm(request.POST)
        if form.is_valid():
            bill = form.save()
            messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully.')
            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillForm()

    return render(request, 'purchasing/bill_create.html', {'form': form})

def bill_create_for_po(request, po_id):
    """Create a new Bill for a specific Purchase Order and copy its line items"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        form = BillForm(request.POST, purchase_order=purchase_order)
        if form.is_valid():
            bill = form.save()

            # Copy line items from PurchaseOrder to Bill
            po_line_items = PurchaseOrderLineItem.objects.filter(purchase_order=purchase_order).order_by('line_number')
            for po_line_item in po_line_items:
                BillLineItem.objects.create(
                    bill=bill,
                    price_list_item=po_line_item.price_list_item,
                    task=po_line_item.task,
                    description=po_line_item.description,
                    qty=po_line_item.qty,
                    units=po_line_item.units,
                    price_currency=po_line_item.price_currency,
                    line_number=po_line_item.line_number
                )

            line_items_copied = po_line_items.count()
            if line_items_copied > 0:
                messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully for PO {purchase_order.po_number} with {line_items_copied} line item(s) copied.')
            else:
                messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully for PO {purchase_order.po_number}.')

            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillForm(purchase_order=purchase_order)

    return render(request, 'purchasing/bill_create.html', {'form': form, 'purchase_order': purchase_order})

def bill_add_line_item(request, bill_id):
    """Add line item to Bill - either from Price List or manual entry"""
    bill = get_object_or_404(Bill, bill_id=bill_id)

    if request.method == 'POST':
        form = BillLineItemForm(request.POST)
        if form.is_valid():
            price_list_item = form.cleaned_data['price_list_item']
            qty = form.cleaned_data['qty']

            if price_list_item:
                # Create line item from price list item, copying purchase_price
                line_item = BillLineItem.objects.create(
                    bill=bill,
                    price_list_item=price_list_item,
                    description=price_list_item.description,
                    qty=qty,
                    units=price_list_item.units,
                    price_currency=price_list_item.purchase_price  # Use purchase_price
                )
                messages.success(request, f'Line item "{line_item.description}" added from price list')
            else:
                # Create line item from manual entry
                description = form.cleaned_data['description']
                units = form.cleaned_data['units']
                price = form.cleaned_data['price']

                line_item = BillLineItem.objects.create(
                    bill=bill,
                    description=description,
                    qty=qty,
                    units=units,
                    price_currency=price
                )
                messages.success(request, f'Line item "{line_item.description}" added manually')

            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillLineItemForm()

    return render(request, 'purchasing/bill_add_line_item.html', {
        'form': form,
        'bill': bill
    })


@require_POST
def purchase_order_reorder_line_item(request, po_id, line_item_id, direction):
    """Reorder line items within a PurchaseOrder by swapping line numbers."""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)
    line_item = get_object_or_404(PurchaseOrderLineItem, line_item_id=line_item_id, purchase_order=purchase_order)

    # Prevent reordering non-draft purchase orders
    if purchase_order.status != 'draft':
        messages.error(request, f'Cannot reorder line items in a {purchase_order.get_status_display().lower()} purchase order.')
        return redirect('purchasing:purchase_order_detail', po_id=po_id)

    # Get all line items for this purchase order ordered by line_number
    all_items = list(PurchaseOrderLineItem.objects.filter(purchase_order=purchase_order).order_by('line_number', 'line_item_id'))

    # Find the index of the current line item
    try:
        current_index = next(i for i, item in enumerate(all_items) if item.line_item_id == line_item.line_item_id)
    except StopIteration:
        messages.error(request, 'Line item not found in purchase order.')
        return redirect('purchasing:purchase_order_detail', po_id=po_id)

    # Determine the swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        swap_index = current_index + 1
    else:
        messages.error(request, 'Cannot move line item in that direction.')
        return redirect('purchasing:purchase_order_detail', po_id=po_id)

    # Swap line numbers
    current_item = all_items[current_index]
    swap_item = all_items[swap_index]
    current_item.line_number, swap_item.line_number = swap_item.line_number, current_item.line_number

    current_item.save()
    swap_item.save()

    return redirect('purchasing:purchase_order_detail', po_id=po_id)


@require_POST
def bill_reorder_line_item(request, bill_id, line_item_id, direction):
    """Reorder line items within a Bill by swapping line numbers."""
    bill = get_object_or_404(Bill, bill_id=bill_id)
    line_item = get_object_or_404(BillLineItem, line_item_id=line_item_id, bill=bill)

    # Prevent reordering non-draft bills
    if bill.status != 'draft':
        messages.error(request, f'Cannot reorder line items in a {bill.get_status_display().lower()} bill.')
        return redirect('purchasing:bill_detail', bill_id=bill_id)

    # Get all line items for this bill ordered by line_number
    all_items = list(BillLineItem.objects.filter(bill=bill).order_by('line_number', 'line_item_id'))

    # Find the index of the current line item
    try:
        current_index = next(i for i, item in enumerate(all_items) if item.line_item_id == line_item.line_item_id)
    except StopIteration:
        messages.error(request, 'Line item not found in bill.')
        return redirect('purchasing:bill_detail', bill_id=bill_id)

    # Determine the swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        swap_index = current_index + 1
    else:
        messages.error(request, 'Cannot move line item in that direction.')
        return redirect('purchasing:bill_detail', bill_id=bill_id)

    # Swap line numbers
    current_item = all_items[current_index]
    swap_item = all_items[swap_index]
    current_item.line_number, swap_item.line_number = swap_item.line_number, current_item.line_number

    current_item.save()
    swap_item.save()

    return redirect('purchasing:bill_detail', bill_id=bill_id)


def bill_delete(request, bill_id):
    """Delete a Bill (only allowed in Draft status)"""
    bill = get_object_or_404(Bill, bill_id=bill_id)

    # Only allow deletion if Bill is in Draft status
    if bill.status != 'draft':
        messages.error(request, f'Cannot delete Bill {bill.bill_number}. Only Draft Bills can be deleted.')
        return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    if request.method == 'POST':
        bill_number = bill.bill_number
        bill.delete()
        messages.success(request, f'Bill {bill_number} deleted successfully.')
        return redirect('purchasing:bill_list')

    return render(request, 'purchasing/bill_delete.html', {
        'bill': bill
    })


def purchase_order_delete_line_item(request, po_id, line_item_id):
    """Delete a line item from a purchase order and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)
    line_item = get_object_or_404(PurchaseOrderLineItem, line_item_id=line_item_id, purchase_order=purchase_order)

    if request.method == 'POST':
        try:
            # Use the service to delete and renumber
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    # GET request - redirect back to detail (no confirmation needed)
    return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)


def bill_delete_line_item(request, bill_id, line_item_id):
    """Delete a line item from a bill and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    bill = get_object_or_404(Bill, bill_id=bill_id)
    line_item = get_object_or_404(BillLineItem, line_item_id=line_item_id, bill=bill)

    if request.method == 'POST':
        try:
            # Use the service to delete and renumber
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    # GET request - redirect back to detail (no confirmation needed)
    return redirect('purchasing:bill_detail', bill_id=bill.bill_id)