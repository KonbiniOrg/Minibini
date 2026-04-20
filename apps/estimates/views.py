from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django import forms
from django.utils import timezone
from django.db import models
from django.views.decorators.http import require_POST
from .models import (
    Estimate, EstimateLineItem, EstWorksheet, WorkTemplate,
    TaskTemplate, TemplateTaskAssociation, TemplateBundle
)
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, PlanTask
from apps.core.services import TaxCalculationService, NotFoundError
from .services import (
    EstimateService, WorkTemplateService, WorksheetService,
)
from .forms import (
    WorkTemplateForm, TaskTemplateForm, EstWorksheetForm,
    ManualLineItemForm, PriceListLineItemForm, EstimateStatusForm
)
from apps.jobs.forms import TaskEditForm, TaskFromTemplateForm


def _build_container_items_from_associations(associations):
    """Normalize TemplateTaskAssociations into the shared container_items format."""
    bundles_by_id = {}
    unbundled = []

    for assoc in associations:
        item = {
            'id': assoc.pk,
            'name': assoc.task_template.template_name,
            'description': assoc.task_template.description,
            'units': assoc.task_template.units,
            'rate': assoc.task_template.rate,
            'est_qty': assoc.est_qty,
            'mapping_strategy': assoc.mapping_strategy,
            'remove_id': assoc.task_template.template_id,
            'sort_order': assoc.sort_order,
        }
        if assoc.mapping_strategy == 'bundle' and assoc.bundle:
            bid = assoc.bundle.pk
            if bid not in bundles_by_id:
                bundles_by_id[bid] = {
                    'id': bid,
                    'name': assoc.bundle.name,
                    'accounting_category_name': assoc.bundle.accounting_category.name,
                    'sort_order': assoc.bundle.sort_order,
                    'items': [],
                }
            bundles_by_id[bid]['items'].append(item)
        else:
            unbundled.append((assoc.sort_order, item))

    # Sort within each bundle
    for bundle_data in bundles_by_id.values():
        bundle_data['items'].sort(key=lambda i: i['sort_order'])

    # Build interleaved list
    container_items = []
    for sort_order, item in unbundled:
        container_items.append(('task', item, sort_order))
    for bundle_data in bundles_by_id.values():
        container_items.append(('bundle', bundle_data, bundle_data['sort_order']))
    container_items.sort(key=lambda x: x[2])
    return container_items


