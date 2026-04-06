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

from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.jobs.services.blep_service import BlepService
from apps.estimates.models import (
    Estimate, WorkOrderTemplate, TaskTemplate,
    EstWorksheet, EstimateLineItem,
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
        if estimate.status not in [Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED]:
            raise ValidationError(
                f"Only Open and Accepted estimates can create WorkOrders. "
                f"Estimate {estimate.estimate_number} is {estimate.status}."
            )

        work_order = WorkOrder.objects.create(
            job=estimate.job,
            status=WorkOrder.STATUS_INCOMPLETE
        )

        # Convert LineItems to Tasks
        for line_item in estimate.estimatelineitem_set.all():
            TaskService.create_from_line_item(line_item, work_order)

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(work_order)

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

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(work_order)

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

        # Release remaining earmarks when WO completes
        if new_status == WorkOrder.STATUS_COMPLETE:
            from apps.inventory.services import InventoryService
            InventoryService.release_earmarks_for_job(wo.job)

        return wo

    @staticmethod
    def copy_from_worksheet(work_order_pk, worksheet_pk):
        """Copy a worksheet's PlanTasks (with their PlanMaterials) to a work order.

        Per spec 2026-04-05-task-split-and-worksheet-to-workorder.md:
        - No bundle copy (RealBundle does not exist).
        - No parent_task copy (hierarchy emerges during work).
        - No mapping_strategy copy (irrelevant on work order).
        - PlanMaterials become Materials with price_list_item preserved.
        """
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import PlanTask
        from apps.inventory.models import Material

        try:
            wo = WorkOrder.objects.get(pk=work_order_pk)
        except WorkOrder.DoesNotExist:
            raise NotFoundError(f'WorkOrder {work_order_pk} not found')
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')

        for plan_task in PlanTask.objects.filter(
            est_worksheet=ws
        ).prefetch_related('plan_materials'):
            new_task = Task.objects.create(
                work_order=wo,
                name=plan_task.name,
                description=plan_task.description,
                units=plan_task.units,
                rate=plan_task.rate,
                est_qty=plan_task.est_qty,
                accounting_category=plan_task.accounting_category,
                sort_order=plan_task.sort_order,
            )
            for pm in plan_task.plan_materials.all():
                Material.objects.create(
                    task=new_task,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(wo)


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
        """Copy the PlanTask that contributed to this EstimateLineItem into a Task on the WO.

        Note: after the spec 2026-04-05 model split, this function copies exactly one
        PlanTask to one Task. The prior "multi-task with parent relationships" logic was
        dead code (the source list was always a single element) and is removed.
        """
        plan_task = line_item.task  # now a PlanTask FK
        new_task = Task.objects.create(
            work_order=work_order,
            name=plan_task.name,
            description=plan_task.description,
            units=plan_task.units,
            rate=plan_task.rate,
            est_qty=plan_task.est_qty,
            accounting_category=plan_task.accounting_category,
            # assignee and status use defaults; parent_task is None
        )
        return [new_task]

    @staticmethod
    def _create_task_from_catalog_item(line_item, work_order):
        """Create a task from PriceListItem data."""
        task_name = f"{line_item.price_list_item.code} - {line_item.price_list_item.description[:50]}"
        if len(line_item.price_list_item.description) > 50:
            task_name += "..."

        task = Task.objects.create(
            work_order=work_order,
            name=task_name,
            units=line_item.units if line_item.units not in ('', 'none') else line_item.price_list_item.units,
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
            accounting_category=template.accounting_category,
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

        # Post-split: Task is always work-order side.
        items_qs = Task.objects.filter(work_order=task.work_order)

        BundlingService.reorder_container_items(
            items_qs, 'task', task_id, direction,
        )
        task.refresh_from_db()
        return task


class TaskLifecycleService:
    """Service for managing Task status transitions and Blep (time tracking) lifecycle."""

    @staticmethod
    def complete_task(task_pk):
        """Transition task from pending/in_progress/blocked -> complete."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED):
                raise ValidationError(
                    f"Cannot complete task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            BlepService._close_open(task=task)
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_COMPLETE)
            task.status = Task.STATUS_COMPLETE
            TaskLifecycleService._check_wo_auto_complete(task)
            return task

    @staticmethod
    def _check_wo_auto_complete(task):
        """Auto-complete WO if all its tasks are complete or cancelled."""
        # Post-split: task is always a Task (work-order side); no container check needed.
        wo = task.work_order
        terminal = {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED}
        all_terminal = not Task.objects.filter(
            work_order=wo
        ).exclude(status__in=terminal).exists()
        if all_terminal:
            WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

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
            TaskLifecycleService._check_wo_blocked(task)
            return task

    @staticmethod
    def _check_wo_blocked(task):
        """Block WorkOrder if a task on it is blocked."""
        # Post-split: task is always a Task (work-order side); no container check needed.
        wo = task.work_order
        if wo.status in (WorkOrder.STATUS_BLOCKED, WorkOrder.STATUS_COMPLETE):
            return
        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_BLOCKED)

    @staticmethod
    def _check_wo_unblocked(task):
        """Unblock WorkOrder if no other tasks on it are blocked."""
        wo = task.work_order
        if wo.status != WorkOrder.STATUS_BLOCKED:
            return
        still_blocked = Task.objects.filter(
            work_order=wo, status=Task.STATUS_BLOCKED,
        ).exclude(pk=task.pk).exists()
        if not still_blocked:
            WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_INCOMPLETE)

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
            TaskLifecycleService._check_wo_unblocked(task)
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
            was_blocked = task.status == Task.STATUS_BLOCKED
            BlepService._close_open(task=task)
            Task.objects.filter(pk=task.pk).update(status=Task.STATUS_CANCELLED)
            task.status = Task.STATUS_CANCELLED
            if was_blocked:
                TaskLifecycleService._check_wo_unblocked(task)
            TaskLifecycleService._check_wo_auto_complete(task)
            return task

    @staticmethod
    def start_work(task_pk, user, action=None):
        """Create a Blep for `user` on the given task.

        - If the task is pending, promotes it to in_progress and consumes
          materials (first worker to start the task).
        - If already in_progress, handles multi-worker conflicts via
          `action='join'` or `action='takeover'`.
        - Rejects worksheet tasks and terminal statuses.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            # Post-split: task is always a Task (work-order side); no container check needed.
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot start work: task status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            now = timezone.now()

            if task.status == Task.STATUS_PENDING:
                # First worker on a pending task: promote and consume materials.
                # No conflict possible — nobody has touched it yet.
                BlepService._close_open(user=user, now=now)
                Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
                task.status = Task.STATUS_IN_PROGRESS
                from apps.inventory.services import InventoryService
                for material in task.materials.all():
                    InventoryService.consume_material(material)
                blep = BlepService._create(task, user, start_time=now)
                return {'task': task, 'blep': blep}

            # Task is in_progress: check for other active workers.
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
            # Close user's open Blep on ANY task
            BlepService._close_open(user=user, now=now)
            if action == 'takeover':
                other_bleps.update(end_time=now)
            blep = BlepService._create(task, user, start_time=now)
            return {'task': task, 'blep': blep}

    @staticmethod
    def stop_work(task_pk, user):
        """Close user's open Blep on this task."""
        with transaction.atomic():
            task = Task.objects.get(pk=task_pk)
            closed = BlepService._close_open(user=user, task=task)
            if not closed:
                raise ValidationError(
                    "No open time entry found for this user on this task."
                )

