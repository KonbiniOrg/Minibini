from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django import forms
from django.utils import timezone
from django.db import models
from django.views.decorators.http import require_POST
from .models import Job, Estimate, EstimateLineItem, Task, WorkOrder, WorkOrderTemplate, TaskTemplate, EstWorksheet, TemplateTaskAssociation
from apps.core.services import TaxCalculationService
from .forms import (
    JobCreateForm, JobEditForm, WorkOrderTemplateForm, TaskTemplateForm, EstWorksheetForm,
    TaskForm, TaskFromTemplateForm,
    ManualLineItemForm, PriceListLineItemForm, EstimateStatusForm, EstimateForm, WorkOrderStatusForm
)
from apps.purchasing.models import PurchaseOrder
from apps.invoicing.models import Invoice


def _build_task_hierarchy(tasks):
    """Build a hierarchical task structure with level indicators, preserving sort_order."""
    task_dict = {task.task_id: task for task in tasks}
    root_tasks = []

    # Find root tasks (no parent) and maintain sort_order
    for task in tasks:
        if not task.parent_task:
            root_tasks.append(task)

    # Sort root tasks by sort_order to ensure proper order
    root_tasks.sort(key=lambda t: t.sort_order if t.sort_order is not None else float('inf'))

    # Recursive function to get task with its children and level
    def get_task_with_children(task, level=0):
        result = {'task': task, 'level': level}
        children = []
        for potential_child in tasks:
            if potential_child.parent_task_id == task.task_id:
                children.append(potential_child)

        # Sort children by sort_order to ensure proper order
        children.sort(key=lambda t: t.sort_order if t.sort_order is not None else float('inf'))

        # Recursively build the tree for each child
        result['children'] = [get_task_with_children(child, level + 1) for child in children]
        return result

    # Build the tree
    tree = []
    for root_task in root_tasks:
        tree.append(get_task_with_children(root_task))

    # Flatten the tree for template display
    def flatten_tree(tree_nodes):
        flat_list = []
        for node in tree_nodes:
            flat_list.append({'task': node['task'], 'level': node['level']})
            if node['children']:
                flat_list.extend(flatten_tree(node['children']))
        return flat_list

    return flatten_tree(tree)


def job_list(request):
    from apps.contacts.models import Contact, Business
    from django.db.models import Case, When, Value, IntegerField
    from django.db.models.functions import Coalesce

    jobs = Job.objects.select_related('contact', 'contact__business').all()

    # Get filter parameters
    status_filters = request.GET.getlist('status')  # Multiple statuses allowed
    date_filter = request.GET.get('date_type', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    contact_filter = request.GET.get('contact', '')
    business_filter = request.GET.get('business', '')

    # Default to Draft and Approved if no status filters and no query string
    # (allows explicitly clearing all statuses via empty submission)
    using_default_statuses = False
    if not status_filters and not request.GET:
        status_filters = ['draft', 'approved']
        using_default_statuses = True

    # Track if any filters are applied (beyond defaults)
    filters_applied = any([date_from, date_to, contact_filter, business_filter]) or (status_filters and not using_default_statuses)

    # Apply status filter (multiple statuses with OR logic)
    if status_filters:
        jobs = jobs.filter(status__in=status_filters)

    # Apply date filter
    if date_filter and (date_from or date_to):
        date_field_map = {
            'created': 'created_date',
            'due': 'due_date',
            'completed': 'completed_date',
            'start': 'start_date',
        }
        date_field = date_field_map.get(date_filter, 'created_date')

        if date_from:
            jobs = jobs.filter(**{f'{date_field}__gte': date_from})
        if date_to:
            jobs = jobs.filter(**{f'{date_field}__lte': date_to})

    # Apply contact filter
    if contact_filter:
        jobs = jobs.filter(contact_id=contact_filter)

    # Apply business filter
    if business_filter:
        jobs = jobs.filter(contact__business_id=business_filter)

    # Custom status ordering: Draft (0) → Approved (1) → Completed (2) → Rejected (3) → Cancelled (4)
    status_order = Case(
        When(status='draft', then=Value(0)),
        When(status='approved', then=Value(1)),
        When(status='submitted', then=Value(2)),
        When(status='completed', then=Value(3)),
        When(status='rejected', then=Value(4)),
        When(status='cancelled', then=Value(5)),
        default=Value(6),
        output_field=IntegerField(),
    )

    # Sort by status order, then by start_date (falling back to created_date if no start_date)
    jobs = jobs.annotate(
        status_order=status_order,
        sort_date=Coalesce('start_date', 'created_date')
    ).order_by('status_order', '-sort_date')

    # Get all contacts and businesses for filter dropdowns
    contacts = Contact.objects.select_related('business').order_by('first_name', 'last_name')
    businesses = Business.objects.order_by('business_name')

    context = {
        'jobs': jobs,
        'contacts': contacts,
        'businesses': businesses,
        'status_choices': Job.JOB_STATUS_CHOICES,
        'current_filters': {
            'statuses': status_filters,  # List of selected statuses
            'date_type': date_filter,
            'date_from': date_from,
            'date_to': date_to,
            'contact': contact_filter,
            'business': business_filter,
        },
        'filters_applied': filters_applied,
    }
    return render(request, 'jobs/job_list.html', context)

def job_detail(request, job_id):
    job = get_object_or_404(Job, job_id=job_id)

    # Get current estimate (highest version, non-superseded)
    current_estimate = Estimate.objects.filter(job=job).exclude(status='superseded').order_by('-version').first()

    # Get superseded estimates
    superseded_estimates = Estimate.objects.filter(job=job, status='superseded').order_by('-version')

    # If there's a current estimate, get its line items and total
    current_estimate_line_items = []
    current_estimate_total = 0
    if current_estimate:
        current_estimate_line_items = EstimateLineItem.objects.filter(estimate=current_estimate).order_by('line_item_id')
        current_estimate_total = sum(item.total_amount for item in current_estimate_line_items)

    work_orders = WorkOrder.objects.filter(job=job).order_by('-work_order_id')
    worksheets = EstWorksheet.objects.filter(job=job).order_by('-created_date')
    purchase_orders = PurchaseOrder.objects.filter(job=job).order_by('-po_id')
    invoices = Invoice.objects.filter(job=job).order_by('-invoice_id')

    # Get current work order (most recent non-complete)
    current_work_order = work_orders.exclude(status='complete').first()
    current_work_order_tasks = []
    if current_work_order:
        all_tasks = Task.objects.filter(work_order=current_work_order).order_by('sort_order', 'task_id')
        current_work_order_tasks = _build_task_hierarchy(all_tasks)

    return render(request, 'jobs/job_detail.html', {
        'job': job,
        'current_estimate': current_estimate,
        'current_estimate_line_items': current_estimate_line_items,
        'current_estimate_total': current_estimate_total,
        'superseded_estimates': superseded_estimates,
        'work_orders': work_orders,
        'worksheets': worksheets,
        'purchase_orders': purchase_orders,
        'invoices': invoices
    })


def job_create(request):
    """Create a new Job"""
    initial_contact_id = request.GET.get('contact_id')
    initial_contact = None

    if initial_contact_id:
        try:
            from apps.contacts.models import Contact
            initial_contact = Contact.objects.get(contact_id=initial_contact_id)
        except Contact.DoesNotExist:
            pass

    if request.method == 'POST':
        form = JobCreateForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            # Job starts in 'draft' status by default (defined in model)
            job.save()
            messages.success(request, f'Job {job.job_number} created successfully.')
            return redirect('jobs:detail', job_id=job.job_id)
    else:
        form = JobCreateForm(initial_contact=initial_contact)

    return render(request, 'jobs/job_create.html', {
        'form': form,
        'initial_contact': initial_contact
    })


def job_edit(request, job_id):
    """Edit an existing Job with state-based field restrictions"""
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = JobEditForm(request.POST, instance=job)
        if form.is_valid():
            job = form.save()
            messages.success(request, f'Job {job.job_number} updated successfully.')
            return redirect('jobs:detail', job_id=job.job_id)
    else:
        form = JobEditForm(instance=job)

    return render(request, 'jobs/job_edit.html', {
        'form': form,
        'job': job
    })


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
                        estimate.status = new_status
                        estimate.save()
                        messages.success(request, f'Estimate status updated to {new_status.title()}')
                    except Exception as e:
                        messages.error(request, f'Error updating status: {str(e)}')
                return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
        else:
            messages.error(request, f'Cannot update status from {estimate.get_status_display()} (terminal state).')
            return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)

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
        'show_reorder': estimate.status == 'draft',
        'reorder_url_name': 'jobs:estimate_reorder_line_item',
        'parent_id': estimate.estimate_id
    })