def _next_container_sort_order(template):
    """Get the next sort_order in the shared container-level space (bundles + unbundled associations)."""
    from .models import TemplateTaskAssociation, TemplateBundle
    max_assoc = TemplateTaskAssociation.objects.filter(
        work_template=template, bundle__isnull=True
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    max_bundle = TemplateBundle.objects.filter(
        work_template=template
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    return max(max_assoc, max_bundle) + 1


def _build_container_items_from_tasks(worksheet):
    """Normalize worksheet PlanTasks into the shared container_items format."""
    tasks = PlanTask.objects.filter(
        est_worksheet=worksheet
    ).prefetch_related('plan_materials').order_by('sort_order', 'plan_task_id')

    container_items = []
    for task in tasks:
        materials = list(task.plan_materials.all())
        item = {
            'id': task.plan_task_id,
            'name': task.name,
            'description': task.description,
            'units': task.units,
            'rate': task.rate,
            'est_qty': task.est_qty,
            'remove_id': task.plan_task_id,
            'sort_order': task.sort_order or 0,
            'detail_url': reverse('jobs:task_detail', args=[task.plan_task_id]),
            'materials': materials,
        }
        container_items.append(('task', item, task.sort_order or 0))

    container_items.sort(key=lambda x: x[2])
    return container_items


def _next_worksheet_sort_order(worksheet):
    """Get the next sort_order for tasks on a worksheet."""
    max_task = PlanTask.objects.filter(
        est_worksheet=worksheet
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    return max_task + 1


def estimate_list(request):
    estimates = Estimate.objects.all().order_by('-estimate_id')
    return render(request, 'jobs/estimate_list.html', {'estimates': estimates})

def estimate_detail(request, estimate_id):
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # Handle status update POST request
    if request.method == 'POST' and 'update_status' in request.POST:
        # Check if status transitions are allowed
        if EstimateStatusForm.has_valid_transitions(estimate.status):
            form = EstimateStatusForm(request.POST, current_status=estimate.status)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                if new_status != estimate.status:
                    try:
                        EstimateService.update_status(estimate.pk, new_status)
                        messages.success(request, f'Estimate status updated to {new_status.title()}')
                    except Exception as e:
                        messages.error(request, f'Error updating status: {str(e)}')
                return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)
        else:
            messages.error(request, f'Cannot update status from {estimate.get_status_display()} (terminal state).')
            return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)

    # Get line items and calculate subtotal
    line_items = EstimateLineItem.objects.filter(estimate=estimate).order_by('line_item_id')
    subtotal = sum(item.total_amount for item in line_items)

    # Get customer business for tax calculation
    customer = None
    if hasattr(estimate.job.contact, 'business') and estimate.job.contact.business:
        customer = estimate.job.contact.business

    # Calculate tax
    tax_amount = TaxCalculationService.calculate_document_tax(estimate, customer=customer)
    total_with_tax = subtotal + tax_amount

    # Check if customer is tax exempt
    is_tax_exempt = customer and customer.tax_multiplier == Decimal('0.00')

    # Check for associated worksheet
    worksheet = EstWorksheet.objects.filter(estimate=estimate).first()

    # Create status form for display only if there are valid transitions
    status_form = None
    if EstimateStatusForm.has_valid_transitions(estimate.status):
        status_form = EstimateStatusForm(current_status=estimate.status)

    return render(request, 'jobs/estimate_detail.html', {
        'estimate': estimate,
        'line_items': line_items,
        'subtotal': subtotal,
        'tax_amount': tax_amount,
        'total_with_tax': total_with_tax,
        'is_tax_exempt': is_tax_exempt,
        'worksheet': worksheet,
        'status_form': status_form,
        'show_reorder': estimate.status == Estimate.STATUS_DRAFT,
        'reorder_url_name': 'estimates:estimate_reorder_line_item',
        'parent_id': estimate.estimate_id
    })


def add_work_template(request):
    if request.method == 'POST':
        form = WorkTemplateForm(request.POST)
        if form.is_valid():
            template = WorkTemplateService.create_template(**form.cleaned_data)
            messages.success(request, f'Work Order Template "{template.template_name}" created successfully.')
            return redirect('estimates:work_template_detail', template_id=template.template_id)
    else:
        form = WorkTemplateForm()

    return render(request, 'jobs/add_work_template.html', {'form': form})


def work_template_edit(request, template_id):
    template = get_object_or_404(WorkTemplate, template_id=template_id)

    if request.method == 'POST':
        form = WorkTemplateForm(request.POST, instance=template)
        if form.is_valid():
            WorkTemplateService.update_template(template.pk, **form.cleaned_data)
            messages.success(request, f'Work Order Template "{template.template_name}" updated successfully.')
            return redirect('estimates:work_template_detail', template_id=template.template_id)
    else:
        form = WorkTemplateForm(instance=template)

    return render(request, 'jobs/work_template_edit.html', {
        'form': form,
        'template': template
    })


@require_POST
def work_template_delete(request, template_id):
    template = get_object_or_404(WorkTemplate, template_id=template_id)
    template_name = template.template_name
    WorkTemplateService.delete_template(template.pk)
    messages.success(request, f'Work Order Template "{template_name}" deleted successfully.')
    return redirect('estimates:work_template_list')


def work_template_list(request):
    templates = WorkTemplate.objects.all().order_by('-created_date')
    return render(request, 'jobs/work_template_list.html', {'templates': templates})


def work_template_detail(request, template_id):
    template = get_object_or_404(WorkTemplate, template_id=template_id)

    # Handle TaskTemplate association
    if request.method == 'POST' and 'associate_task' in request.POST:
        task_template_id = request.POST.get('task_template_id')
        est_qty = request.POST.get('est_qty', '1.00')
        if task_template_id:
            task_template = get_object_or_404(TaskTemplate, template_id=task_template_id)

            next_sort_order = _next_container_sort_order(template)

            association, created = TemplateTaskAssociation.objects.get_or_create(
                work_template=template,
                task_template=task_template,
                defaults={'est_qty': est_qty, 'sort_order': next_sort_order}
            )
            if created:
                messages.success(request, f'Task Template "{task_template.template_name}" associated with quantity {est_qty}.')
            else:
                messages.warning(request, f'Task Template "{task_template.template_name}" is already associated.')
        return redirect('estimates:work_template_detail', template_id=template_id)

    # Handle TaskTemplate removal (unbundle if bundled, delete if unbundled)
    if request.method == 'POST' and 'remove_task' in request.POST:
        task_template_id = request.POST.get('remove_task')
        if task_template_id:
            task_template = get_object_or_404(TaskTemplate, template_id=task_template_id)
            assoc = TemplateTaskAssociation.objects.filter(
                work_template=template,
                task_template=task_template
            ).first()
            if assoc and assoc.mapping_strategy == 'bundle' and assoc.bundle:
                WorkTemplateService.unbundle_association(template.pk, assoc.pk)
                messages.success(request, f'"{task_template.template_name}" unbundled.')
            elif assoc:
                WorkTemplateService.delete_association(template.pk, assoc.pk)
                messages.success(request, f'Task Template "{task_template.template_name}" removed.')
        return redirect('estimates:work_template_detail', template_id=template_id)

    # Handle bundle creation
    if request.method == 'POST' and 'bundle_tasks' in request.POST:
        from apps.core.models import AccountingCategory

        selected_ids = request.POST.getlist('selected_tasks')
        bundle_name = request.POST.get('bundle_name', '').strip()
        accounting_category_id = request.POST.get('accounting_category')

        if not bundle_name:
            messages.error(request, 'Bundle name is required.')
        elif not accounting_category_id:
            messages.error(request, 'Line item type is required.')
        else:
            accounting_category = get_object_or_404(AccountingCategory, pk=accounting_category_id)
            try:
                WorkTemplateService.bundle_associations(
                    template.pk,
                    [int(i) for i in selected_ids],
                    bundle_name,
                    accounting_category,
                )
                messages.success(request, f'Bundle "{bundle_name}" updated.')
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))

        return redirect('estimates:work_template_detail', template_id=template_id)

    # Get task template associations with bundle info
    from apps.core.models import AccountingCategory

    associations = TemplateTaskAssociation.objects.filter(
        work_template=template,
        task_template__is_active=True
    ).select_related('task_template', 'bundle').order_by('sort_order', 'task_template__template_name')

    # Build normalized container_items for shared _bundle_table.html partial
    container_items = _build_container_items_from_associations(associations)

    # Get available task templates (not yet associated)
    associated_task_ids = associations.values_list('task_template_id', flat=True)
    available_templates = TaskTemplate.objects.filter(is_active=True).exclude(template_id__in=associated_task_ids)

    # Get line item types for bundle form
    accounting_categories = AccountingCategory.objects.all().order_by('name')

    return render(request, 'jobs/work_template_detail.html', {
        'template': template,
        'container_items': container_items,
        'available_templates': available_templates,
        'accounting_categories': accounting_categories,
        'can_edit': True,
        'reorder_container_url': 'estimates:template_reorder_item',
        'reorder_in_bundle_url': 'estimates:template_reorder_in_bundle',
        'container_id': template.template_id,
    })


