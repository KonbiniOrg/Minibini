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
    EstWorksheet, EstimateLineItem, TaskMapping, ProductBundlingRule, TaskInstanceMapping
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
        """Copy all tasks that contributed to this EstimateLineItem."""
        tasks = []

        # Check if this task is part of a bundle
        try:
            instance_mapping = TaskInstanceMapping.objects.get(task=line_item.task)
            # Find all tasks with the same product_identifier (all tasks that contributed to this line item)
            source_tasks = Task.objects.filter(
                est_worksheet=line_item.task.est_worksheet,
                taskinstancemapping__product_identifier=instance_mapping.product_identifier
            ).order_by('task_id')
        except TaskInstanceMapping.DoesNotExist:
            # Single task, not part of a bundle
            source_tasks = [line_item.task]

        # Create mapping for parent-child relationships
        task_mapping = {}

        # First pass: create all tasks that contributed to this line item
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
            task_mapping[source_task.task_id] = new_task
            tasks.append(new_task)

            # Copy TaskInstanceMapping if exists
            try:
                old_mapping = TaskInstanceMapping.objects.get(task=source_task)
                TaskInstanceMapping.objects.create(
                    task=new_task,
                    product_identifier=old_mapping.product_identifier,
                    product_instance=old_mapping.product_instance
                )
            except TaskInstanceMapping.DoesNotExist:
                pass

        # Second pass: set parent relationships within this set of tasks
        for source_task in source_tasks:
            if source_task.parent_task and source_task.parent_task_id in task_mapping:
                new_task = task_mapping[source_task.task_id]
                new_parent = task_mapping[source_task.parent_task_id]
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
        
        # Convert LineItems to Tasks via TaskMapping (placeholder for now)
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

        # Convert Tasks to LineItems via TaskMapping (placeholder for now)
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
        Uses TaskMapping for translation (placeholder for now).
        """
        # Placeholder: TaskMapping translation will be implemented later
        task = Task.objects.create(
            work_order=work_order,
            name=f"Task from {line_item.description or 'LineItem'}",
        )
        return task
    
    @staticmethod
    def create_from_template(template, work_order, assignee=None):
        """
        Create Task from TaskTemplate.
        Direct creation - no TaskMapping involved.
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
        Uses TaskMapping for translation (placeholder for now).
        """
        # Placeholder: TaskMapping translation will be implemented later
        from .models import EstimateLineItem
        line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            description=f"LineItem from {task.name}",
            qty=1,
            units="each",
            price_currency=0
        )
        return line_item


class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates using TaskMappings"""
    
    def __init__(self):
        self.line_number = 1
    
    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet: EstWorksheet) -> Estimate:
        """
        Convert EstWorksheet to Estimate using TaskMappings.
        
        Args:
            worksheet: The EstWorksheet to convert
            
        Returns:
            The generated Estimate with line items
        """
        # Get all tasks with their templates and mappings
        tasks = worksheet.task_set.select_related(
            'template',
            'template__task_mapping'
        ).prefetch_related(
            'taskinstancemapping'
        ).all()
        
        if not tasks:
            raise ValueError(f"EstWorksheet {worksheet.pk} has no tasks to convert")
        
        # Create the estimate
        estimate = self._create_estimate(worksheet)
        
        # Process tasks based on their mappings
        products, services, direct_items, excluded = self._categorize_tasks(tasks)
        
        # Generate line items
        line_items = []
        
        # Process bundled products
        if products:
            product_line_items = self._process_product_bundles(products, estimate)
            line_items.extend(product_line_items)
        
        # Process bundled services
        if services:
            service_line_items = self._process_service_bundles(services, estimate)
            line_items.extend(service_line_items)
        
        # Process direct items
        if direct_items:
            direct_line_items = self._process_direct_items(direct_items, estimate)
            line_items.extend(direct_line_items)
        
        # Bulk create all line items
        if line_items:
            EstimateLineItem.objects.bulk_create(line_items)
        
        # Link worksheet to estimate
        worksheet.estimate = estimate
        worksheet.save()
        
        return estimate
    
    def _create_estimate(self, worksheet: EstWorksheet) -> Estimate:
        """Create a new estimate for the worksheet's job"""
        # Check if worksheet has a parent with an estimate
        version = 1
        parent_estimate = None

        if worksheet.parent and worksheet.parent.estimate:
            parent_estimate = worksheet.parent.estimate
            # New estimate inherits parent's number but increments version
            estimate_number = parent_estimate.estimate_number
            version = parent_estimate.version + 1

            # Mark parent as superseded (closed_date is set automatically by model.save())
            parent_estimate.status = 'superseded'
            parent_estimate.save()
        else:
            # Generate new estimate number using centralized service
            estimate_number = NumberGenerationService.generate_next_number('estimate')

        # Create new estimate with parent reference
        estimate = Estimate.objects.create(
            job=worksheet.job,
            estimate_number=estimate_number,
            version=version,
            parent=parent_estimate,
            status='draft'
        )

        return estimate
    
    def _categorize_tasks(self, tasks: List[Task]) -> Tuple[Dict, Dict, List[Task], List[Task]]:
        """
        Categorize tasks based on their mapping strategy.
        
        Returns:
            Tuple of (products_dict, services_dict, direct_list, excluded_list)
        """
        products = defaultdict(list)  # product_identifier -> [tasks]
        services = defaultdict(list)  # service bundle key -> [tasks]
        direct_items = []
        excluded = []
        
        for task in tasks:
            strategy = task.get_mapping_strategy()
            
            if strategy == 'exclude':
                excluded.append(task)
            elif strategy == 'bundle_to_product':
                # Get product identifier from instance mapping or generate one
                try:
                    instance_mapping = task.taskinstancemapping
                    product_identifier = instance_mapping.product_identifier
                except TaskInstanceMapping.DoesNotExist:
                    # Generate product identifier if not set
                    product_type = task.get_product_type() or 'product'
                    product_identifier = f"{product_type}_{task.task_id}"
                
                products[product_identifier].append(task)
            elif strategy == 'bundle_to_service':
                # Use product_type as service bundle key
                service_key = task.get_product_type() or 'general_service'
                services[service_key].append(task)
            else:  # 'direct' or unrecognized
                direct_items.append(task)
        
        return products, services, direct_items, excluded
    
    def _process_product_bundles(self, products: Dict[str, List[Task]], estimate: Estimate) -> List[EstimateLineItem]:
        """Process product bundles into line items"""
        line_items = []
        
        # Group by product type for potential combining
        product_instances = defaultdict(list)
        
        for product_id, task_list in products.items():
            if task_list:
                first_task = task_list[0]
                product_type = first_task.get_product_type()
                if product_type:
                    # Get instance number if available
                    try:
                        instance_mapping = first_task.taskinstancemapping
                        instance_num = instance_mapping.product_instance
                    except TaskInstanceMapping.DoesNotExist:
                        instance_num = None
                    
                    product_instances[product_type].append({
                        'identifier': product_id,
                        'tasks': task_list,
                        'instance': instance_num
                    })
        
        # Process each product type
        for product_type, instances in product_instances.items():
            # Find applicable bundling rule
            rule = ProductBundlingRule.objects.filter(
                product_type=product_type,
                is_active=True
            ).order_by('priority').first()
            
            if rule and rule.combine_instances and len(instances) > 1:
                # Create single line item with quantity
                line_item = self._create_combined_product_line_item(
                    instances, rule, estimate, quantity=len(instances)
                )
                line_items.append(line_item)
            else:
                # Create separate line items for each instance
                for instance_data in instances:
                    line_item = self._create_product_line_item(
                        instance_data['tasks'], rule, estimate, product_type
                    )
                    line_items.append(line_item)
        
        return line_items
    
    def _process_service_bundles(self, services: Dict[str, List[Task]], estimate: Estimate) -> List[EstimateLineItem]:
        """Process service bundles into line items"""
        line_items = []
        
        for service_type, task_list in services.items():
            # Calculate total price for service bundle
            total_price = Decimal('0.00')
            total_hours = Decimal('0.00')
            descriptions = []
            
            for task in task_list:
                qty = task.est_qty or Decimal('1.00')
                rate = task.rate or Decimal('0.00')
                total_price += qty * rate
                total_hours += qty
                descriptions.append(f"- {task.name}")
            
            line_item = EstimateLineItem(
                estimate=estimate,
                line_number=self.line_number,
                description=f"{service_type.replace('_', ' ').title()} Services:\n" + "\n".join(descriptions),
                qty=total_hours,
                units='hours',
                price_currency=total_price
            )
            
            self.line_number += 1
            line_items.append(line_item)
        
        return line_items
    
    def _process_direct_items(self, tasks: List[Task], estimate: Estimate) -> List[EstimateLineItem]:
        """Process direct mapping tasks into individual line items"""
        line_items = []
        
        for task in tasks:
            # Get mapping from template
            mapping = None
            if task.template and task.template.task_mapping:
                mapping = task.template.task_mapping
            
            description = task.name
            if mapping and mapping.line_item_description:
                description = mapping.line_item_description
            
            qty = task.est_qty or Decimal('1.00')
            rate = task.rate or Decimal('0.00')
            
            line_item = EstimateLineItem(
                estimate=estimate,
                task=task,
                line_number=self.line_number,
                description=description,
                qty=qty,
                units=task.units or 'each',
                price_currency=qty * rate
            )
            
            self.line_number += 1
            line_items.append(line_item)
        
        return line_items
    
    def _create_product_line_item(self, tasks: List[Task], rule: Optional[ProductBundlingRule], 
                                   estimate: Estimate, product_type: str) -> EstimateLineItem:
        """Create a single line item for a product from its component tasks"""
        
        # Default values
        description = f"Custom {product_type.title()}"
        total_price = Decimal('0.00')
        
        if rule:
            description = rule.line_item_template.format(product_type=product_type.title())
            
            if rule.pricing_method == 'template_base':
                # Use template base price if available
                template = rule.work_order_template
                if template and template.base_price:
                    total_price = template.base_price
            else:
                # Sum components based on inclusion rules
                for task in tasks:
                    step_type = task.get_step_type()
                    include = True
                    if step_type == 'material' and not rule.include_materials:
                        include = False
                    elif step_type == 'labor' and not rule.include_labor:
                        include = False
                    elif step_type == 'overhead' and not rule.include_overhead:
                        include = False
                    
                    if include:
                        qty = task.est_qty or Decimal('1.00')
                        rate = task.rate or Decimal('0.00')
                        total_price += qty * rate
        else:
            # No rule, sum all task prices
            for task in tasks:
                qty = task.est_qty or Decimal('1.00')
                rate = task.rate or Decimal('0.00')
                total_price += qty * rate
        
        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=description,
            qty=Decimal('1.00'),
            units='each',
            price_currency=total_price
        )
        
        self.line_number += 1
        return line_item
    
    def _create_combined_product_line_item(self, instances: List[Dict], rule: ProductBundlingRule,
                                            estimate: Estimate, quantity: int) -> EstimateLineItem:
        """Create a single line item for multiple instances of the same product"""
        
        # Calculate price per unit
        unit_price = Decimal('0.00')
        
        if rule.pricing_method == 'template_base':
            template = rule.work_order_template
            if template and template.base_price:
                unit_price = template.base_price
        else:
            # Calculate average price per instance
            total_all_instances = Decimal('0.00')
            for instance_data in instances:
                instance_total = Decimal('0.00')
                for task in instance_data['tasks']:
                    step_type = task.get_step_type()
                    include = True
                    if step_type == 'material' and not rule.include_materials:
                        include = False
                    elif step_type == 'labor' and not rule.include_labor:
                        include = False
                    elif step_type == 'overhead' and not rule.include_overhead:
                        include = False
                    
                    if include:
                        qty = task.est_qty or Decimal('1.00')
                        rate = task.rate or Decimal('0.00')
                        instance_total += qty * rate
                
                total_all_instances += instance_total
            
            unit_price = total_all_instances / Decimal(str(quantity))
        
        product_type = instances[0]['tasks'][0].get_product_type()
        description = rule.line_item_template.format(product_type=product_type.title())
        
        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=description,
            qty=Decimal(str(quantity)),
            units='each',
            price_currency=unit_price * Decimal(str(quantity))
        )
        
        self.line_number += 1
        return line_item