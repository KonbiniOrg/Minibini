"""
Service classes for handling complex creation workflows between Jobs, WorkOrders, and Tasks.
"""

from decimal import Decimal
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Prefetch
from django.utils import timezone

from .models import Job, WorkOrder, Task, TaskBundle, Blep
from apps.estimates.models import (
    Estimate, WorkOrderTemplate, TaskTemplate,
    EstWorksheet, EstimateLineItem
)
from apps.inventory.models import PriceListItem
from apps.core.services import NumberGenerationService, NotFoundError


class JobService:
    """Service for Job CRUD operations."""

    @staticmethod
    def create_job(**kwargs):
        """Create a new Job with auto-generated number."""
        job_number = NumberGenerationService.generate_next_number('job')
        job = Job(job_number=job_number, **kwargs)
        job.full_clean()
        job.save()
        return job

    @staticmethod
    def update_job(pk, **kwargs):
        """Update an existing Job by PK."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        for field, value in kwargs.items():
            setattr(job, field, value)
        job.full_clean()
        job.save()
        return job


class WorkOrderService:
    """Service class for WorkOrder creation workflows."""

    @staticmethod
    def create_from_estimate(estimate):
        """
        Create WorkOrder from Estimate.
        Only Open and Accepted Estimates can create WorkOrders.
        Created WorkOrder starts in 'incomplete' status.
        """
        if estimate.status not in ['open', 'accepted']:
            raise ValidationError(
                f"Only Open and Accepted estimates can create WorkOrders. "
                f"Estimate {estimate.estimate_number} is {estimate.status}."
            )

        work_order = WorkOrder.objects.create(
            job=estimate.job,
            status='incomplete'
        )

        # Convert LineItems to Tasks
        for line_item in estimate.estimatelineitem_set.all():
            TaskService.create_from_line_item(line_item, work_order)

        return work_order

    @staticmethod
    def create_from_template(template, job):
        """
        Create WorkOrder from WorkOrderTemplate.
        Created WorkOrder starts in 'incomplete' status.
        """
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")

        work_order = WorkOrder.objects.create(
            job=job,
            template=template,
        )

        # Generate Tasks from TaskTemplate associations
        from apps.estimates.models import TemplateTaskAssociation
        associations = TemplateTaskAssociation.objects.filter(
            work_order_template=template,
            task_template__is_active=True
        ).order_by('sort_order', 'task_template__template_name')

        for association in associations:
            association.task_template.generate_task(work_order, association.est_qty)

        return work_order

    @staticmethod
    def create_direct(job, **kwargs):
        """Create WorkOrder directly. Starts in 'incomplete' status."""
        return WorkOrder.objects.create(
            job=job,
            **kwargs
        )

    @staticmethod
    def update_status(pk, new_status):
        """Update work order status."""
        try:
            wo = WorkOrder.objects.get(pk=pk)
        except WorkOrder.DoesNotExist:
            raise NotFoundError(f'WorkOrder {pk} not found')
        wo.status = new_status
        wo.full_clean()
        wo.save()
        return wo

    @staticmethod
    def copy_from_worksheet(work_order_pk, worksheet_pk):
        """Copy a worksheet's bundles, tasks, and materials to a work order."""
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import TaskBundle
        from apps.inventory.models import Material

        try:
            wo = WorkOrder.objects.get(pk=work_order_pk)
        except WorkOrder.DoesNotExist:
            raise NotFoundError(f'WorkOrder {work_order_pk} not found')
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')

        # Copy TaskBundles, mapping old bundle PKs to new ones
        bundle_mapping = {}
        for bundle in TaskBundle.objects.filter(est_worksheet=ws):
            new_bundle = TaskBundle.objects.create(
                work_order=wo,
                name=bundle.name,
                description=bundle.description,
                line_item_type=bundle.line_item_type,
                sort_order=bundle.sort_order,
                source_template_bundle=bundle.source_template_bundle,
            )
            bundle_mapping[bundle.pk] = new_bundle

        # Copy tasks with their materials
        for task in Task.objects.filter(est_worksheet=ws).prefetch_related('materials'):
            new_bundle = bundle_mapping.get(task.bundle_id) if task.bundle_id else None
            new_task = Task.objects.create(
                work_order=wo,
                name=task.name,
                description=task.description,
                units=task.units,
                rate=task.rate,
                est_qty=task.est_qty,
                assignee=task.assignee,
                line_item_type=task.line_item_type,
                mapping_strategy=task.mapping_strategy,
                bundle=new_bundle,
                sort_order=task.sort_order,
            )
            for material in task.materials.all():
                Material.objects.create(
                    task=new_task,
                    price_list_item=material.price_list_item,
                    line_item_type=material.line_item_type,
                    description=material.description,
                    quantity=material.quantity,
                    unit_cost=material.unit_cost,
                    sell_price=material.sell_price,
                )