def estworksheet_list(request):
    """List all EstWorksheets"""
    worksheets = EstWorksheet.objects.select_related('job', 'estimate').order_by('-created_date')
    return render(request, 'jobs/estworksheet_list.html', {'worksheets': worksheets})


def estworksheet_detail(request, worksheet_id):
    """Show details of a specific EstWorksheet with its tasks."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)
    can_edit = worksheet.status == EstWorksheet.STATUS_DRAFT

    # Build context
    container_items = _build_container_items_from_tasks(worksheet)

    # Calculate total cost from all tasks
    all_tasks = PlanTask.objects.filter(est_worksheet=worksheet)
    total_cost = sum(
        (t.rate * t.est_qty) for t in all_tasks if t.rate and t.est_qty
    )

    return render(request, 'jobs/estworksheet_detail.html', {
        'worksheet': worksheet,
        'container_items': container_items,
        'total_cost': total_cost,
        'can_edit': can_edit,
        'reorder_container_url': 'estimates:worksheet_reorder_item',
        'container_id': worksheet.est_worksheet_id,
    })


def estimate_mark_open(request, estimate_id):
    """Mark an estimate as Open and update associated worksheet to Final"""
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    if request.method == 'POST':
        try:
            EstimateService.mark_open(estimate.pk)
            messages.success(request, f'Estimate {estimate.estimate_number} marked as Open')
        except ValidationError:
            messages.warning(request, 'Only Draft estimates can be marked as Open')

    return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)


def estworksheet_revise(request, worksheet_id):
    """Create a new revision of a worksheet"""
    parent_worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    if request.method == 'POST':
        if parent_worksheet.status != EstWorksheet.STATUS_DRAFT:
            new_worksheet = WorksheetService.revise_worksheet(parent_worksheet.pk)
            messages.success(request, f'New worksheet revision created (v{new_worksheet.version})')
            return redirect('estimates:estworksheet_detail', worksheet_id=new_worksheet.est_worksheet_id)
        else:
            messages.warning(request, 'Cannot revise a Draft worksheet')

    return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)


def task_template_list(request):
    """List all TaskTemplates with all fields"""
    templates = TaskTemplate.objects.all().prefetch_related('work_templates').order_by('template_name')
    return render(request, 'jobs/task_template_list.html', {'templates': templates})


def add_task_template_standalone(request):
    """Create a new TaskTemplate independently"""
    if request.method == 'POST':
        form = TaskTemplateForm(request.POST)
        if form.is_valid():
            task_template = WorkTemplateService.create_task_template(**form.cleaned_data)
            messages.success(request, f'Task Template "{task_template.template_name}" created successfully.')
            return redirect('estimates:task_template_list')
    else:
        form = TaskTemplateForm()

    return render(request, 'jobs/add_task_template_standalone.html', {'form': form})


def task_template_edit(request, template_id):
    """Edit an existing TaskTemplate."""
    template = get_object_or_404(TaskTemplate, template_id=template_id)

    if request.method == 'POST':
        form = TaskTemplateForm(request.POST, instance=template)
        if form.is_valid():
            WorkTemplateService.update_task_template(template.pk, **form.cleaned_data)
            messages.success(request, f'Task Template "{template.template_name}" updated successfully.')
            return redirect('estimates:task_template_list')
    else:
        form = TaskTemplateForm(instance=template)

    # Get WorkTemplates using this TaskTemplate
    work_templates = WorkTemplate.objects.filter(
        templatetaskassociation__task_template=template
    ).distinct()

    return render(request, 'jobs/task_template_edit.html', {
        'form': form,
        'template': template,
        'work_templates': work_templates,
        'can_delete': not work_templates.exists()
    })


@require_POST
def task_template_delete(request, template_id):
    """Delete a TaskTemplate."""
    template = get_object_or_404(TaskTemplate, template_id=template_id)
    try:
        template_name = template.template_name
        WorkTemplateService.delete_task_template(template.pk)
        messages.success(request, f'Task Template "{template_name}" deleted successfully.')
    except ValidationError as e:
        messages.error(request, str(e.message))
        return redirect('estimates:task_template_edit', template_id=template_id)
    return redirect('estimates:task_template_list')


def estworksheet_create_for_job(request, job_id):
    """Create a new EstWorksheet for a specific Job, optionally from a template"""
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = EstWorksheetForm(request.POST, initial={'job': job})
        if form.is_valid():
            template = form.cleaned_data.get('template')
            worksheet = WorksheetService.create_worksheet(
                job.pk, template=template,
            )

            # If a template was selected, generate tasks (and bundles) from it
            if template:
                template.generate_tasks_for_worksheet(worksheet)
                messages.success(request, f'Worksheet created from template "{template.template_name}" for Job {job.job_number}')
            else:
                messages.success(request, f'Worksheet created successfully for Job {job.job_number}')

            return redirect('estimates:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
    else:
        form = EstWorksheetForm(initial={'job': job})
        # Hide the job field since it's already set
        form.fields['job'].widget = forms.HiddenInput()

    return render(request, 'jobs/estworksheet_create_for_job.html', {
        'form': form,
        'job': job
    })


def task_add_from_template(request, worksheet_id):
    """Add Task to EstWorksheet from TaskTemplate"""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    # Prevent adding tasks to non-draft worksheets
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, f'Cannot add tasks to a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)

    if request.method == 'POST':
        form = TaskFromTemplateForm(request.POST)
        if form.is_valid():
            template = form.cleaned_data['template']
            est_qty = form.cleaned_data['est_qty']

            task = WorksheetService.add_task_from_template(
                worksheet.pk, template.pk, est_qty=est_qty,
            )

            messages.success(request, f'Task "{task.name}" added from template')
            return redirect('estimates:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
    else:
        form = TaskFromTemplateForm()

    return render(request, 'jobs/task_add_from_template.html', {
        'form': form,
        'worksheet': worksheet
    })


def task_add_manual(request, worksheet_id):
    """Add Task to EstWorksheet manually"""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    # Prevent adding tasks to non-draft worksheets
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, f'Cannot add tasks to a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)

    if request.method == 'POST':
        task_instance = PlanTask(est_worksheet=worksheet)
        form = TaskEditForm(request.POST, instance=task_instance)
        if form.is_valid():
            task = WorksheetService.add_task_manual(
                worksheet.pk, **form.cleaned_data,
            )

            messages.success(request, f'Task "{task.name}" added manually')
            return redirect('estimates:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
    else:
        form = TaskEditForm()

    return render(request, 'jobs/task_add_manual.html', {
        'form': form,
        'worksheet': worksheet
    })


def estimate_delete_line_item(request, estimate_id, line_item_id):
    """Delete a line item from an estimate and renumber remaining items"""
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    if request.method == 'POST':
        try:
            EstimateService.delete_line_item(line_item_id)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)

    # GET request - show confirmation (optional, can skip for simple delete)
    return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)


def estimate_add_line_item(request, estimate_id):
    """Add line item to Estimate - either manually or from Price List"""
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # Prevent modifications to non-draft estimates
    if estimate.status != Estimate.STATUS_DRAFT:
        messages.error(request, f'Cannot add line items to a {estimate.get_status_display().lower()} estimate. Only draft estimates can be modified.')
        return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)

    if request.method == 'POST':
        # Determine which form was submitted
        if 'manual_submit' in request.POST:
            # Manual line item form submitted
            manual_form = ManualLineItemForm(request.POST)
            if manual_form.is_valid():
                line_item = EstimateService.add_line_item(
                    estimate.pk, **manual_form.cleaned_data,
                )

                messages.success(request, f'Line item "{line_item.description}" added')
                return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)
            else:
                # Manual form has errors, create empty price list form
                pricelist_form = PriceListLineItemForm()

        elif 'pricelist_submit' in request.POST:
            # Price list line item form submitted
            pricelist_form = PriceListLineItemForm(request.POST)
            if pricelist_form.is_valid():
                price_list_item = pricelist_form.cleaned_data['price_list_item']
                qty = pricelist_form.cleaned_data['qty']

                line_item = EstimateService.add_line_item_from_pli(
                    estimate.pk, price_list_item.pk, qty=qty,
                )

                messages.success(request, f'Line item "{line_item.description}" added from price list')
                return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)
            else:
                # Price list form has errors, create empty manual form
                manual_form = ManualLineItemForm()
        else:
            # Neither form submitted (shouldn't happen)
            manual_form = ManualLineItemForm()
            pricelist_form = PriceListLineItemForm()
    else:
        # GET request - create both empty forms
        manual_form = ManualLineItemForm()
        pricelist_form = PriceListLineItemForm()

    return render(request, 'jobs/estimate_add_line_item.html', {
        'manual_form': manual_form,
        'pricelist_form': pricelist_form,
        'estimate': estimate
    })


def estimate_update_status(request, estimate_id):
    """Update Estimate status"""
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # Prevent modifications to superseded estimates
    if estimate.status == Estimate.STATUS_SUPERSEDED:
        messages.error(request, 'Cannot update the status of a superseded estimate.')
        return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)

    if request.method == 'POST':
        form = EstimateStatusForm(request.POST, current_status=estimate.status)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            if new_status != estimate.status:
                EstimateService.update_status(estimate.pk, new_status)
                messages.success(request, f'Estimate status updated to {new_status.title()}')
            return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)
    else:
        form = EstimateStatusForm(current_status=estimate.status)

    return render(request, 'jobs/estimate_update_status.html', {
        'form': form,
        'estimate': estimate
    })


def estimate_create_for_job(request, job_id):
    """Create a new Estimate for a specific Job - creates directly with defaults"""
    job = get_object_or_404(Job, job_id=job_id)

    # Check if an estimate already exists for this job
    existing_estimate = Estimate.objects.filter(job=job).exclude(status=Estimate.STATUS_SUPERSEDED).first()
    if existing_estimate:
        if existing_estimate.status == Estimate.STATUS_DRAFT:
            messages.info(request, f'A draft estimate already exists for this job. You can edit it here.')
            return redirect('estimates:estimate_detail', estimate_id=existing_estimate.estimate_id)
        else:
            messages.error(request, f'An estimate already exists for this job. Use the Revise option to create a new version.')
            return redirect('estimates:estimate_detail', estimate_id=existing_estimate.estimate_id)

    estimate = EstimateService.create_for_job(job.pk)

    messages.success(request, f'Estimate {estimate.estimate_number} (v{estimate.version}) created successfully')
    return redirect('estimates:estimate_detail', estimate_id=estimate.estimate_id)


def estimate_revise(request, estimate_id):
    """Create a new revision of an estimate"""
    parent_estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    if request.method == 'POST':
        try:
            new_estimate = EstimateService.revise_estimate(parent_estimate.pk)
            messages.success(request, f'Created new revision of estimate {new_estimate.estimate_number} (v{new_estimate.version})')
            return redirect('estimates:estimate_detail', estimate_id=new_estimate.estimate_id)
        except ValidationError:
            messages.info(request, 'Cannot revise a draft estimate. Please edit it directly.')
            return redirect('estimates:estimate_detail', estimate_id=parent_estimate.estimate_id)

    return render(request, 'jobs/estimate_revise_confirm.html', {
        'estimate': parent_estimate
    })


@require_POST
def task_reorder_worksheet(request, worksheet_id, task_id, direction):
    """Reorder plan tasks within an EstWorksheet by swapping sort_order."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    # Prevent reordering non-draft worksheets
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, f'Cannot reorder tasks in a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)

    try:
        WorksheetService.reorder_items(worksheet.pk, 'task', task_id, direction)
    except (ValidationError, NotFoundError) as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))

    return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)