def task_list(request):
    # Only show incomplete tasks with WorkOrders (not EstWorksheets)
    tasks = Task.objects.filter(
        work_order__isnull=False,
        est_worksheet__isnull=True
    ).exclude(
        work_order__status='complete'
    ).select_related('work_order', 'work_order__job', 'assignee').order_by('-task_id')
    return render(request, 'jobs/task_list.html', {'tasks': tasks})

def task_detail(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    return render(request, 'jobs/task_detail.html', {'task': task})

def work_order_list(request):
    work_orders = WorkOrder.objects.all().order_by('-work_order_id')
    return render(request, 'jobs/work_order_list.html', {'work_orders': work_orders})

def work_order_detail(request, work_order_id):
    work_order = get_object_or_404(WorkOrder, work_order_id=work_order_id)

    # Handle status update POST request
    if request.method == 'POST' and 'update_status' in request.POST:
        if work_order.status != 'complete':
            form = WorkOrderStatusForm(request.POST, current_status=work_order.status)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                if new_status != work_order.status:
                    work_order.status = new_status
                    work_order.save()
                    messages.success(request, f'Work Order status updated to {new_status.title()}')
            return redirect('jobs:work_order_detail', work_order_id=work_order.work_order_id)
        else:
            messages.error(request, 'Cannot update the status of a completed work order.')
            return redirect('jobs:work_order_detail', work_order_id=work_order.work_order_id)

    # Get all tasks for this work order
    all_tasks = Task.objects.filter(work_order=work_order).order_by('sort_order', 'task_id')
    tasks_with_levels = _build_task_hierarchy(all_tasks)

    # Create status form for display (unless completed)
    status_form = WorkOrderStatusForm(current_status=work_order.status) if work_order.status != 'complete' else None

    return render(request, 'jobs/work_order_detail.html', {
        'work_order': work_order,
        'tasks': tasks_with_levels,
        'status_form': status_form,
        'show_reorder': True,
        'reorder_url_name': 'jobs:task_reorder_work_order',
        'container_id': work_order.work_order_id
    })


def work_order_create_from_estimate(request, estimate_id):
    """Create a WorkOrder from an accepted Estimate"""
    from django.db import transaction

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # Only allow creation from accepted estimates
    if estimate.status != 'accepted':
        messages.error(request, 'Work Orders can only be created from accepted estimates.')
        return redirect('jobs:estimate_detail', estimate_id=estimate_id)

    if request.method == 'POST':
        with transaction.atomic():
            # Create the WorkOrder
            work_order = WorkOrder.objects.create(
                job=estimate.job,
                status='draft',
                template=None
            )

            # Generate tasks from all EstimateLineItems
            from .services import LineItemTaskService
            total_tasks = 0
            line_items = estimate.estimatelineitem_set.all().order_by('line_number', 'pk')

            for line_item in line_items:
                generated_tasks = LineItemTaskService.generate_tasks_for_work_order(line_item, work_order)
                total_tasks += len(generated_tasks)

            # If we have worksheet-based tasks, try to set template from worksheet
            worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
            if worksheet:
                work_order.template = worksheet.template
                work_order.save()

            messages.success(request, f'Work Order {work_order.work_order_id} created successfully from Estimate {estimate.estimate_number}.')
            return redirect('jobs:work_order_detail', work_order_id=work_order.work_order_id)

    # GET request - show confirmation page
    worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
    line_items = estimate.estimatelineitem_set.all().order_by('line_number', 'pk')

    # Categorize line items by source
    worksheet_items = []
    catalog_items = []
    manual_items = []

    for line_item in line_items:
        if line_item.task:
            worksheet_items.append(line_item)
        elif line_item.price_list_item:
            catalog_items.append(line_item)
        else:
            manual_items.append(line_item)

    return render(request, 'jobs/work_order_create_confirm.html', {
        'estimate': estimate,
        'worksheet': worksheet,
        'line_items': line_items,
        'worksheet_items': worksheet_items,
        'catalog_items': catalog_items,
        'manual_items': manual_items,
        'total_line_items': line_items.count()
    })


def add_work_order_template(request):
    if request.method == 'POST':
        form = WorkOrderTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            messages.success(request, f'Work Order Template "{template.template_name}" created successfully.')
            return redirect('jobs:work_order_template_detail', template_id=template.template_id)
    else:
        form = WorkOrderTemplateForm()

    return render(request, 'jobs/add_work_order_template.html', {'form': form})


def work_order_template_edit(request, template_id):
    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)

    if request.method == 'POST':
        form = WorkOrderTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f'Work Order Template "{template.template_name}" updated successfully.')
            return redirect('jobs:work_order_template_detail', template_id=template.template_id)
    else:
        form = WorkOrderTemplateForm(instance=template)

    return render(request, 'jobs/work_order_template_edit.html', {
        'form': form,
        'template': template
    })