class TaskService:
    """Service class for Task creation workflows."""

    @staticmethod
    def create_from_line_item(line_item, work_order):
        """
        Generate appropriate Task(s) for a LineItem in a WorkOrder.

        Dispatches to the right strategy based on line item source:
        - Worksheet task: copies the source task with all fields
        - Catalog PLI: creates task from PriceListItem data
        - Manual: creates task from line item fields

        Returns:
            List[Task]: Tasks created for this LineItem
        """
        if line_item.task:
            return TaskService._copy_worksheet_tasks(line_item, work_order)
        elif line_item.price_list_item:
            return TaskService._create_task_from_catalog_item(line_item, work_order)
        else:
            return TaskService._create_generic_task(line_item, work_order)

    @staticmethod
    def _copy_worksheet_tasks(line_item, work_order):
        """Copy the task that contributed to this EstimateLineItem."""
        tasks = []
        source_tasks = [line_item.task]

        # Create mapping for parent-child relationships
        task_id_mapping = {}

        # First pass: create all tasks
        for source_task in source_tasks:
            new_task = Task.objects.create(
                work_order=work_order,
                name=source_task.name,
                units=source_task.units,
                rate=source_task.rate,
                est_qty=source_task.est_qty,
                assignee=source_task.assignee,
                line_item_type=source_task.line_item_type,
                parent_task=None  # Set in second pass
            )
            task_id_mapping[source_task.task_id] = new_task
            tasks.append(new_task)

        # Second pass: set parent relationships within this set of tasks
        for source_task in source_tasks:
            if source_task.parent_task and source_task.parent_task_id in task_id_mapping:
                new_task = task_id_mapping[source_task.task_id]
                new_parent = task_id_mapping[source_task.parent_task_id]
                new_task.parent_task = new_parent
                new_task.save()

        return tasks

    @staticmethod
    def _create_task_from_catalog_item(line_item, work_order):
        """Create a task from PriceListItem data."""
        task_name = f"{line_item.price_list_item.code} - {line_item.price_list_item.description[:50]}"
        if len(line_item.price_list_item.description) > 50:
            task_name += "..."

        task = Task.objects.create(
            work_order=work_order,
            name=task_name,
            units=line_item.units or line_item.price_list_item.units,
            rate=line_item.price or line_item.price_list_item.selling_price,
            est_qty=line_item.qty,
            assignee=None,
            parent_task=None
        )
        return [task]

    @staticmethod
    def _create_generic_task(line_item, work_order):
        """Create a generic task from manual LineItem data."""
        if line_item.description:
            task_name = line_item.description[:255]
        elif line_item.line_number:
            task_name = f"Line Item {line_item.line_number}"
        else:
            task_name = f"Line Item {line_item.pk}"

        task = Task.objects.create(
            work_order=work_order,
            name=task_name,
            units=line_item.units,
            rate=line_item.price,
            est_qty=line_item.qty,
            assignee=None,
            parent_task=None
        )
        return [task]

    @staticmethod
    def create_from_template(template, work_order, assignee=None):
        """
        Create Task from TaskTemplate.
        """
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")

        task = Task.objects.create(
            work_order=work_order,
            line_item_type=template.line_item_type,
            name=template.template_name,
            assignee=assignee
        )
        return task

    @staticmethod
    def create_direct(work_order, name, **kwargs):
        """Create Task directly."""
        return Task.objects.create(
            work_order=work_order,
            name=name,
            **kwargs
        )

    @staticmethod
    def update_task(pk, **kwargs):
        """Update an existing Task by PK."""
        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {pk} not found')
        for field, value in kwargs.items():
            setattr(task, field, value)
        task.full_clean()
        task.save()
        return task

    @staticmethod
    def reorder_tasks(task_id, direction):
        """Reorder a task within its container — delegates to BundlingService."""
        from apps.core.services import BundlingService

        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_id} not found')

        container = task.get_container()
        if container is None:
            raise ValidationError('Task has no container.')

        # Build queryset for the container
        if task.work_order:
            items_qs = Task.objects.filter(work_order=task.work_order)
        else:
            items_qs = Task.objects.filter(est_worksheet=task.est_worksheet)

        BundlingService.reorder_container_items(
            items_qs, 'task', task_id, direction,
        )
        task.refresh_from_db()
        return task