@require_POST
def estimate_reorder_line_item(request, estimate_id, line_item_id, direction):
    """Reorder line items within an Estimate by swapping line numbers."""
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    try:
        EstimateService.reorder_line_item(line_item_id, direction)
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect('estimates:estimate_detail', estimate_id=estimate_id)


@require_POST
def template_reorder_item(request, template_id, item_type, item_id, direction):
    """Reorder items at the container level within a WorkTemplate."""
    template = get_object_or_404(WorkTemplate, template_id=template_id)
    try:
        WorkTemplateService.reorder_items(template.pk, item_type, item_id, direction)
    except (NotFoundError, ValidationError) as e:
        messages.error(request, str(e))
    return redirect('estimates:work_template_detail', template_id=template_id)


@require_POST
def template_reorder_in_bundle(request, template_id, association_id, direction):
    """Reorder a task within its bundle."""
    template = get_object_or_404(WorkTemplate, template_id=template_id)
    try:
        WorkTemplateService.reorder_in_bundle(template.pk, association_id, direction)
    except (NotFoundError, ValidationError) as e:
        messages.error(request, str(e))
    return redirect('estimates:work_template_detail', template_id=template_id)


@require_POST
def worksheet_reorder_item(request, worksheet_id, item_type, item_id, direction):
    """Reorder items at the container level within a worksheet."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)
    try:
        WorksheetService.reorder_items(worksheet.pk, item_type, item_id, direction)
    except (NotFoundError, ValidationError) as e:
        messages.error(request, str(e))
    return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)


@require_POST
def worksheet_reorder_in_bundle(request, worksheet_id, task_id, direction):
    """Reorder a task within its bundle on a worksheet."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)
    try:
        WorksheetService.reorder_in_bundle(worksheet.pk, task_id, direction)
    except (NotFoundError, ValidationError) as e:
        messages.error(request, str(e))
    return redirect('estimates:estworksheet_detail', worksheet_id=worksheet_id)


