from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from .models import PurchaseOrder, Bill, BillLineItem, PurchaseOrderLineItem
from .services import PurchaseOrderService, BillService
from apps.core.services import NotFoundError
from .forms import (
    PurchaseOrderForm, PurchaseOrderStatusForm,
    BillForm, BillLineItemForm, BillStatusForm,
    POManualLineItemForm, POPriceListLineItemForm
)

@login_required
@permission_required('core.can_view_jobs', raise_exception=True)
def purchase_order_list(request):
    purchase_orders = PurchaseOrder.objects.all().order_by('-po_id')
    return render(request, 'purchasing/purchase_order_list.html', {'purchase_orders': purchase_orders})

@login_required
@permission_required('core.can_view_jobs', raise_exception=True)
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
                        PurchaseOrderService.update_status(purchase_order.pk, new_status)
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

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_create(request):
    """Create a new PurchaseOrder"""
    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            purchase_order = PurchaseOrderService.create_po(**form.cleaned_data)
            messages.success(request, f'Purchase Order {purchase_order.po_number} created successfully.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm()

    return render(request, 'purchasing/purchase_order_create.html', {'form': form})

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_create_for_job(request, job_id):
    """Create a new PurchaseOrder for a specific job"""
    from apps.jobs.models import Job
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, job=job)
        if form.is_valid():
            purchase_order = PurchaseOrderService.create_po(**form.cleaned_data)
            messages.success(request, f'Purchase Order {purchase_order.po_number} created successfully for Job {job.job_number}.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm(job=job)

    return render(request, 'purchasing/purchase_order_create.html', {'form': form, 'job': job})

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_add_line_item(request, po_id):
    """Add line item to PurchaseOrder - manual entry or from Price List"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        if 'manual_submit' in request.POST:
            # Manual line item form submitted
            manual_form = POManualLineItemForm(request.POST)
            if manual_form.is_valid():
                line_item = PurchaseOrderService.add_line_item(
                    purchase_order.pk, **manual_form.cleaned_data,
                )
                messages.success(request, f'Line item "{line_item.description}" added')
                return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
            else:
                # Manual form has errors, create empty price list form
                pricelist_form = POPriceListLineItemForm()

        elif 'pricelist_submit' in request.POST:
            # Price list line item form submitted
            pricelist_form = POPriceListLineItemForm(request.POST)
            if pricelist_form.is_valid():
                price_list_item = pricelist_form.cleaned_data['price_list_item']
                qty = pricelist_form.cleaned_data['qty']

                line_item = PurchaseOrderService.add_line_item_from_pli(
                    purchase_order.pk, price_list_item.pk, qty,
                )
                messages.success(request, f'Line item "{line_item.description}" added from price list')
                return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
            else:
                # Price list form has errors, create empty manual form
                manual_form = POManualLineItemForm()
        else:
            # Neither form submitted (shouldn't happen)
            manual_form = POManualLineItemForm()
            pricelist_form = POPriceListLineItemForm()
    else:
        # GET request - create both empty forms
        manual_form = POManualLineItemForm()
        pricelist_form = POPriceListLineItemForm()

    return render(request, 'purchasing/purchase_order_add_line_item.html', {
        'manual_form': manual_form,
        'pricelist_form': pricelist_form,
        'purchase_order': purchase_order
    })

@login_required
@permission_required('core.can_view_jobs', raise_exception=True)
def bill_list(request):
    bills = Bill.objects.all().order_by('-bill_id')
    return render(request, 'purchasing/bill_list.html', {'bills': bills})

@login_required
@permission_required('core.can_view_jobs', raise_exception=True)
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
                        BillService.update_status(bill.pk, new_status)
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

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_edit(request, po_id):
    """Edit an existing PurchaseOrder"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, instance=purchase_order)
        if form.is_valid():
            PurchaseOrderService.update_po(purchase_order.pk, **form.cleaned_data)
            messages.success(request, f'Purchase Order {purchase_order.po_number} updated successfully.')
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)
    else:
        form = PurchaseOrderForm(instance=purchase_order)

    return render(request, 'purchasing/purchase_order_edit.html', {
        'form': form,
        'purchase_order': purchase_order
    })

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_delete(request, po_id):
    """Delete a PurchaseOrder (only allowed in Draft status)"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        try:
            po_number = purchase_order.po_number
            PurchaseOrderService.delete_po(purchase_order.pk)
            messages.success(request, f'Purchase Order {po_number} deleted successfully.')
            return redirect('purchasing:purchase_order_list')
        except ValidationError as e:
            messages.error(request, str(e.message))
            return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    # Only show confirmation page if PO is draft
    if purchase_order.status != 'draft':
        messages.error(request, f'Cannot delete Purchase Order {purchase_order.po_number}. Only Draft POs can be deleted.')
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    return render(request, 'purchasing/purchase_order_delete.html', {
        'purchase_order': purchase_order
    })

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_cancel(request, po_id):
    """Cancel a PurchaseOrder (only allowed in Issued status)"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        try:
            PurchaseOrderService.cancel_po(purchase_order.pk)
            messages.success(request, f'Purchase Order {purchase_order.po_number} has been cancelled.')
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    # Only show confirmation page if PO is issued
    if purchase_order.status != 'issued':
        messages.error(request, f'Cannot cancel Purchase Order {purchase_order.po_number}. Only Issued POs can be cancelled.')
        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    return render(request, 'purchasing/purchase_order_cancel.html', {
        'purchase_order': purchase_order
    })

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def bill_create(request):
    """Create a new Bill"""
    if request.method == 'POST':
        form = BillForm(request.POST)
        if form.is_valid():
            bill = BillService.create_bill(**form.cleaned_data)
            messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully.')
            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillForm()

    return render(request, 'purchasing/bill_create.html', {'form': form})

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def bill_create_for_po(request, po_id):
    """Create a new Bill for a specific Purchase Order and copy its line items"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        form = BillForm(request.POST, purchase_order=purchase_order)
        if form.is_valid():
            bill = BillService.create_bill_from_po(
                purchase_order.pk,
                vendor_invoice_number=form.cleaned_data['vendor_invoice_number'],
                due_date=form.cleaned_data.get('due_date'),
            )

            line_items_copied = BillLineItem.objects.filter(bill=bill).count()
            if line_items_copied > 0:
                messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully for PO {purchase_order.po_number} with {line_items_copied} line item(s) copied.')
            else:
                messages.success(request, f'Bill for vendor invoice {bill.vendor_invoice_number} created successfully for PO {purchase_order.po_number}.')

            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillForm(purchase_order=purchase_order)

    return render(request, 'purchasing/bill_create.html', {'form': form, 'purchase_order': purchase_order})

@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def bill_add_line_item(request, bill_id):
    """Add line item to Bill - either from Price List or manual entry"""
    bill = get_object_or_404(Bill, bill_id=bill_id)

    if request.method == 'POST':
        form = BillLineItemForm(request.POST)
        if form.is_valid():
            price_list_item = form.cleaned_data['price_list_item']
            qty = form.cleaned_data['qty']

            if price_list_item:
                line_item = BillService.add_line_item_from_pli(
                    bill.pk, price_list_item.pk, qty,
                )
                messages.success(request, f'Line item "{line_item.description}" added from price list')
            else:
                line_item = BillService.add_line_item(
                    bill.pk,
                    description=form.cleaned_data['description'],
                    qty=qty,
                    units=form.cleaned_data['units'],
                    price=form.cleaned_data['price'],
                    line_item_type=form.cleaned_data['line_item_type'],
                )
                messages.success(request, f'Line item "{line_item.description}" added manually')

            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
    else:
        form = BillLineItemForm()

    return render(request, 'purchasing/bill_add_line_item.html', {
        'form': form,
        'bill': bill
    })


@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
@require_POST
def purchase_order_reorder_line_item(request, po_id, line_item_id, direction):
    """Reorder line items within a PurchaseOrder by swapping line numbers."""
    try:
        PurchaseOrderService.reorder_line_item(line_item_id, direction)
    except ValidationError as e:
        messages.error(request, str(e.message))
    return redirect('purchasing:purchase_order_detail', po_id=po_id)


@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
@require_POST
def bill_reorder_line_item(request, bill_id, line_item_id, direction):
    """Reorder line items within a Bill by swapping line numbers."""
    try:
        BillService.reorder_line_item(line_item_id, direction)
    except ValidationError as e:
        messages.error(request, str(e.message))
    return redirect('purchasing:bill_detail', bill_id=bill_id)


@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def bill_delete(request, bill_id):
    """Delete a Bill (only allowed in Draft status)"""
    bill = get_object_or_404(Bill, bill_id=bill_id)

    if request.method == 'POST':
        try:
            bill_number = bill.bill_number
            BillService.delete_bill(bill.pk)
            messages.success(request, f'Bill {bill_number} deleted successfully.')
            return redirect('purchasing:bill_list')
        except ValidationError as e:
            messages.error(request, str(e.message))
            return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    # Only show confirmation page if bill is draft
    if bill.status != 'draft':
        messages.error(request, f'Cannot delete Bill {bill.bill_number}. Only Draft Bills can be deleted.')
        return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    return render(request, 'purchasing/bill_delete.html', {
        'bill': bill
    })


@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def purchase_order_delete_line_item(request, po_id, line_item_id):
    """Delete a line item from a purchase order and renumber remaining items"""
    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)

    if request.method == 'POST':
        try:
            PurchaseOrderService.delete_line_item(line_item_id)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except (ValidationError, NotFoundError) as e:
            messages.error(request, str(e))

        return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)

    # GET request - redirect back to detail (no confirmation needed)
    return redirect('purchasing:purchase_order_detail', po_id=purchase_order.po_id)


@login_required
@permission_required('core.can_manage_purchasing', raise_exception=True)
def bill_delete_line_item(request, bill_id, line_item_id):
    """Delete a line item from a bill and renumber remaining items"""
    bill = get_object_or_404(Bill, bill_id=bill_id)

    if request.method == 'POST':
        try:
            BillService.delete_line_item(line_item_id)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except (ValidationError, NotFoundError) as e:
            messages.error(request, str(e))

        return redirect('purchasing:bill_detail', bill_id=bill.bill_id)

    # GET request - redirect back to detail (no confirmation needed)
    return redirect('purchasing:bill_detail', bill_id=bill.bill_id)
