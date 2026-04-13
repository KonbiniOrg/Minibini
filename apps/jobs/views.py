from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse
from django import forms
from django.utils import timezone
from django.db import models
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from .models import Job, Task, PlanTask, Blep
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.core.services import TaxCalculationService, NotFoundError
from .services import JobService, TaskService
from apps.inventory.services import InventoryService
from .forms import (
    JobCreateForm, JobEditForm,
    TaskEditForm, WorkOrderStatusForm,
    MaterialForm
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


@login_required
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
        status_filters = [Job.STATUS_DRAFT, Job.STATUS_APPROVED]
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
        When(status=Job.STATUS_DRAFT, then=Value(0)),
        When(status=Job.STATUS_APPROVED, then=Value(1)),
        When(status=Job.STATUS_SUBMITTED, then=Value(2)),
        When(status=Job.STATUS_COMPLETED, then=Value(3)),
        When(status=Job.STATUS_REJECTED, then=Value(4)),
        When(status=Job.STATUS_CANCELLED, then=Value(5)),
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

@login_required
def job_detail(request, job_id):
    job = get_object_or_404(Job, job_id=job_id)

    # Get current estimate (highest version, non-superseded)
    current_estimate = Estimate.objects.filter(job=job).exclude(status=Estimate.STATUS_SUPERSEDED).order_by('-version').first()

    # Get superseded estimates
    superseded_estimates = Estimate.objects.filter(job=job, status=Estimate.STATUS_SUPERSEDED).order_by('-version')

    # If there's a current estimate, get its line items and total
    current_estimate_line_items = []
    current_estimate_total = 0
    if current_estimate:
        current_estimate_line_items = EstimateLineItem.objects.filter(estimate=current_estimate).order_by('line_item_id')
        current_estimate_total = sum(item.total_amount for item in current_estimate_line_items)

    work_orders = WorkOrder.objects.filter(job=job).order_by('-work_order_id')
    worksheets = EstWorksheet.objects.filter(job=job).order_by('-created_date')
    from apps.purchasing.models import PurchaseOrderLineItem
    po_ids = PurchaseOrderLineItem.objects.filter(job=job).values_list('purchase_order_id', flat=True).distinct()
    purchase_orders = PurchaseOrder.objects.filter(po_id__in=po_ids).order_by('-po_id')
    invoices = Invoice.objects.filter(job=job).order_by('-invoice_id')

    # Get current work order (most recent non-complete)
    current_work_order = work_orders.exclude(status=WorkOrder.STATUS_COMPLETE).first()
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


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def job_create(request):
    """Create a new Job"""
    initial_contact_id = request.GET.get('contact_id')
    initial_description = request.GET.get('description', '')
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
            data = form.cleaned_data.copy()
            job = JobService.create_job(**data)

            # Link to email if this came from email workflow
            email_record_id = request.session.get('email_record_id_for_job')
            if email_record_id:
                try:
                    from apps.core.services import EmailService
                    EmailService.associate_with_job(email_record_id, job.pk)
                    messages.info(request, f'Email linked to job {job.job_number}.')
                    request.session.pop('email_record_id_for_job', None)
                    request.session.pop('email_body_for_job', None)
                except (NotFoundError, Exception):
                    pass

            messages.success(request, f'Job {job.job_number} created successfully.')
            return redirect('jobs:detail', job_id=job.job_id)
    else:
        # Prepare initial data
        initial_data = {}
        if initial_description:
            initial_data['description'] = initial_description

        form = JobCreateForm(initial=initial_data, initial_contact=initial_contact)

    return render(request, 'jobs/job_create.html', {
        'form': form,
        'initial_contact': initial_contact
    })


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def job_edit(request, job_id):
    """Edit an existing Job with state-based field restrictions"""
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        form = JobEditForm(request.POST, instance=job)
        if form.is_valid():
            job = JobService.update_job(job.pk, **form.cleaned_data)
            messages.success(request, f'Job {job.job_number} updated successfully.')
            return redirect('jobs:detail', job_id=job.job_id)
    else:
        form = JobEditForm(instance=job)

    return render(request, 'jobs/job_edit.html', {
        'form': form,
        'job': job
    })


@login_required
def task_list(request):
    # Only show incomplete tasks with WorkOrders (not EstWorksheets)
    tasks = Task.objects.filter(
        work_order__isnull=False,
        est_worksheet__isnull=True
    ).exclude(
        work_order__status=WorkOrder.STATUS_COMPLETE
    ).select_related('work_order', 'work_order__job', 'assignee').order_by('-task_id')
    return render(request, 'jobs/task_list.html', {'tasks': tasks})

@login_required
def task_detail(request, task_id):
    # Try worksheet-side PlanTask first, fall back to WO-side Task.
    # HTML side is legacy; SPA will supersede. This preserves existing URL behavior.
    try:
        task = PlanTask.objects.get(pk=task_id)
        is_plan = True
    except PlanTask.DoesNotExist:
        task = get_object_or_404(Task, pk=task_id)
        is_plan = False
    if is_plan:
        bleps = []
    else:
        bleps = Blep.objects.filter(task=task).select_related('user').order_by('-start_time')
    return render(request, 'jobs/task_detail.html', {'task': task, 'bleps': bleps, 'is_plan': is_plan})


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def task_edit(request, task_id):
    """Edit a plan task's details. Only allowed for tasks on draft worksheets."""
    task = get_object_or_404(PlanTask, plan_task_id=task_id)

    # Check if editing is allowed
    worksheet = task.est_worksheet
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, f'Cannot edit tasks on a {worksheet.get_status_display().lower()} worksheet.')
        return redirect('jobs:task_detail', task_id=task_id)

    if request.method == 'POST':
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task "{task.name}" updated.')
            return redirect('jobs:task_detail', task_id=task_id)
    else:
        form = TaskEditForm(instance=task)

    return render(request, 'jobs/task_edit.html', {
        'form': form,
        'task': task,
    })


