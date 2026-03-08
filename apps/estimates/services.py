"""
Service classes for Estimate generation and management.
"""

from decimal import Decimal
from collections import defaultdict

from django.db import transaction

from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet
)
from apps.core.services import NumberGenerationService


class EstimateService:
    """Service class for Estimate creation workflows."""

    @staticmethod
    def create_from_work_order(work_order):
        """
        Create Estimate from WorkOrder.
        Only Draft WorkOrders can create Estimates.
        Created Estimate starts in 'draft' status.
        """
        from django.core.exceptions import ValidationError
        from apps.jobs.services import TaskService

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


class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates using instance-level bundling."""

    def __init__(self):
        self.line_number = 1
        self._default_line_item_type = None

    def _get_default_line_item_type(self):
        """Get a fallback LineItemType when none is available from the source object."""
        if self._default_line_item_type is None:
            from apps.core.models import LineItemType
            self._default_line_item_type = LineItemType.objects.filter(is_active=True).first()
        return self._default_line_item_type

    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet) -> 'Estimate':
        """
        Convert EstWorksheet to Estimate using instance-level mapping config.

        Tasks are processed based on their own mapping_strategy field:
        - 'direct': Task becomes its own line item
        - 'bundle': Tasks in same TaskBundle are combined into one line item
        - 'exclude': Task is not included on estimate
        """
        tasks = worksheet.task_set.select_related('bundle').prefetch_related('materials').all()

        if not tasks:
            raise ValueError(f"EstWorksheet {worksheet.pk} has no tasks to convert")

        # Create the estimate
        estimate = self._create_estimate(worksheet)

        # Categorize tasks by their instance-level mapping strategy
        direct_tasks = []
        bundles = defaultdict(list)  # bundle_id -> [tasks]

        for task in tasks:
            if task.mapping_strategy == 'exclude':
                continue
            elif task.mapping_strategy == 'bundle' and task.bundle:
                bundles[task.bundle_id].append(task)
            else:
                direct_tasks.append(task)

        # Generate line items
        line_items = []

        # Process bundled tasks
        for bundle_id, bundle_tasks in bundles.items():
            task_bundle = bundle_tasks[0].bundle
            line_item = self._create_bundle_line_item(bundle_tasks, task_bundle, estimate)
            line_items.append(line_item)

        # Process direct tasks
        for task in direct_tasks:
            has_materials = task.materials.exists()
            is_pass_through = (not task.rate or task.rate == Decimal('0.00')) and has_materials

            # Skip labor line item for pass-through tasks (no rate, only materials)
            if not is_pass_through:
                line_item = self._create_direct_line_item(task, estimate)
                line_items.append(line_item)

            # Create material line items for each material on direct tasks
            for material in task.materials.all():
                mat_li = self._create_material_line_item(material, estimate)
                line_items.append(mat_li)

        # Bulk create all line items
        if line_items:
            EstimateLineItem.objects.bulk_create(line_items)

        # Link worksheet to estimate
        worksheet.estimate = estimate
        worksheet.save()

        return estimate

    def _create_estimate(self, worksheet) -> 'Estimate':
        """Create a new estimate for the worksheet's job."""
        version = 1
        parent_estimate = None

        if worksheet.parent and worksheet.parent.estimate:
            parent_estimate = worksheet.parent.estimate
            estimate_number = parent_estimate.estimate_number
            version = parent_estimate.version + 1
            parent_estimate.status = 'superseded'
            parent_estimate.save()
        else:
            estimate_number = NumberGenerationService.generate_next_number('estimate')

        estimate = Estimate.objects.create(
            job=worksheet.job,
            estimate_number=estimate_number,
            version=version,
            parent=parent_estimate,
            status='draft'
        )

        return estimate

    def _create_direct_line_item(self, task, estimate) -> 'EstimateLineItem':
        """Create a line item for a direct-mapped task."""
        qty = task.est_qty or Decimal('1.00')
        rate = task.rate or Decimal('0.00')

        # Get line_item_type from task directly
        line_item_type = task.line_item_type

        if line_item_type is None:
            line_item_type = self._get_default_line_item_type()

        line_item = EstimateLineItem(
            estimate=estimate,
            task=task,
            line_number=self.line_number,
            description=task.name,
            qty=qty,
            units=task.units or 'each',
            price=rate,
            line_item_type=line_item_type
        )

        self.line_number += 1
        return line_item

    def _create_material_line_item(self, material, estimate) -> 'EstimateLineItem':
        """Create a line item for a material on a direct-mapped task."""
        # Derive line_item_type: PLI first, then material's own field, then fallback
        line_item_type = None
        if material.price_list_item:
            line_item_type = material.price_list_item.line_item_type
        if line_item_type is None:
            line_item_type = material.line_item_type
        if line_item_type is None:
            line_item_type = self._get_default_line_item_type()

        line_item = EstimateLineItem(
            estimate=estimate,
            material=material,
            line_number=self.line_number,
            description=material.description,
            qty=material.quantity,
            units='each',
            price=material.sell_price,
            line_item_type=line_item_type,
        )

        self.line_number += 1
        return line_item

    def _create_bundle_line_item(self, tasks, bundle, estimate) -> 'EstimateLineItem':
        """Create a single line item for bundled tasks, including material costs."""
        total_price = Decimal('0.00')

        for task in tasks:
            qty = task.est_qty or Decimal('1.00')
            rate = task.rate or Decimal('0.00')
            total_price += qty * rate
            # Add material sell totals to bundle price
            for material in task.materials.all():
                total_price += material.total_sell

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=bundle.name,
            qty=Decimal('1.00'),
            units='each',
            price=total_price,
            line_item_type=bundle.line_item_type
        )

        self.line_number += 1
        return line_item