@require_POST
def work_order_template_delete(request, template_id):
    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)
    template_name = template.template_name
    template.delete()
    messages.success(request, f'Work Order Template "{template_name}" deleted successfully.')
    return redirect('jobs:work_order_template_list')


def work_order_template_list(request):
    templates = WorkOrderTemplate.objects.all().order_by('-created_date')
    return render(request, 'jobs/work_order_template_list.html', {'templates': templates})


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
                    'line_item_type_name': assoc.bundle.line_item_type.name,
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
        work_order_template=template, bundle__isnull=True
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    max_bundle = TemplateBundle.objects.filter(
        work_order_template=template
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    return max(max_assoc, max_bundle) + 1


def work_order_template_detail(request, template_id):
    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)
    
    # Handle TaskTemplate association
    if request.method == 'POST' and 'associate_task' in request.POST:
        task_template_id = request.POST.get('task_template_id')
        est_qty = request.POST.get('est_qty', '1.00')
        if task_template_id:
            from .models import TemplateTaskAssociation
            task_template = get_object_or_404(TaskTemplate, template_id=task_template_id)

            next_sort_order = _next_container_sort_order(template)

            association, created = TemplateTaskAssociation.objects.get_or_create(
                work_order_template=template,
                task_template=task_template,
                defaults={'est_qty': est_qty, 'sort_order': next_sort_order}
            )
            if created:
                messages.success(request, f'Task Template "{task_template.template_name}" associated with quantity {est_qty}.')
            else:
                messages.warning(request, f'Task Template "{task_template.template_name}" is already associated.')
        return redirect('jobs:work_order_template_detail', template_id=template_id)
    
    # Handle TaskTemplate removal (unbundle if bundled, delete if unbundled)
    if request.method == 'POST' and 'remove_task' in request.POST:
        task_template_id = request.POST.get('remove_task')
        if task_template_id:
            from .models import TemplateTaskAssociation, TemplateBundle
            task_template = get_object_or_404(TaskTemplate, template_id=task_template_id)
            assoc = TemplateTaskAssociation.objects.filter(
                work_order_template=template,
                task_template=task_template
            ).first()
            if assoc and assoc.mapping_strategy == 'bundle' and assoc.bundle:
                # Unbundle: place just after the bundle in container-level ordering
                bundle = assoc.bundle
                insert_point = bundle.sort_order + 1

                # Bump container-level items at >= insert_point to make room
                TemplateTaskAssociation.objects.filter(
                    work_order_template=template, bundle__isnull=True,
                    sort_order__gte=insert_point
                ).update(sort_order=models.F('sort_order') + 1)
                TemplateBundle.objects.filter(
                    work_order_template=template, sort_order__gte=insert_point
                ).update(sort_order=models.F('sort_order') + 1)

                assoc.mapping_strategy = 'direct'
                assoc.bundle = None
                assoc.sort_order = insert_point
                assoc.save()
                # Clean up: dissolve bundle if 0 or 1 tasks remain
                remaining = TemplateTaskAssociation.objects.filter(bundle=bundle)
                if remaining.count() == 0:
                    bundle.delete()
                    messages.success(request, f'"{task_template.template_name}" unbundled. Bundle "{bundle.name}" removed (empty).')
                elif remaining.count() == 1:
                    # Auto-unbundle the last task
                    last_assoc = remaining.first()
                    last_assoc.mapping_strategy = 'direct'
                    last_assoc.sort_order = bundle.sort_order
                    last_assoc.bundle = None
                    last_assoc.save()
                    bundle.delete()
                    messages.success(request, f'"{task_template.template_name}" unbundled. Bundle "{bundle.name}" dissolved (only 1 task remained).')
                else:
                    messages.success(request, f'"{task_template.template_name}" removed from bundle "{bundle.name}".')
            elif assoc:
                assoc.delete()
                messages.success(request, f'Task Template "{task_template.template_name}" removed.')
        return redirect('jobs:work_order_template_detail', template_id=template_id)

    # Handle bundle creation
    if request.method == 'POST' and 'bundle_tasks' in request.POST:
        from .models import TemplateTaskAssociation, TemplateBundle
        from apps.core.models import LineItemType

        # Get selected association IDs
        selected_ids = request.POST.getlist('selected_tasks')
        bundle_name = request.POST.get('bundle_name', '').strip()
        bundle_description = request.POST.get('bundle_description', '').strip()
        line_item_type_id = request.POST.get('line_item_type')

        if len(selected_ids) < 2:
            messages.error(request, 'Please select at least 2 tasks to bundle.')
        elif not bundle_name:
            messages.error(request, 'Bundle name is required.')
        elif not line_item_type_id:
            messages.error(request, 'Line item type is required.')
        else:
            line_item_type = get_object_or_404(LineItemType, pk=line_item_type_id)

            # Use existing bundle if name matches, otherwise create new
            bundle, created = TemplateBundle.objects.get_or_create(
                work_order_template=template,
                name=bundle_name,
                defaults={
                    'description': bundle_description,
                    'line_item_type': line_item_type,
                    'sort_order': _next_container_sort_order(template),
                }
            )

            # Update selected associations and assign sequential within-bundle sort_order
            selected_assocs = TemplateTaskAssociation.objects.filter(
                pk__in=selected_ids,
                work_order_template=template
            ).order_by('sort_order', 'pk')

            # Find the current max sort_order within the bundle (for adding to existing)
            existing_max = TemplateTaskAssociation.objects.filter(
                bundle=bundle
            ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0

            for i, assoc in enumerate(selected_assocs, start=existing_max + 1):
                assoc.mapping_strategy = 'bundle'
                assoc.bundle = bundle
                assoc.sort_order = i
                assoc.save()

            updated = selected_assocs.count()

            # Check if any other bundles were reduced to 1 or 0 tasks
            for other_bundle in TemplateBundle.objects.filter(work_order_template=template).exclude(pk=bundle.pk):
                remaining = TemplateTaskAssociation.objects.filter(bundle=other_bundle)
                if remaining.count() == 0:
                    other_bundle.delete()
                elif remaining.count() == 1:
                    # Auto-unbundle the last task
                    last_assoc = remaining.first()
                    last_assoc.mapping_strategy = 'direct'
                    last_assoc.sort_order = other_bundle.sort_order
                    last_assoc.bundle = None
                    last_assoc.save()
                    other_bundle.delete()

            if created:
                messages.success(request, f'Bundle "{bundle_name}" created with {updated} tasks.')
            else:
                messages.success(request, f'{updated} tasks added to existing bundle "{bundle_name}".')

        return redirect('jobs:work_order_template_detail', template_id=template_id)

    # Get task template associations with bundle info
    from .models import TemplateTaskAssociation, TemplateBundle
    from apps.core.models import LineItemType

    associations = TemplateTaskAssociation.objects.filter(
        work_order_template=template,
        task_template__is_active=True
    ).select_related('task_template', 'bundle').order_by('sort_order', 'task_template__template_name')

    # Build normalized container_items for shared _bundle_table.html partial
    container_items = _build_container_items_from_associations(associations)

    # Get available task templates (not yet associated)
    associated_task_ids = associations.values_list('task_template_id', flat=True)
    available_templates = TaskTemplate.objects.filter(is_active=True).exclude(template_id__in=associated_task_ids)

    # Get line item types for bundle form
    line_item_types = LineItemType.objects.all().order_by('name')

    return render(request, 'jobs/work_order_template_detail.html', {
        'template': template,
        'container_items': container_items,
        'available_templates': available_templates,
        'line_item_types': line_item_types,
        'can_edit': True,
        'reorder_container_url': 'jobs:template_reorder_item',
        'reorder_in_bundle_url': 'jobs:template_reorder_in_bundle',
        'container_id': template.template_id,
    })


def estworksheet_list(request):
    """List all EstWorksheets"""
    worksheets = EstWorksheet.objects.select_related('job', 'estimate').order_by('-created_date')
    return render(request, 'jobs/estworksheet_list.html', {'worksheets': worksheets})


def _build_container_items_from_tasks(worksheet):
    """Normalize worksheet Tasks/TaskBundles into the shared container_items format."""
    tasks = Task.objects.filter(
        est_worksheet=worksheet
    ).select_related('template', 'bundle').order_by('sort_order', 'task_id')

    bundles_by_id = {}
    unbundled = []

    for task in tasks:
        item = {
            'id': task.task_id,
            'name': task.name,
            'description': task.template.description if task.template else '',
            'units': task.units,
            'rate': task.rate,
            'est_qty': task.est_qty,
            'mapping_strategy': task.mapping_strategy,
            'remove_id': task.task_id,
            'sort_order': task.sort_order or 0,
        }
        if task.mapping_strategy == 'bundle' and task.bundle:
            bid = task.bundle_id
            if bid not in bundles_by_id:
                bundles_by_id[bid] = {
                    'id': bid,
                    'name': task.bundle.name,
                    'line_item_type_name': task.bundle.line_item_type.name,
                    'sort_order': task.bundle.sort_order,
                    'items': [],
                }
            bundles_by_id[bid]['items'].append(item)
        else:
            unbundled.append((task.sort_order or 0, item))

    for bundle_data in bundles_by_id.values():
        bundle_data['items'].sort(key=lambda i: i['sort_order'])

    container_items = []
    for sort_order, item in unbundled:
        container_items.append(('task', item, sort_order))
    for bundle_data in bundles_by_id.values():
        container_items.append(('bundle', bundle_data, bundle_data['sort_order']))
    container_items.sort(key=lambda x: x[2])
    return container_items


def _next_worksheet_sort_order(worksheet):
    """Get the next sort_order in the shared container-level space for a worksheet."""
    from .models import TaskBundle
    max_task = Task.objects.filter(
        est_worksheet=worksheet, bundle__isnull=True
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    max_bundle = TaskBundle.objects.filter(
        est_worksheet=worksheet
    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
    return max(max_task, max_bundle) + 1


def estworksheet_detail(request, worksheet_id):
    """Show details of a specific EstWorksheet with its tasks and bundle editing."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)
    can_edit = worksheet.status == 'draft'

    # Handle bundle creation
    if request.method == 'POST' and 'bundle_tasks' in request.POST and can_edit:
        from .models import TaskBundle
        from apps.core.models import LineItemType

        selected_ids = request.POST.getlist('selected_tasks')
        bundle_name = request.POST.get('bundle_name', '').strip()
        bundle_description = request.POST.get('bundle_description', '').strip()
        line_item_type_id = request.POST.get('line_item_type')

        if len(selected_ids) < 2:
            messages.error(request, 'Please select at least 2 tasks to bundle.')
        elif not bundle_name:
            messages.error(request, 'Bundle name is required.')
        elif not line_item_type_id:
            messages.error(request, 'Line item type is required.')
        else:
            line_item_type = get_object_or_404(LineItemType, pk=line_item_type_id)

            bundle, created = TaskBundle.objects.get_or_create(
                est_worksheet=worksheet,
                name=bundle_name,
                defaults={
                    'description': bundle_description,
                    'line_item_type': line_item_type,
                    'sort_order': _next_worksheet_sort_order(worksheet),
                }
            )

            selected_tasks = Task.objects.filter(
                task_id__in=selected_ids, est_worksheet=worksheet
            ).order_by('sort_order', 'task_id')

            for i, task in enumerate(selected_tasks, start=1):
                task.mapping_strategy = 'bundle'
                task.bundle = bundle
                task.sort_order = i  # Within-bundle position
                task.save()

            # Auto-dissolve other bundles reduced to 0 or 1 tasks
            for other_bundle in TaskBundle.objects.filter(est_worksheet=worksheet).exclude(pk=bundle.pk):
                remaining = Task.objects.filter(bundle=other_bundle)
                if remaining.count() == 0:
                    other_bundle.delete()
                elif remaining.count() == 1:
                    last_task = remaining.first()
                    last_task.mapping_strategy = 'direct'
                    last_task.sort_order = other_bundle.sort_order
                    last_task.bundle = None
                    last_task.save()
                    other_bundle.delete()

            if created:
                messages.success(request, f'Bundle "{bundle_name}" created with {selected_tasks.count()} tasks.')
            else:
                messages.success(request, f'{selected_tasks.count()} tasks added to existing bundle "{bundle_name}".')

        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Handle unbundle / remove
    if request.method == 'POST' and 'remove_task' in request.POST and can_edit:
        from .models import TaskBundle
        task_id = request.POST.get('remove_task')
        task = get_object_or_404(Task, task_id=task_id, est_worksheet=worksheet)

        if task.mapping_strategy == 'bundle' and task.bundle:
            bundle = task.bundle
            insert_point = bundle.sort_order + 1

            # Bump container-level items at >= insert_point to make room
            Task.objects.filter(
                est_worksheet=worksheet, bundle__isnull=True,
                sort_order__gte=insert_point
            ).update(sort_order=models.F('sort_order') + 1)
            TaskBundle.objects.filter(
                est_worksheet=worksheet, sort_order__gte=insert_point
            ).update(sort_order=models.F('sort_order') + 1)

            task.mapping_strategy = 'direct'
            task.bundle = None
            task.sort_order = insert_point
            task.save()

            remaining = Task.objects.filter(bundle=bundle)
            if remaining.count() == 0:
                bundle.delete()
                messages.success(request, f'"{task.name}" unbundled. Bundle "{bundle.name}" removed (empty).')
            elif remaining.count() == 1:
                last_task = remaining.first()
                last_task.mapping_strategy = 'direct'
                last_task.sort_order = bundle.sort_order
                last_task.bundle = None
                last_task.save()
                bundle.delete()
                messages.success(request, f'"{task.name}" unbundled. Bundle "{bundle.name}" dissolved (only 1 task remained).')
            else:
                messages.success(request, f'"{task.name}" removed from bundle "{bundle.name}".')
        else:
            messages.info(request, f'Task "{task.name}" is not bundled.')

        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Build context
    from apps.core.models import LineItemType

    container_items = _build_container_items_from_tasks(worksheet)
    line_item_types = LineItemType.objects.all().order_by('name')

    # Calculate total cost from all tasks
    all_tasks = Task.objects.filter(est_worksheet=worksheet)
    total_cost = sum(
        (t.rate * t.est_qty) for t in all_tasks if t.rate and t.est_qty
    )

    return render(request, 'jobs/estworksheet_detail.html', {
        'worksheet': worksheet,
        'container_items': container_items,
        'line_item_types': line_item_types,
        'total_cost': total_cost,
        'can_edit': can_edit,
        'reorder_container_url': 'jobs:worksheet_reorder_item',
        'reorder_in_bundle_url': 'jobs:worksheet_reorder_in_bundle',
        'container_id': worksheet.est_worksheet_id,
    })


def estworksheet_generate_estimate(request, worksheet_id):
    """Generate an estimate from a worksheet using EstimateGenerationService"""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    # Prevent generating estimates from non-draft worksheets
    if worksheet.status != 'draft':
        messages.error(request, f'Cannot generate estimate from a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    if request.method == 'POST':
        try:
            from .services import EstimateGenerationService
            service = EstimateGenerationService()
            estimate = service.generate_estimate_from_worksheet(worksheet)

            # Mark worksheet as final after generating estimate
            worksheet.status = 'final'
            worksheet.save()

            messages.success(request, f'Estimate {estimate.estimate_number} generated successfully!')
            return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
            
        except Exception as e:
            messages.error(request, f'Error generating estimate: {str(e)}')
            return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)
    
    # Show confirmation page
    tasks = Task.objects.filter(est_worksheet=worksheet).select_related(
        'template'
    )
    total_cost = sum(task.rate * task.est_qty for task in tasks if task.rate and task.est_qty)
    
    return render(request, 'jobs/estworksheet_generate_estimate.html', {
        'worksheet': worksheet,
        'tasks': tasks,
        'total_cost': total_cost
    })


def estimate_mark_open(request, estimate_id):
    """Mark an estimate as Open and update associated worksheet to Final"""
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    if request.method == 'POST':
        if estimate.status == 'draft':
            # Mark estimate as open
            estimate.status = 'open'
            estimate.save()

            # Update associated worksheet to final if exists
            worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
            if worksheet and worksheet.status == 'draft':
                worksheet.status = 'final'
                worksheet.save()

            messages.success(request, f'Estimate {estimate.estimate_number} marked as Open')
        else:
            messages.warning(request, 'Only Draft estimates can be marked as Open')

    return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)


def estworksheet_revise(request, worksheet_id):
    """Create a new revision of a worksheet"""
    parent_worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    if request.method == 'POST':
        if parent_worksheet.status != 'draft':
            # Create new draft worksheet
            new_worksheet = EstWorksheet.objects.create(
                job=parent_worksheet.job,
                parent=parent_worksheet,
                status='draft',
                version=parent_worksheet.version + 1
            )

            # Copy tasks from parent to new worksheet
            parent_tasks = Task.objects.filter(est_worksheet=parent_worksheet)
            for task in parent_tasks:
                Task.objects.create(
                    name=task.name,
                    template=task.template,
                    est_worksheet=new_worksheet,
                    est_qty=task.est_qty,
                    units=task.units,
                    rate=task.rate
                )

            # Mark parent as superseded and increment version
            parent_worksheet.status = 'superseded'
            parent_worksheet.save()

            messages.success(request, f'New worksheet revision created (v{new_worksheet.version})')
            return redirect('jobs:estworksheet_detail', worksheet_id=new_worksheet.est_worksheet_id)
        else:
            messages.warning(request, 'Cannot revise a Draft worksheet')

    return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)


def task_template_list(request):
    """List all TaskTemplates with all fields"""
    templates = TaskTemplate.objects.all().prefetch_related('work_order_templates').order_by('template_name')
    return render(request, 'jobs/task_template_list.html', {'templates': templates})


def add_task_template_standalone(request):
    """Create a new TaskTemplate independently"""
    if request.method == 'POST':
        form = TaskTemplateForm(request.POST)
        if form.is_valid():
            task_template = form.save()
            messages.success(request, f'Task Template "{task_template.template_name}" created successfully.')
            return redirect('jobs:task_template_list')
    else:
        form = TaskTemplateForm()

    return render(request, 'jobs/add_task_template_standalone.html', {'form': form})


def task_template_edit(request, template_id):
    """Edit an existing TaskTemplate."""
    template = get_object_or_404(TaskTemplate, template_id=template_id)

    if request.method == 'POST':
        form = TaskTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task Template "{template.template_name}" updated successfully.')
            return redirect('jobs:task_template_list')
    else:
        form = TaskTemplateForm(instance=template)

    # Get WorkOrderTemplates using this TaskTemplate
    work_order_templates = WorkOrderTemplate.objects.filter(
        templatetaskassociation__task_template=template
    ).distinct()

    return render(request, 'jobs/task_template_edit.html', {
        'form': form,
        'template': template,
        'work_order_templates': work_order_templates,
        'can_delete': not work_order_templates.exists()
    })


@require_POST
def task_template_delete(request, template_id):
    """Delete a TaskTemplate."""
    template = get_object_or_404(TaskTemplate, template_id=template_id)

    # Check if template is used in any WorkOrderTemplate
    if TemplateTaskAssociation.objects.filter(task_template=template).exists():
        messages.error(request, f'Task Template "{template.template_name}" cannot be deleted because it is used in one or more Work Order Templates.')
        return redirect('jobs:task_template_edit', template_id=template_id)

    template_name = template.template_name
    template.delete()
    messages.success(request, f'Task Template "{template_name}" deleted successfully.')
    return redirect('jobs:task_template_list')


def estworksheet_create_for_job(request, job_id):
    """Create a new EstWorksheet for a specific Job, optionally from a template"""
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = EstWorksheetForm(request.POST, initial={'job': job})
        if form.is_valid():
            worksheet = form.save(commit=False)
            worksheet.job = job  # Ensure job is set
            worksheet.save()

            # If a template was selected, generate tasks (and bundles) from it
            template = form.cleaned_data.get('template')
            if template:
                template.generate_tasks_for_worksheet(worksheet)
                messages.success(request, f'Worksheet created from template "{template.template_name}" for Job {job.job_number}')
            else:
                messages.success(request, f'Worksheet created successfully for Job {job.job_number}')

            return redirect('jobs:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
    else:
        form = EstWorksheetForm(initial={'job': job})
        # Hide the job field since it's already set
        form.fields['job'].widget = forms.HiddenInput()

    return render(request, 'jobs/estworksheet_create_for_job.html', {
        'form': form,
        'job': job
    })


# Removed estworksheet_create_from_template - functionality merged into estworksheet_create_for_job


def task_add_from_template(request, worksheet_id):
    """Add Task to EstWorksheet from TaskTemplate"""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    # Prevent adding tasks to non-draft worksheets
    if worksheet.status != 'draft':
        messages.error(request, f'Cannot add tasks to a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    if request.method == 'POST':
        form = TaskFromTemplateForm(request.POST)
        if form.is_valid():
            template = form.cleaned_data['template']
            est_qty = form.cleaned_data['est_qty']

            task = Task.objects.create(
                name=template.template_name,
                template=template,
                est_worksheet=worksheet,
                est_qty=est_qty,
                units=template.units,
                rate=template.rate
            )

            messages.success(request, f'Task "{task.name}" added from template')
            return redirect('jobs:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
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
    if worksheet.status != 'draft':
        messages.error(request, f'Cannot add tasks to a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.est_worksheet = worksheet
            task.save()

            messages.success(request, f'Task "{task.name}" added manually')
            return redirect('jobs:estworksheet_detail', worksheet_id=worksheet.est_worksheet_id)
    else:
        form = TaskForm(initial={'est_worksheet': worksheet})
        # Hide the worksheet field since it's already set
        form.fields['est_worksheet'].widget = forms.HiddenInput()
        # Hide the template field since user chose to add manually
        form.fields['template'].widget = forms.HiddenInput()

    return render(request, 'jobs/task_add_manual.html', {
        'form': form,
        'worksheet': worksheet
    })


def estimate_delete_line_item(request, estimate_id, line_item_id):
    """Delete a line item from an estimate and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    line_item = get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    if request.method == 'POST':
        try:
            # Use the service to delete and renumber
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)

    # GET request - show confirmation (optional, can skip for simple delete)
    return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)


def estimate_add_line_item(request, estimate_id):
    """Add line item to Estimate - either manually or from Price List"""
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # Prevent modifications to non-draft estimates
    if estimate.status != 'draft':
        messages.error(request, f'Cannot add line items to a {estimate.get_status_display().lower()} estimate. Only draft estimates can be modified.')
        return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)

    if request.method == 'POST':
        # Determine which form was submitted
        if 'manual_submit' in request.POST:
            # Manual line item form submitted
            manual_form = ManualLineItemForm(request.POST)
            if manual_form.is_valid():
                line_item = manual_form.save(commit=False)
                line_item.estimate = estimate
                line_item.save()

                messages.success(request, f'Line item "{line_item.description}" added')
                return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
            else:
                # Manual form has errors, create empty price list form
                pricelist_form = PriceListLineItemForm()

        elif 'pricelist_submit' in request.POST:
            # Price list line item form submitted
            pricelist_form = PriceListLineItemForm(request.POST)
            if pricelist_form.is_valid():
                price_list_item = pricelist_form.cleaned_data['price_list_item']
                qty = pricelist_form.cleaned_data['qty']

                # Create line item from price list item
                line_item = EstimateLineItem.objects.create(
                    estimate=estimate,
                    price_list_item=price_list_item,
                    description=price_list_item.description,
                    qty=qty,
                    units=price_list_item.units,
                    price=price_list_item.selling_price,
                    line_item_type=price_list_item.line_item_type
                )

                messages.success(request, f'Line item "{line_item.description}" added from price list')
                return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
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
    if estimate.status == 'superseded':
        messages.error(request, 'Cannot update the status of a superseded estimate.')
        return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)

    if request.method == 'POST':
        form = EstimateStatusForm(request.POST, current_status=estimate.status)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            if new_status != estimate.status:
                estimate.status = new_status
                estimate.save()
                messages.success(request, f'Estimate status updated to {new_status.title()}')
            return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
    else:
        form = EstimateStatusForm(current_status=estimate.status)

    return render(request, 'jobs/estimate_update_status.html', {
        'form': form,
        'estimate': estimate
    })