class TaskLifecycleService:
    """Service for managing Task status transitions and Blep (time tracking) lifecycle."""

    @staticmethod
    def start_task(task_pk, user):
        """Transition task from pending -> in_progress, consume materials, create Blep."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status != Task.STATUS_PENDING:
                raise ValidationError(
                    f"Cannot start task: status is '{task.status}', must be 'pending'."
                )
            if not task.work_order:
                raise ValidationError(
                    "Cannot start task: task must belong to a WorkOrder, not a worksheet."
                )
            # Close user's open Blep on ANY task
            now = timezone.now()
            Blep.objects.filter(user=user, end_time__isnull=True).update(end_time=now)
            # Update status
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
            task.status = Task.STATUS_IN_PROGRESS
            # Consume materials
            from apps.inventory.services import InventoryService
            for material in task.materials.all():
                InventoryService.consume_material(material)
            # Create Blep
            blep = Blep.objects.create(task=task, user=user, start_time=now)
            return {'task': task, 'blep': blep}

    @staticmethod
    def complete_task(task_pk):
        """Transition task from pending/in_progress -> complete."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot complete task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            now = timezone.now()
            Blep.objects.filter(task=task, end_time__isnull=True).update(end_time=now)
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_COMPLETE)
            task.status = Task.STATUS_COMPLETE
            TaskLifecycleService._check_wo_auto_complete(task)
            return task

    @staticmethod
    def _check_wo_auto_complete(task):
        """Auto-complete WO if all its tasks are complete or cancelled."""
        if not task.work_order:
            return
        wo = task.work_order
        terminal = {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED}
        all_terminal = not Task.objects.filter(
            work_order=wo
        ).exclude(status__in=terminal).exists()
        if all_terminal:
            WorkOrderService.update_status(wo.pk, 'complete')

    @staticmethod
    def block_task(task_pk):
        """Transition task from pending/in_progress -> blocked.
        Returns conflict dict if open Bleps exist."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot block task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            open_bleps = Blep.objects.filter(task=task, end_time__isnull=True)
            if open_bleps.exists():
                workers = []
                for b in open_bleps:
                    workers.append({
                        'user_id': b.user_id,
                        'name': b.user.get_full_name() or b.user.username,
                        'blep_id': b.blep_id,
                        'started_at': b.start_time,
                    })
                return {'conflict': 'active_workers', 'workers': workers}
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_BLOCKED)
            task.status = Task.STATUS_BLOCKED
            return task

    @staticmethod
    def unblock_task(task_pk):
        """Transition task from blocked -> in_progress."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status != Task.STATUS_BLOCKED:
                raise ValidationError(
                    f"Cannot unblock task: status is '{task.status}', must be 'blocked'."
                )
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
            task.status = Task.STATUS_IN_PROGRESS
            return task

    @staticmethod
    def cancel_task(task_pk):
        """Transition task from pending/in_progress/blocked -> cancelled."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            allowed = (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED)
            if task.status not in allowed:
                raise ValidationError(
                    f"Cannot cancel task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            now = timezone.now()
            Blep.objects.filter(task=task, end_time__isnull=True).update(end_time=now)
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_CANCELLED)
            task.status = Task.STATUS_CANCELLED
            TaskLifecycleService._check_wo_auto_complete(task)
            return task

    @staticmethod
    def start_work(task_pk, user, action=None):
        """Start a Blep on an in_progress task. Handles multi-worker conflicts."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status != Task.STATUS_IN_PROGRESS:
                raise ValidationError(
                    f"Cannot start work: task status is '{task.status}', "
                    f"must be 'in_progress'."
                )
            # Check for other workers' open Bleps
            other_bleps = Blep.objects.filter(
                task=task, end_time__isnull=True
            ).exclude(user=user)
            if other_bleps.exists() and action is None:
                b = other_bleps.first()
                return {
                    'conflict': 'active_worker',
                    'worker': {
                        'user_id': b.user_id,
                        'name': b.user.get_full_name() or b.user.username,
                    },
                    'blep_id': b.blep_id,
                    'started_at': b.start_time,
                    'options': ['join', 'takeover'],
                }
            now = timezone.now()
            # Close user's open Blep on ANY task
            Blep.objects.filter(user=user, end_time__isnull=True).update(end_time=now)
            if action == 'takeover':
                other_bleps.update(end_time=now)
            blep = Blep.objects.create(task=task, user=user, start_time=now)
            return {'task': task, 'blep': blep}

    @staticmethod
    def stop_work(task_pk, user):
        """Close user's open Blep on this task."""
        with transaction.atomic():
            updated = Blep.objects.filter(
                task_id=task_pk, user=user, end_time__isnull=True
            ).update(end_time=timezone.now())
            if not updated:
                raise ValidationError(
                    "No open time entry found for this user on this task."
                )

