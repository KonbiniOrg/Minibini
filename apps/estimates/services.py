"""
Service classes for Estimate generation and management.
"""

from decimal import Decimal
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.core.services import NumberGenerationService, NotFoundError
from apps.inventory.models import PriceListItem


class EstimateService:
    """Service class for Estimate creation and management."""

    @staticmethod
    def create_direct(job, **kwargs):
        """
        Create Estimate directly. Starts in 'draft' status.
        Estimate number is auto-generated.
        """
        estimate_number = NumberGenerationService.generate_next_number('estimate')

        return Estimate.objects.create(
            job=job,
            estimate_number=estimate_number,
            status='draft',
            **kwargs
        )

    @staticmethod
    def create_for_job(job_pk):
        """Create a new draft Estimate for a job by PK."""
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')

        estimate_number = NumberGenerationService.generate_next_number('estimate')
        estimate = Estimate.objects.create(
            job=job,
            estimate_number=estimate_number,
            version=1,
            status='draft',
        )
        return estimate

    @staticmethod
    def update_status(pk, new_status):
        """Update estimate status. Model validates transitions."""
        try:
            estimate = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        estimate.status = new_status
        estimate.save()  # Model.save() calls full_clean() and handles dates
        return estimate

    @staticmethod
    def mark_open(pk):
        """Mark a draft estimate as open and finalize associated worksheet."""
        try:
            estimate = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        if estimate.status != 'draft':
            raise ValidationError('Only draft estimates can be marked as open.')
        estimate.status = 'open'
        estimate.save()

        # Finalize associated worksheet if draft
        worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
        if worksheet and worksheet.status == 'draft':
            worksheet.status = 'final'
            worksheet.save()

        return estimate

    @staticmethod
    @transaction.atomic
    def revise_estimate(pk):
        """Create a new revision of an estimate, copying line items and superseding parent."""
        try:
            parent = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        if parent.status == 'draft':
            raise ValidationError('Cannot revise a draft estimate. Edit it directly.')

        new_estimate = Estimate.objects.create(
            job=parent.job,
            estimate_number=parent.estimate_number,
            version=parent.version + 1,
            status='draft',
            parent=parent,
        )

        # Copy line items
        for li in EstimateLineItem.objects.filter(estimate=parent):
            EstimateLineItem.objects.create(
                estimate=new_estimate,
                task=li.task,
                price_list_item=li.price_list_item,
                qty=li.qty,
                units=li.units,
                description=li.description,
                price=li.price,
                line_item_type=li.line_item_type,
            )

        # Supersede parent
        parent.status = 'superseded'
        parent.save()

        return new_estimate

    @staticmethod
    def add_line_item(estimate_pk, **kwargs):
        """Add a manual line item to a draft estimate."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != 'draft':
            raise ValidationError('Can only add line items to draft estimates.')
        li = EstimateLineItem(estimate=estimate, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder an estimate line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = EstimateLineItem.objects.get(pk=line_item_id)
        except EstimateLineItem.DoesNotExist:
            raise NotFoundError(f'EstimateLineItem {line_item_id} not found')
        if li.estimate.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft estimate.'
            )
        return LineItemService.reorder_line_item(li, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete an estimate line item and renumber — validates draft status."""
        from apps.core.services import LineItemService
        try:
            li = EstimateLineItem.objects.get(pk=line_item_id)
        except EstimateLineItem.DoesNotExist:
            raise NotFoundError(f'EstimateLineItem {line_item_id} not found')
        if li.estimate.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft estimate.'
            )
        return LineItemService.delete_line_item_with_renumber(li)

    @staticmethod
    def add_line_item_from_pli(estimate_pk, pli_pk, qty):
        """Add a line item from a PriceListItem to a draft estimate."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != 'draft':
            raise ValidationError('Can only add line items to draft estimates.')
        try:
            pli = PriceListItem.objects.get(pk=pli_pk)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {pli_pk} not found')

        li = EstimateLineItem.objects.create(
            estimate=estimate,
            price_list_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            line_item_type=pli.line_item_type,
        )
        return li


class WorkOrderTemplateService:
    """Service for WorkOrderTemplate and TaskTemplate CRUD."""

    # --- WorkOrderTemplate ---

    @staticmethod
    def create_template(**kwargs):
        """Create a new WorkOrderTemplate."""
        tmpl = WorkOrderTemplate(**kwargs)
        tmpl.full_clean()
        tmpl.save()
        return tmpl

    @staticmethod
    def update_template(pk, **kwargs):
        """Update an existing WorkOrderTemplate by PK."""
        try:
            tmpl = WorkOrderTemplate.objects.get(pk=pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {pk} not found')
        for field, value in kwargs.items():
            setattr(tmpl, field, value)
        tmpl.full_clean()
        tmpl.save()
        return tmpl

    @staticmethod
    def delete_template(pk):
        """Delete a WorkOrderTemplate by PK."""
        try:
            tmpl = WorkOrderTemplate.objects.get(pk=pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {pk} not found')
        tmpl.delete()

    # --- TaskTemplate ---

    @staticmethod
    def create_task_template(**kwargs):
        """Create a new TaskTemplate."""
        tt = TaskTemplate(**kwargs)
        tt.full_clean()
        tt.save()
        return tt

    @staticmethod
    def update_task_template(pk, **kwargs):
        """Update an existing TaskTemplate by PK."""
        try:
            tt = TaskTemplate.objects.get(pk=pk)
        except TaskTemplate.DoesNotExist:
            raise NotFoundError(f'TaskTemplate {pk} not found')
        for field, value in kwargs.items():
            setattr(tt, field, value)
        tt.full_clean()
        tt.save()
        return tt

    @staticmethod
    def delete_task_template(pk):
        """Delete a TaskTemplate if not used in any WorkOrderTemplate."""
        try:
            tt = TaskTemplate.objects.get(pk=pk)
        except TaskTemplate.DoesNotExist:
            raise NotFoundError(f'TaskTemplate {pk} not found')
        if TemplateTaskAssociation.objects.filter(task_template=tt).exists():
            raise ValidationError(
                f'Task Template "{tt.template_name}" cannot be deleted '
                f'because it is used in one or more Work Order Templates.'
            )
        tt.delete()

    # --- Association management ---

    @staticmethod
    def delete_association(template_pk, assoc_pk):
        """Delete an unbundled association from a template."""
        try:
            tmpl = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_order_template=tmpl,
            )
        except TemplateTaskAssociation.DoesNotExist:
            raise NotFoundError(f'TemplateTaskAssociation {assoc_pk} not found')
        assoc.delete()

    # --- Bundling operations ---

    @staticmethod
    def bundle_associations(template_pk, assoc_ids, bundle_name, line_item_type,
                            description=''):
        """Bundle associations on a template. Requires >= 2 associations."""
        from apps.core.services import BundlingService
        from apps.estimates.models import TemplateBundle
        from django.db import models as db_models

        try:
            tmpl = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {template_pk} not found')
        if len(assoc_ids) < 2:
            raise ValidationError('Please select at least 2 tasks to bundle.')

        # Calculate next sort_order at container level
        max_assoc = TemplateTaskAssociation.objects.filter(
            work_order_template=tmpl, bundle__isnull=True,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        max_bundle = TemplateBundle.objects.filter(
            work_order_template=tmpl,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        next_sort = max(max_assoc, max_bundle) + 1

        bundle, _ = TemplateBundle.objects.get_or_create(
            work_order_template=tmpl, name=bundle_name,
            defaults={
                'description': description,
                'line_item_type': line_item_type,
                'sort_order': next_sort,
            },
        )

        selected = TemplateTaskAssociation.objects.filter(
            pk__in=assoc_ids, work_order_template=tmpl,
        ).order_by('sort_order', 'pk')
        BundlingService.bundle_items(selected, bundle)

        # Auto-dissolve other bundles that lost members
        all_bundles = TemplateBundle.objects.filter(work_order_template=tmpl)
        BundlingService.auto_dissolve_bundles(
            all_bundles, TemplateTaskAssociation, exclude_pk=bundle.pk,
        )

        return bundle

    @staticmethod
    def unbundle_association(template_pk, assoc_pk):
        """Unbundle an association from its bundle on a template."""
        from apps.core.services import BundlingService
        from apps.estimates.models import TemplateBundle

        try:
            tmpl = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_order_template=tmpl,
            )
        except TemplateTaskAssociation.DoesNotExist:
            raise NotFoundError(f'TemplateTaskAssociation {assoc_pk} not found')
        if assoc.mapping_strategy != 'bundle' or not assoc.bundle:
            return

        container_items_qs = TemplateTaskAssociation.objects.filter(
            work_order_template=tmpl, bundle__isnull=True,
        )
        container_bundles_qs = TemplateBundle.objects.filter(
            work_order_template=tmpl,
        )
        BundlingService.unbundle_item(assoc, container_items_qs, container_bundles_qs)

        BundlingService.auto_dissolve_bundles(
            TemplateBundle.objects.filter(work_order_template=tmpl),
            TemplateTaskAssociation,
        )

    @staticmethod
    def reorder_items(template_pk, item_type, item_id, direction):
        """Reorder items at container level on a template."""
        from apps.core.services import BundlingService

        try:
            tmpl = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {template_pk} not found')

        items_qs = TemplateTaskAssociation.objects.filter(
            work_order_template=tmpl,
        )
        BundlingService.reorder_container_items(
            items_qs, item_type, item_id, direction,
        )

    @staticmethod
    def reorder_in_bundle(template_pk, assoc_pk, direction):
        """Reorder an association within its bundle on a template."""
        from apps.core.services import BundlingService

        try:
            tmpl = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            raise NotFoundError(f'WorkOrderTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_order_template=tmpl,
                mapping_strategy='bundle', bundle__isnull=False,
            )
        except TemplateTaskAssociation.DoesNotExist:
            raise NotFoundError(f'TemplateTaskAssociation {assoc_pk} not found in bundle')
        bundle_items_qs = TemplateTaskAssociation.objects.filter(bundle=assoc.bundle)
        BundlingService.reorder_in_bundle(bundle_items_qs, assoc, direction)


class WorksheetService:
    """Service for EstWorksheet operations."""

    @staticmethod
    def create_worksheet(job_pk, **kwargs):
        """Create a new draft EstWorksheet for a job."""
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')
        ws = EstWorksheet(job=job, status='draft', **kwargs)
        ws.save()
        return ws

    @staticmethod
    def revise_worksheet(pk):
        """Create a new revision of a worksheet using the model's create_new_version."""
        try:
            ws = EstWorksheet.objects.get(pk=pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {pk} not found')
        return ws.create_new_version()

    @staticmethod
    def add_task_from_template(worksheet_pk, template_pk, est_qty=Decimal('1.00')):
        """Add a task to a draft worksheet from a TaskTemplate."""
        from apps.jobs.models import Task
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError(
                f'Cannot add tasks to a {ws.get_status_display().lower()} worksheet.'
            )
        try:
            tt = TaskTemplate.objects.get(pk=template_pk)
        except TaskTemplate.DoesNotExist:
            raise NotFoundError(f'TaskTemplate {template_pk} not found')

        task = Task.objects.create(
            name=tt.template_name,
            description=tt.description,
            line_item_type=tt.line_item_type,
            est_worksheet=ws,
            est_qty=est_qty,
            units=tt.units,
            rate=tt.rate,
        )
        return task

    @staticmethod
    def add_task_manual(worksheet_pk, **kwargs):
        """Add a task manually to a draft worksheet."""
        from apps.jobs.models import Task
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError(
                f'Cannot add tasks to a {ws.get_status_display().lower()} worksheet.'
            )
        task = Task(est_worksheet=ws, **kwargs)
        task.full_clean()
        task.save()
        return task

    @staticmethod
    def bundle_tasks(worksheet_pk, task_ids, bundle_name, line_item_type,
                     description=''):
        """Bundle tasks on a draft worksheet. Requires >= 2 tasks."""
        from apps.jobs.models import Task, TaskBundle
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError('Cannot bundle tasks on a non-draft worksheet.')
        if len(task_ids) < 2:
            raise ValidationError('Please select at least 2 tasks to bundle.')

        # Get or create the bundle
        from django.db import models as db_models
        max_task = Task.objects.filter(
            est_worksheet=ws, bundle__isnull=True,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        max_bundle = TaskBundle.objects.filter(
            est_worksheet=ws,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        next_sort = max(max_task, max_bundle) + 1

        bundle, _ = TaskBundle.objects.get_or_create(
            est_worksheet=ws, name=bundle_name,
            defaults={
                'description': description,
                'line_item_type': line_item_type,
                'sort_order': next_sort,
            },
        )

        selected = Task.objects.filter(
            task_id__in=task_ids, est_worksheet=ws,
        ).order_by('sort_order', 'task_id')
        BundlingService.bundle_items(selected, bundle)

        # Auto-dissolve other bundles that lost members
        all_bundles = TaskBundle.objects.filter(est_worksheet=ws)
        BundlingService.auto_dissolve_bundles(all_bundles, Task, exclude_pk=bundle.pk)

        return bundle

    @staticmethod
    def unbundle_task(worksheet_pk, task_pk):
        """Unbundle a task from its bundle on a draft worksheet."""
        from apps.jobs.models import Task, TaskBundle
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError('Cannot unbundle tasks on a non-draft worksheet.')
        try:
            task = Task.objects.get(pk=task_pk, est_worksheet=ws)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_pk} not found')
        if task.mapping_strategy != 'bundle' or not task.bundle:
            return  # Nothing to unbundle

        container_items_qs = Task.objects.filter(
            est_worksheet=ws, bundle__isnull=True,
        )
        container_bundles_qs = TaskBundle.objects.filter(est_worksheet=ws)
        BundlingService.unbundle_item(task, container_items_qs, container_bundles_qs)

        # Auto-dissolve bundles that may now have 0 or 1 items
        BundlingService.auto_dissolve_bundles(
            TaskBundle.objects.filter(est_worksheet=ws), Task,
        )

    @staticmethod
    def reorder_items(worksheet_pk, item_type, item_id, direction):
        """Reorder items at container level on a draft worksheet."""
        from apps.jobs.models import Task, TaskBundle
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError('Cannot reorder on a non-draft worksheet.')

        items_qs = Task.objects.filter(est_worksheet=ws)
        BundlingService.reorder_container_items(
            items_qs, item_type, item_id, direction,
        )

    @staticmethod
    def reorder_in_bundle(worksheet_pk, task_pk, direction):
        """Reorder a task within its bundle on a draft worksheet."""
        from apps.jobs.models import Task
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError('Cannot reorder on a non-draft worksheet.')
        try:
            task = Task.objects.get(
                pk=task_pk, est_worksheet=ws,
                mapping_strategy='bundle', bundle__isnull=False,
            )
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_pk} not found in bundle')
        bundle_items_qs = Task.objects.filter(bundle=task.bundle)
        BundlingService.reorder_in_bundle(bundle_items_qs, task, direction)

    @staticmethod
    def finalize(worksheet_pk):
        """Mark a draft worksheet as final."""
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != 'draft':
            raise ValidationError(
                f'Cannot finalize a {ws.get_status_display().lower()} worksheet.'
            )
        ws.status = 'final'
        ws.save()
        return ws


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