def estimate_create_for_job(request, job_id):
    """Create a new Estimate for a specific Job - creates directly with defaults"""
    from apps.core.services import NumberGenerationService

    job = get_object_or_404(Job, job_id=job_id)

    # Check if an estimate already exists for this job
    existing_estimate = Estimate.objects.filter(job=job).exclude(status='superseded').first()
    if existing_estimate:
        if existing_estimate.status == 'draft':
            # Redirect to existing draft estimate for editing
            messages.info(request, f'A draft estimate already exists for this job. You can edit it here.')
            return redirect('jobs:estimate_detail', estimate_id=existing_estimate.estimate_id)
        else:
            # For non-draft estimates, user must use revise functionality
            messages.error(request, f'An estimate already exists for this job. Use the Revise option to create a new version.')
            return redirect('jobs:estimate_detail', estimate_id=existing_estimate.estimate_id)

    # Create estimate directly with defaults
    estimate = Estimate.objects.create(
        job=job,
        estimate_number=NumberGenerationService.generate_next_number('estimate'),
        version=1,
        status='draft'
    )

    messages.success(request, f'Estimate {estimate.estimate_number} (v{estimate.version}) created successfully')
    return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)


def estimate_revise(request, estimate_id):
    """Create a new revision of an estimate"""
    parent_estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    if request.method == 'POST':
        if parent_estimate.status != 'draft':
            # Create new draft estimate
            new_estimate = Estimate.objects.create(
                job=parent_estimate.job,
                estimate_number=parent_estimate.estimate_number,
                version=parent_estimate.version + 1,
                status='draft',
                parent=parent_estimate
            )

            # Copy line items from parent to new estimate
            parent_line_items = EstimateLineItem.objects.filter(estimate=parent_estimate)
            for line_item in parent_line_items:
                EstimateLineItem.objects.create(
                    estimate=new_estimate,
                    task=line_item.task,
                    price_list_item=line_item.price_list_item,
                    qty=line_item.qty,
                    units=line_item.units,
                    description=line_item.description,
                    price=line_item.price,
                    line_item_type=line_item.line_item_type,
                )

            # Mark parent as superseded (closed_date is set automatically by model.save())
            parent_estimate.status = 'superseded'
            parent_estimate.save()

            messages.success(request, f'Created new revision of estimate {new_estimate.estimate_number} (v{new_estimate.version})')
            return redirect('jobs:estimate_detail', estimate_id=new_estimate.estimate_id)
        else:
            messages.info(request, 'Cannot revise a draft estimate. Please edit it directly.')
            return redirect('jobs:estimate_detail', estimate_id=parent_estimate.estimate_id)

    return render(request, 'jobs/estimate_revise_confirm.html', {
        'estimate': parent_estimate
    })


