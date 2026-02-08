"""
Service classes for handling complex creation workflows between Jobs, WorkOrders, Estimates, and Tasks.
"""

from decimal import Decimal
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Prefetch
from django.utils import timezone

from .models import (
    Job, WorkOrder, Estimate, Task, WorkOrderTemplate, TaskTemplate,
    EstWorksheet, EstimateLineItem
)
from apps.invoicing.models import PriceListItem
from apps.core.services import NumberGenerationService


class LineItemTaskService:
    """Service class for generating tasks from EstimateLineItems."""

    @staticmethod
    def generate_tasks_for_work_order(line_item, work_order):
        """
        Generate appropriate Task(s) for a LineItem in a WorkOrder.

        Args:
            line_item (EstimateLineItem): The line item to generate tasks from
            work_order (WorkOrder): The WorkOrder to create tasks for

        Returns:
            List[Task]: Tasks created for this LineItem
        """
        if line_item.task:
            # Case 1: LineItem derived from worksheet task - copy existing task(s)
            return LineItemTaskService._copy_worksheet_tasks(line_item, work_order)
        elif line_item.price_list_item:
            # Case 2: LineItem from catalog - create task from catalog item
            return LineItemTaskService._create_task_from_catalog_item(line_item, work_order)
        else:
            # Case 3: Manual LineItem - create generic task
            return LineItemTaskService._create_generic_task(line_item, work_order)

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
                template=source_task.template,
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
            rate=line_item.price_currency or line_item.price_list_item.selling_price,
            est_qty=line_item.qty,
            assignee=None,
            template=None,
            parent_task=None
        )
        return [task]

    @staticmethod
    def _create_generic_task(line_item, work_order):
        """Create a generic task from manual LineItem data."""
        if line_item.description:
            task_name = line_item.description
        elif line_item.line_number:
            task_name = f"Line Item {line_item.line_number}"
        else:
            task_name = f"Line Item {line_item.pk}"

        task = Task.objects.create(
            work_order=work_order,
            name=task_name,
            units=line_item.units,
            rate=line_item.price_currency,
            est_qty=line_item.qty,
            assignee=None,
            template=None,
            parent_task=None
        )
        return [task]


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
        Created WorkOrder starts in 'draft' status.
        """
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
            
        work_order = WorkOrder.objects.create(
            job=job,
            template=template,
            status='draft'
        )
        
        # Generate Tasks from TaskTemplate associations
        from .models import TemplateTaskAssociation
        associations = TemplateTaskAssociation.objects.filter(
            work_order_template=template,
            task_template__is_active=True
        ).order_by('sort_order', 'task_template__template_name')
        
        for association in associations:
            association.task_template.generate_task(work_order, association.est_qty)
            
        return work_order
    
    @staticmethod
    def create_direct(job, **kwargs):
        """Create WorkOrder directly. Starts in 'draft' status."""
        return WorkOrder.objects.create(
            job=job,
            status='draft',
            **kwargs
        )


class EstimateService:
    """Service class for Estimate creation workflows."""
    
    @staticmethod
    def create_from_work_order(work_order):
        """
        Create Estimate from WorkOrder.
        Only Draft WorkOrders can create Estimates.
        Created Estimate starts in 'draft' status.
        """
        if work_order.status != 'draft':
            raise ValidationError(
                f"Only Draft WorkOrders can create Estimates. "
                f"WorkOrder {work_order.pk} is {work_order.status}."
            )

        # Generate estimate number using centralized service
        estimate_number = NumberGenerationService.generate_next_number('estimate')

        estimate = Estimate.objects.create(
            job=work_order.job,
            estimate_number=estimate_number,
            status='draft'
        )

        # Convert Tasks to LineItems
        from .models import EstimateLineItem
        for task in work_order.task_set.all():
            TaskService.create_line_item_from_task(task, estimate)

        return estimate

    @staticmethod
    def create_direct(job, **kwargs):
        """
        Create Estimate directly. Starts in 'draft' status.
        Estimate number is auto-generated.
        """
        # Generate estimate number using centralized service
        estimate_number = NumberGenerationService.generate_next_number('estimate')

        return Estimate.objects.create(
            job=job,
            estimate_number=estimate_number,
            status='draft',
            **kwargs
        )


class TaskService:
    """Service class for Task creation workflows."""
    
    @staticmethod
    def create_from_line_item(line_item, work_order):
        """
        Create Task from LineItem.
        """
        task = Task.objects.create(
            work_order=work_order,
            name=f"Task from {line_item.description or 'LineItem'}",
        )
        return task
    
    @staticmethod
    def create_from_template(template, work_order, assignee=None):
        """
        Create Task from TaskTemplate.
        """
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
            
        task = Task.objects.create(
            work_order=work_order,
            template=template,
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
    def create_line_item_from_task(task, estimate):
        """
        Create LineItem from Task.
        """
        from .models import EstimateLineItem
        from apps.core.models import LineItemType

        # Get line_item_type from task's template if available
        line_item_type = None
        if task.template and hasattr(task.template, 'line_item_type'):
            line_item_type = task.template.line_item_type

        # Fall back to default LineItemType if none specified
        if line_item_type is None:
            # Get default LineItemType (Direct/Service)
            line_item_type = LineItemType.objects.filter(
                code__in=['SVC', 'DIR']
            ).first()
            # If no standard default exists, get any active type
            if line_item_type is None:
                line_item_type = LineItemType.objects.filter(is_active=True).first()

        line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            description=f"LineItem from {task.name}",
            qty=1,
            units="each",
            price_currency=0,
            line_item_type=line_item_type,
        )
        return line_item


class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates.

    TODO: Reimplement using TemplateBundle system.
    """

    def __init__(self):
        self.line_number = 1
        self._default_line_item_type = None

    def _get_default_line_item_type(self):
        """Get a default LineItemType to use when none is specified."""
        if self._default_line_item_type is None:
            from apps.core.models import LineItemType
            self._default_line_item_type = LineItemType.objects.filter(
                code__in=['SVC', 'DIR'], is_active=True
            ).first()
            if self._default_line_item_type is None:
                self._default_line_item_type = LineItemType.objects.filter(is_active=True).first()
        return self._default_line_item_type

    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet) -> 'Estimate':
        """
        Convert EstWorksheet to Estimate.

        TODO: Reimplement with TemplateBundle system.
        """
        raise NotImplementedError("EstimateGenerationService needs reimplementation with TemplateBundle system")