@login_required
def work_order_list(request):
    work_orders = WorkOrder.objects.all().order_by('-work_order_id')
    return render(request, 'jobs/work_order_list.html', {'work_orders': work_orders})

@login_required
def work_order_detail(request, work_order_id):
    work_order = get_object_or_404(WorkOrder, work_order_id=work_order_id)

    # Handle status update POST request
    if request.method == 'POST' and 'update_status' in request.POST:
        if work_order.status != WorkOrder.STATUS_COMPLETE:
            form = WorkOrderStatusForm(request.POST, current_status=work_order.status)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                if new_status != work_order.status:
                    WorkOrderService.update_status(work_order.pk, new_status)
                    messages.success(request, f'Work Order status updated to {new_status.title()}')
            return redirect('jobs:work_order_detail', work_order_id=work_order.work_order_id)
        else:
            messages.error(request, 'Cannot update the status of a completed work order.')
            return redirect('jobs:work_order_detail', work_order_id=work_order.work_order_id)

    # Get all tasks for this work order with blep summaries
    all_tasks = Task.objects.filter(work_order=work_order).order_by('sort_order', 'task_id')
    tasks_with_levels = _build_task_hierarchy(all_tasks)

    # Calculate blep summary for each task
    bleps_by_task = {}
    for blep in Blep.objects.filter(task__work_order=work_order).select_related('user'):
        bleps_by_task.setdefault(blep.task_id, []).append(blep)

    for item in tasks_with_levels:
        task_bleps = bleps_by_task.get(item['task'].task_id, [])
        if not task_bleps:
            item['blep_summary'] = "-"
        else:
            from datetime import timedelta
            total = timedelta()
            for b in task_bleps:
                if b.elapsed:
                    total += b.elapsed
            total_seconds = int(total.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            count = len(task_bleps)
            active = any(b.end_time is None for b in task_bleps)
            time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            parts = [time_str, f"({count} session{'s' if count != 1 else ''})"]
            if active:
                parts.append("ACTIVE")
            item['blep_summary'] = " ".join(parts)

    # Create status form for display (unless completed)
    status_form = WorkOrderStatusForm(current_status=work_order.status) if work_order.status != WorkOrder.STATUS_COMPLETE else None

    return render(request, 'jobs/work_order_detail.html', {
        'work_order': work_order,
        'tasks': tasks_with_levels,
        'status_form': status_form,
        'show_reorder': True,
        'reorder_url_name': 'jobs:task_reorder_work_order',
        'container_id': work_order.work_order_id
    })


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
@require_POST
def task_reorder_work_order(request, work_order_id, task_id, direction):
    """Reorder tasks within a WorkOrder by swapping sort_order."""
    try:
        TaskService.reorder_tasks(task_id, direction)
    except (ValidationError, NotFoundError) as e:
        messages.error(request, str(e.message if hasattr(e, 'message') else e))
    return redirect('jobs:work_order_detail', work_order_id=work_order_id)


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def material_add(request, task_id):
    """Add a PlanMaterial to a PlanTask. Only allowed on draft worksheets."""
    plan_task = get_object_or_404(PlanTask, plan_task_id=task_id)
    worksheet = plan_task.est_worksheet
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, 'Cannot add materials to tasks on a non-draft worksheet.')
        return redirect('jobs:task_detail', task_id=task_id)

    if request.method == 'POST':
        pm_instance = PlanMaterial(plan_task=plan_task)
        form = MaterialForm(request.POST, instance=pm_instance)
        if form.is_valid():
            mat = InventoryService.create_plan_material(plan_task.pk, **form.cleaned_data)
            messages.success(request, f'Material "{mat.description}" added.')
            return redirect('jobs:task_detail', task_id=task_id)
    else:
        form = MaterialForm()

    return render(request, 'jobs/material_add.html', {
        'form': form,
        'task': plan_task,
    })


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def material_edit(request, material_id):
    """Edit a PlanMaterial. Only allowed on draft worksheets."""
    material = get_object_or_404(PlanMaterial, plan_material_id=material_id)
    plan_task = material.plan_task
    worksheet = plan_task.est_worksheet

    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, 'Cannot edit materials on a non-draft worksheet.')
        return redirect('jobs:task_detail', task_id=plan_task.pk)

    if request.method == 'POST':
        form = MaterialForm(request.POST, instance=material)
        if form.is_valid():
            material = InventoryService.update_plan_material(material.pk, **form.cleaned_data)
            messages.success(request, f'Material "{material.description}" updated.')
            return redirect('jobs:task_detail', task_id=plan_task.pk)
    else:
        form = MaterialForm(instance=material)

    return render(request, 'jobs/material_edit.html', {
        'form': form,
        'material': material,
        'task': plan_task,
    })


@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def material_delete(request, material_id):
    """Delete a PlanMaterial. Only allowed on draft worksheets."""
    material = get_object_or_404(PlanMaterial, plan_material_id=material_id)
    plan_task = material.plan_task
    worksheet = plan_task.est_worksheet

    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, 'Cannot delete materials on a non-draft worksheet.')
        return redirect('jobs:task_detail', task_id=plan_task.pk)

    description = material.description
    InventoryService.delete_plan_material(material.pk)
    messages.success(request, f'Material "{description}" deleted.')
    return redirect('jobs:task_detail', task_id=plan_task.pk)
