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
    EstWorksheet, EstimateLineItem, TaskMapping, BundlingRule, TaskInstanceMapping
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
            # Find all tasks with the same bundle_identifier (all tasks that contributed to this line item)
            source_tasks = Task.objects.filter(
                est_worksheet=line_item.task.est_worksheet,
                taskinstancemapping__bundle_identifier=instance_mapping.bundle_identifier
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
                    bundle_identifier=old_mapping.bundle_identifier,
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
        Uses TaskMapping for translation.
        """
        from .models import EstimateLineItem
        from apps.core.models import LineItemType

        # Get line_item_type from task's template mapping if available
        line_item_type = None
        if task.template and task.template.task_mapping:
            line_item_type = task.template.task_mapping.output_line_item_type

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
    """Service for converting EstWorksheets to Estimates using TaskMappings"""

    def __init__(self):
        self.line_number = 1
        self._default_line_item_type = None

    def _get_default_line_item_type(self):
        """Get a default LineItemType to use when none is specified."""
        if self._default_line_item_type is None:
            from apps.core.models import LineItemType
            # Try to find Service type first, then Direct, then any active type
            self._default_line_item_type = LineItemType.objects.filter(
                code__in=['SVC', 'DIR'], is_active=True
            ).first()
            if self._default_line_item_type is None:
                self._default_line_item_type = LineItemType.objects.filter(is_active=True).first()
        return self._default_line_item_type
    
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
        bundles, direct_items, excluded = self._categorize_tasks(tasks)

        # Generate line items
        line_items = []

        # Process bundled tasks
        if bundles:
            bundle_line_items = self._process_bundles(bundles, estimate)
            line_items.extend(bundle_line_items)

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
    
    def _categorize_tasks(self, tasks: List[Task]) -> Tuple[Dict, List[Task], List[Task]]:
        """
        Categorize tasks based on their mapping strategy.

        Returns:
            Tuple of (bundles_dict, direct_list, excluded_list)
            bundles_dict is keyed by bundle_identifier (or auto-generated key)
        """
        bundles = defaultdict(list)  # bundle_identifier -> [tasks]
        direct_items = []
        excluded = []

        for task in tasks:
            strategy = task.get_mapping_strategy()

            if strategy == 'exclude':
                excluded.append(task)
            elif strategy == 'bundle':
                # Get bundle identifier from instance mapping or auto-generate
                try:
                    instance_mapping = task.taskinstancemapping
                    bundle_identifier = instance_mapping.bundle_identifier
                except TaskInstanceMapping.DoesNotExist:
                    bundle_identifier = None

                # If no explicit bundle_identifier, group by product_type
                if not bundle_identifier:
                    product_type = task.get_product_type() or 'general'
                    bundle_identifier = f"_auto_{product_type}"

                bundles[bundle_identifier].append(task)
            else:  # 'direct' or unrecognized
                direct_items.append(task)

        return bundles, direct_items, excluded
    
    def _process_bundles(self, bundles: Dict[str, List[Task]], estimate: Estimate) -> List[EstimateLineItem]:
        """
        Process bundled tasks into line items using BundlingRule configuration.

        Bundles are grouped by bundle_identifier. The BundlingRule.default_units
        determines quantity calculation:
        - 'each': qty=1 per bundle
        - 'hours': qty=sum of task hours
        """
        line_items = []

        # Group bundles by product_type for rule lookup and potential combining
        bundles_by_type = defaultdict(list)

        for bundle_id, task_list in bundles.items():
            if task_list:
                first_task = task_list[0]
                product_type = first_task.get_product_type() or 'general'

                # Get instance number if available
                try:
                    instance_mapping = first_task.taskinstancemapping
                    instance_num = instance_mapping.product_instance
                except TaskInstanceMapping.DoesNotExist:
                    instance_num = None

                bundles_by_type[product_type].append({
                    'identifier': bundle_id,
                    'tasks': task_list,
                    'instance': instance_num
                })

        # Process each product type
        for product_type, bundle_instances in bundles_by_type.items():
            # Find applicable bundling rule
            rule = BundlingRule.objects.filter(
                product_type=product_type,
                is_active=True
            ).order_by('priority').first()

            if rule and rule.combine_instances and len(bundle_instances) > 1:
                # Create single line item with quantity for combined instances
                line_item = self._create_combined_bundle_line_item(
                    bundle_instances, rule, estimate, quantity=len(bundle_instances)
                )
                line_items.append(line_item)
            else:
                # Create separate line items for each bundle
                for bundle_data in bundle_instances:
                    line_item = self._create_bundle_line_item(
                        bundle_data['tasks'], rule, estimate, product_type,
                        bundle_data['identifier']
                    )
                    line_items.append(line_item)

        return line_items

    def _create_bundle_line_item(self, tasks: List[Task], rule: Optional[BundlingRule],
                                  estimate: Estimate, product_type: str,
                                  bundle_identifier: str = '') -> EstimateLineItem:
        """Create a single line item for a bundle from its component tasks."""
        # Calculate totals
        total_price = Decimal('0.00')
        total_hours = Decimal('0.00')
        task_names = []

        for task in tasks:
            qty = task.est_qty or Decimal('1.00')
            rate = task.rate or Decimal('0.00')

            # Apply inclusion rules if rule exists
            include = True
            if rule:
                step_type = task.get_step_type()
                if step_type == 'material' and not rule.include_materials:
                    include = False
                elif step_type == 'labor' and not rule.include_labor:
                    include = False
                elif step_type == 'overhead' and not rule.include_overhead:
                    include = False

            if include:
                total_price += qty * rate
                total_hours += qty
                task_names.append(task.name)

        # Determine units and quantity based on rule
        if rule:
            default_units = rule.default_units
            if rule.pricing_method == 'template_base' and rule.work_order_template:
                total_price = rule.work_order_template.base_price or total_price
        else:
            default_units = 'each'

        if default_units == 'hours':
            qty = total_hours
            units = 'hours'
        else:  # 'each'
            qty = Decimal('1.00')
            units = 'each'

        # Build description
        if rule and rule.description_template:
            tasks_list = '\n'.join(f'- {name}' for name in task_names)
            description = rule.description_template.format(
                tasks_list=tasks_list,
                product_type=product_type.title(),
                bundle_identifier=bundle_identifier
            )
        elif rule and rule.line_item_template:
            description = rule.line_item_template.format(
                product_type=product_type.title(),
                bundle_identifier=bundle_identifier
            )
        else:
            description = f"Custom {product_type.title()}"

        # Get line_item_type: rule overrides task mapping
        line_item_type = None
        if rule and rule.output_line_item_type:
            line_item_type = rule.output_line_item_type
        else:
            for task in tasks:
                if task.template and task.template.task_mapping:
                    line_item_type = task.template.task_mapping.output_line_item_type
                    if line_item_type:
                        break

        if line_item_type is None:
            line_item_type = self._get_default_line_item_type()

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=description,
            qty=qty,
            units=units,
            price_currency=total_price,
            line_item_type=line_item_type
        )

        self.line_number += 1
        return line_item

    def _create_combined_bundle_line_item(self, instances: List[Dict], rule: BundlingRule,
                                           estimate: Estimate, quantity: int) -> EstimateLineItem:
        """Create a single line item for multiple instances of the same product type."""
        # Calculate price per unit
        unit_price = Decimal('0.00')
        total_hours = Decimal('0.00')

        if rule.pricing_method == 'template_base' and rule.work_order_template:
            unit_price = rule.work_order_template.base_price or Decimal('0.00')
        else:
            total_all_instances = Decimal('0.00')
            for instance_data in instances:
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
                        task_qty = task.est_qty or Decimal('1.00')
                        rate = task.rate or Decimal('0.00')
                        total_all_instances += task_qty * rate
                        total_hours += task_qty

            unit_price = total_all_instances / Decimal(str(quantity))

        product_type = instances[0]['tasks'][0].get_product_type() or 'product'

        # Determine units and quantity
        if rule.default_units == 'hours':
            qty = total_hours
            units = 'hours'
        else:
            qty = Decimal(str(quantity))
            units = 'each'

        # Build description
        first_identifier = instances[0].get('identifier', '')
        description = rule.line_item_template.format(
            product_type=product_type.title(),
            bundle_identifier=first_identifier if quantity == 1 else f"{quantity}x {product_type}"
        )

        # Get line_item_type
        line_item_type = rule.output_line_item_type
        if not line_item_type:
            for instance_data in instances:
                for task in instance_data['tasks']:
                    if task.template and task.template.task_mapping:
                        line_item_type = task.template.task_mapping.output_line_item_type
                        if line_item_type:
                            break
                if line_item_type:
                    break

        if line_item_type is None:
            line_item_type = self._get_default_line_item_type()

        total_price = unit_price * qty if rule.default_units == 'each' else unit_price * Decimal(str(quantity))

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=description,
            qty=qty,
            units=units,
            price_currency=total_price if rule.default_units == 'each' else unit_price * Decimal(str(quantity)),
            line_item_type=line_item_type
        )

        self.line_number += 1
        return line_item

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

            # Get line_item_type from mapping
            line_item_type = None
            if mapping and mapping.output_line_item_type:
                line_item_type = mapping.output_line_item_type

            # Use default line_item_type if none was found
            if line_item_type is None:
                line_item_type = self._get_default_line_item_type()

            line_item = EstimateLineItem(
                estimate=estimate,
                task=task,
                line_number=self.line_number,
                description=description,
                qty=qty,
                units=task.units or 'each',
                price_currency=qty * rate,
                line_item_type=line_item_type
            )

            self.line_number += 1
            line_items.append(line_item)

        return line_items