@require_POST
def task_reorder_worksheet(request, worksheet_id, task_id, direction):
    """Reorder tasks within an EstWorksheet by swapping line numbers."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)
    task = get_object_or_404(Task, task_id=task_id, est_worksheet=worksheet)

    # Prevent reordering non-draft worksheets
    if worksheet.status != 'draft':
        messages.error(request, f'Cannot reorder tasks in a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Get all tasks for this worksheet ordered by sort_order
    all_tasks = list(Task.objects.filter(est_worksheet=worksheet).order_by('sort_order', 'task_id'))

    # Find the index of the current task
    try:
        current_index = next(i for i, t in enumerate(all_tasks) if t.task_id == task.task_id)
    except StopIteration:
        messages.error(request, 'Task not found in worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Determine the swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(all_tasks) - 1:
        swap_index = current_index + 1
    else:
        messages.error(request, 'Cannot move task in that direction.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Swap sort_order
    current_task = all_tasks[current_index]
    swap_task = all_tasks[swap_index]
    current_task.sort_order, swap_task.sort_order = swap_task.sort_order, current_task.sort_order

    current_task.save()
    swap_task.save()

    return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)


@require_POST
def task_reorder_work_order(request, work_order_id, task_id, direction):
    """Reorder tasks within a WorkOrder by swapping line numbers."""
    work_order = get_object_or_404(WorkOrder, work_order_id=work_order_id)
    task = get_object_or_404(Task, task_id=task_id, work_order=work_order)

    # Get all tasks for this work order ordered by sort_order
    all_tasks = list(Task.objects.filter(work_order=work_order).order_by('sort_order', 'task_id'))

    # Find the index of the current task
    try:
        current_index = next(i for i, t in enumerate(all_tasks) if t.task_id == task.task_id)
    except StopIteration:
        messages.error(request, 'Task not found in work order.')
        return redirect('jobs:work_order_detail', work_order_id=work_order_id)

    # Determine the swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(all_tasks) - 1:
        swap_index = current_index + 1
    else:
        messages.error(request, 'Cannot move task in that direction.')
        return redirect('jobs:work_order_detail', work_order_id=work_order_id)

    # Swap sort_order
    current_task = all_tasks[current_index]
    swap_task = all_tasks[swap_index]
    current_task.sort_order, swap_task.sort_order = swap_task.sort_order, current_task.sort_order

    current_task.save()
    swap_task.save()

    return redirect('jobs:work_order_detail', work_order_id=work_order_id)


@require_POST
def estimate_reorder_line_item(request, estimate_id, line_item_id, direction):
    """Reorder line items within an Estimate by swapping line numbers."""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    line_item = get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    try:
        # Use the service to reorder
        LineItemService.reorder_line_item(line_item, direction)
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect('jobs:estimate_detail', estimate_id=estimate_id)


@require_POST
def template_reorder_item(request, template_id, item_type, item_id, direction):
    """Reorder items at the container level within a WorkOrderTemplate.

    Bundles and unbundled associations share the same sort_order space.
    item_type is 'bundle' or 'task' (for unbundled TemplateTaskAssociation).
    """
    from .models import TemplateTaskAssociation, TemplateBundle

    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)

    # Build the container-level list: unbundled associations + bundles
    associations = TemplateTaskAssociation.objects.filter(
        work_order_template=template,
    ).select_related('bundle')

    container_items = []  # (sort_order, item_type, object)
    seen_bundles = set()

    for assoc in associations:
        if assoc.mapping_strategy == 'bundle' and assoc.bundle:
            if assoc.bundle.pk not in seen_bundles:
                seen_bundles.add(assoc.bundle.pk)
                container_items.append((assoc.bundle.sort_order, 'bundle', assoc.bundle))
        else:
            container_items.append((assoc.sort_order, 'task', assoc))

    container_items.sort(key=lambda x: x[0])

    # Find the item being moved
    current_index = None
    for i, (_, itype, obj) in enumerate(container_items):
        if itype == item_type:
            if item_type == 'bundle' and obj.pk == item_id:
                current_index = i
                break
            elif item_type == 'task' and obj.pk == item_id:
                current_index = i
                break

    if current_index is None:
        messages.error(request, 'Item not found.')
        return redirect('jobs:work_order_template_detail', template_id=template_id)

    # Determine swap target
    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(container_items) - 1:
        swap_index = current_index + 1
    else:
        return redirect('jobs:work_order_template_detail', template_id=template_id)

    # Swap sort_order values
    _, _, current_obj = container_items[current_index]
    _, _, swap_obj = container_items[swap_index]

    current_obj.sort_order, swap_obj.sort_order = swap_obj.sort_order, current_obj.sort_order
    current_obj.save()
    swap_obj.save()

    return redirect('jobs:work_order_template_detail', template_id=template_id)


@require_POST
def template_reorder_in_bundle(request, template_id, association_id, direction):
    """Reorder a task within its bundle."""
    from .models import TemplateTaskAssociation

    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)
    assoc = get_object_or_404(
        TemplateTaskAssociation,
        pk=association_id,
        work_order_template=template,
        mapping_strategy='bundle',
        bundle__isnull=False
    )

    # Get all associations in this bundle, ordered by sort_order
    bundle_assocs = list(
        TemplateTaskAssociation.objects.filter(
            bundle=assoc.bundle
        ).order_by('sort_order', 'pk')
    )

    current_index = None
    for i, a in enumerate(bundle_assocs):
        if a.pk == assoc.pk:
            current_index = i
            break

    if current_index is None:
        return redirect('jobs:work_order_template_detail', template_id=template_id)

    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(bundle_assocs) - 1:
        swap_index = current_index + 1
    else:
        return redirect('jobs:work_order_template_detail', template_id=template_id)

    # Swap sort_order values
    current = bundle_assocs[current_index]
    swap = bundle_assocs[swap_index]
    current.sort_order, swap.sort_order = swap.sort_order, current.sort_order
    current.save()
    swap.save()

    return redirect('jobs:work_order_template_detail', template_id=template_id)


@require_POST
def worksheet_reorder_item(request, worksheet_id, item_type, item_id, direction):
    """Reorder items at the container level within a worksheet.

    Bundles and unbundled tasks share the same sort_order space.
    item_type is 'bundle' or 'task'.
    """
    from .models import TaskBundle

    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    if worksheet.status != 'draft':
        messages.error(request, f'Cannot reorder in a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    # Build container-level list: unbundled tasks + bundles
    tasks = Task.objects.filter(est_worksheet=worksheet).select_related('bundle')

    container_items = []  # (sort_order, item_type, object)
    seen_bundles = set()

    for task in tasks:
        if task.mapping_strategy == 'bundle' and task.bundle:
            if task.bundle_id not in seen_bundles:
                seen_bundles.add(task.bundle_id)
                container_items.append((task.bundle.sort_order, 'bundle', task.bundle))
        else:
            container_items.append((task.sort_order or 0, 'task', task))

    container_items.sort(key=lambda x: x[0])

    # Find the item being moved
    current_index = None
    for i, (_, itype, obj) in enumerate(container_items):
        if itype == item_type and obj.pk == item_id:
            current_index = i
            break

    if current_index is None:
        messages.error(request, 'Item not found.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(container_items) - 1:
        swap_index = current_index + 1
    else:
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    _, _, current_obj = container_items[current_index]
    _, _, swap_obj = container_items[swap_index]

    current_obj.sort_order, swap_obj.sort_order = swap_obj.sort_order, current_obj.sort_order
    current_obj.save()
    swap_obj.save()

    return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)


@require_POST
def worksheet_reorder_in_bundle(request, worksheet_id, task_id, direction):
    """Reorder a task within its bundle on a worksheet."""
    worksheet = get_object_or_404(EstWorksheet, est_worksheet_id=worksheet_id)

    if worksheet.status != 'draft':
        messages.error(request, f'Cannot reorder in a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    task = get_object_or_404(
        Task, task_id=task_id, est_worksheet=worksheet,
        mapping_strategy='bundle', bundle__isnull=False
    )

    bundle_tasks = list(
        Task.objects.filter(bundle=task.bundle).order_by('sort_order', 'task_id')
    )

    current_index = None
    for i, t in enumerate(bundle_tasks):
        if t.task_id == task.task_id:
            current_index = i
            break

    if current_index is None:
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    if direction == 'up' and current_index > 0:
        swap_index = current_index - 1
    elif direction == 'down' and current_index < len(bundle_tasks) - 1:
        swap_index = current_index + 1
    else:
        return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

    current = bundle_tasks[current_index]
    swap = bundle_tasks[swap_index]
    current.sort_order, swap.sort_order = swap.sort_order, current.sort_order
    current.save()
    swap.save()

    return redirect('jobs:estworksheet_detail', worksheet_id=worksheet_id)

