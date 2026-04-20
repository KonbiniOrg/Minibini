"""
Service classes for Estimate generation and management.
"""

from decimal import Decimal
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
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
            status=Estimate.STATUS_DRAFT,
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
            status=Estimate.STATUS_DRAFT,
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
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Only draft estimates can be marked as open.')
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        # Finalize associated worksheet if draft
        worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
        if worksheet and worksheet.status == EstWorksheet.STATUS_DRAFT:
            worksheet.status = EstWorksheet.STATUS_FINAL
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
        if parent.status == Estimate.STATUS_DRAFT:
            raise ValidationError('Cannot revise a draft estimate. Edit it directly.')

        new_estimate = Estimate.objects.create(
            job=parent.job,
            estimate_number=parent.estimate_number,
            version=parent.version + 1,
            status=Estimate.STATUS_DRAFT,
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
                accounting_category=li.accounting_category,
            )

        # Supersede parent
        parent.status = Estimate.STATUS_SUPERSEDED
        parent.save()

        return new_estimate

    @staticmethod
    def add_line_item(estimate_pk, **kwargs):
        """Add a manual line item to a draft estimate."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft estimates.')
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(EstimateLineItem, kwargs)
        li = EstimateLineItem(estimate=estimate, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update an estimate line item — validates draft status."""
        try:
            li = EstimateLineItem.objects.get(pk=line_item_id)
        except EstimateLineItem.DoesNotExist:
            raise NotFoundError(f'EstimateLineItem {line_item_id} not found')
        if li.estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only modify line items on draft estimates.')
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(EstimateLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(estimate_pk, item_ids):
        """Reorder estimate line items by position list — validates draft status."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only modify line items on draft estimates.')
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                EstimateLineItem.objects.filter(
                    pk=item_id, estimate=estimate,
                ).update(line_number=position)

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder an estimate line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = EstimateLineItem.objects.get(pk=line_item_id)
        except EstimateLineItem.DoesNotExist:
            raise NotFoundError(f'EstimateLineItem {line_item_id} not found')
        if li.estimate.status != Estimate.STATUS_DRAFT:
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
        if li.estimate.status != Estimate.STATUS_DRAFT:
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
        if estimate.status != Estimate.STATUS_DRAFT:
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
            accounting_category=pli.accounting_category,
        )
        return li


class WorkTemplateService:
    """Service for WorkTemplate and TaskTemplate CRUD."""

    # --- WorkTemplate ---

    @staticmethod
    def create_template(**kwargs):
        """Create a new WorkTemplate."""
        tmpl = WorkTemplate(**kwargs)
        tmpl.full_clean()
        tmpl.save()
        return tmpl

    @staticmethod
    def update_template(pk, **kwargs):
        """Update an existing WorkTemplate by PK."""
        try:
            tmpl = WorkTemplate.objects.get(pk=pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {pk} not found')
        for field, value in kwargs.items():
            setattr(tmpl, field, value)
        tmpl.full_clean()
        tmpl.save()
        return tmpl

    @staticmethod
    def delete_template(pk):
        """Delete a WorkTemplate by PK."""
        try:
            tmpl = WorkTemplate.objects.get(pk=pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {pk} not found')
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
        """Delete a TaskTemplate if not used in any WorkTemplate."""
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
            tmpl = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_template=tmpl,
            )
        except TemplateTaskAssociation.DoesNotExist:
            raise NotFoundError(f'TemplateTaskAssociation {assoc_pk} not found')
        assoc.delete()

    # --- Bundling operations ---

    @staticmethod
    def bundle_associations(template_pk, assoc_ids, bundle_name, accounting_category):
        """Bundle associations on a template. Requires >= 2 associations."""
        from apps.core.services import BundlingService
        from apps.estimates.models import TemplateBundle
        from django.db import models as db_models

        try:
            tmpl = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {template_pk} not found')
        if len(assoc_ids) < 2:
            raise ValidationError('Please select at least 2 tasks to bundle.')

        # Calculate next sort_order at container level
        max_assoc = TemplateTaskAssociation.objects.filter(
            work_template=tmpl, bundle__isnull=True,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        max_bundle = TemplateBundle.objects.filter(
            work_template=tmpl,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        next_sort = max(max_assoc, max_bundle) + 1

        bundle, _ = TemplateBundle.objects.get_or_create(
            work_template=tmpl, name=bundle_name,
            defaults={
                'accounting_category': accounting_category,
                'sort_order': next_sort,
            },
        )

        selected = TemplateTaskAssociation.objects.filter(
            pk__in=assoc_ids, work_template=tmpl,
        ).order_by('sort_order', 'pk')
        BundlingService.bundle_items(selected, bundle)

        # Auto-dissolve other bundles that lost members
        all_bundles = TemplateBundle.objects.filter(work_template=tmpl)
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
            tmpl = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_template=tmpl,
            )
        except TemplateTaskAssociation.DoesNotExist:
            raise NotFoundError(f'TemplateTaskAssociation {assoc_pk} not found')
        if assoc.mapping_strategy != 'bundle' or not assoc.bundle:
            return

        container_items_qs = TemplateTaskAssociation.objects.filter(
            work_template=tmpl, bundle__isnull=True,
        )
        container_bundles_qs = TemplateBundle.objects.filter(
            work_template=tmpl,
        )
        BundlingService.unbundle_item(assoc, container_items_qs, container_bundles_qs)

        BundlingService.auto_dissolve_bundles(
            TemplateBundle.objects.filter(work_template=tmpl),
            TemplateTaskAssociation,
        )

    @staticmethod
    def reorder_items(template_pk, item_type, item_id, direction):
        """Reorder items at container level on a template."""
        from apps.core.services import BundlingService

        try:
            tmpl = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {template_pk} not found')

        items_qs = TemplateTaskAssociation.objects.filter(
            work_template=tmpl,
        )
        BundlingService.reorder_container_items(
            items_qs, item_type, item_id, direction,
        )

    @staticmethod
    def reorder_in_bundle(template_pk, assoc_pk, direction):
        """Reorder an association within its bundle on a template."""
        from apps.core.services import BundlingService

        try:
            tmpl = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            raise NotFoundError(f'WorkTemplate {template_pk} not found')
        try:
            assoc = TemplateTaskAssociation.objects.get(
                pk=assoc_pk, work_template=tmpl,
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
        ws = EstWorksheet(job=job, status=EstWorksheet.STATUS_DRAFT, **kwargs)
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
        """Add a PlanTask to a draft worksheet from a TaskTemplate."""
        from apps.jobs.models import PlanTask
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot add tasks to a {ws.get_status_display().lower()} worksheet.'
            )
        try:
            tt = TaskTemplate.objects.get(pk=template_pk)
        except TaskTemplate.DoesNotExist:
            raise NotFoundError(f'TaskTemplate {template_pk} not found')

        task = PlanTask.objects.create(
            name=tt.template_name,
            description=tt.description,
            accounting_category=tt.accounting_category,
            est_worksheet=ws,
            est_qty=est_qty,
            units=tt.units,
            rate=tt.rate,
        )
        return task

    @staticmethod
    def add_task_manual(worksheet_pk, **kwargs):
        """Add a PlanTask manually to a draft worksheet."""
        from apps.jobs.models import PlanTask
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot add tasks to a {ws.get_status_display().lower()} worksheet.'
            )
        task = PlanTask(est_worksheet=ws, **kwargs)
        task.full_clean()
        task.save()
        return task

    @staticmethod
    def bundle_tasks(worksheet_pk, task_ids, bundle_name, accounting_category):
        """Bundle PlanTasks on a draft worksheet. Requires >= 2 tasks."""
        from apps.jobs.models import PlanTask, PlanBundle
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError('Cannot bundle tasks on a non-draft worksheet.')
        if len(task_ids) < 2:
            raise ValidationError('Please select at least 2 tasks to bundle.')

        # Get or create the bundle
        from django.db import models as db_models
        max_task = PlanTask.objects.filter(
            est_worksheet=ws, bundle__isnull=True,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        max_bundle = PlanBundle.objects.filter(
            est_worksheet=ws,
        ).aggregate(db_models.Max('sort_order'))['sort_order__max'] or 0
        next_sort = max(max_task, max_bundle) + 1

        bundle, _ = PlanBundle.objects.get_or_create(
            est_worksheet=ws, name=bundle_name,
            defaults={
                'accounting_category': accounting_category,
                'sort_order': next_sort,
            },
        )

        selected = PlanTask.objects.filter(
            plan_task_id__in=task_ids, est_worksheet=ws,
        ).order_by('sort_order', 'plan_task_id')
        BundlingService.bundle_items(selected, bundle)

        # Auto-dissolve other bundles that lost members
        all_bundles = PlanBundle.objects.filter(est_worksheet=ws)
        BundlingService.auto_dissolve_bundles(all_bundles, PlanTask, exclude_pk=bundle.pk)

        return bundle

    @staticmethod
    def unbundle_task(worksheet_pk, task_pk):
        """Unbundle a PlanTask from its bundle on a draft worksheet."""
        from apps.jobs.models import PlanTask, PlanBundle
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError('Cannot unbundle tasks on a non-draft worksheet.')
        try:
            task = PlanTask.objects.get(pk=task_pk, est_worksheet=ws)
        except PlanTask.DoesNotExist:
            raise NotFoundError(f'PlanTask {task_pk} not found')
        if task.mapping_strategy != 'bundle' or not task.bundle:
            return  # Nothing to unbundle

        container_items_qs = PlanTask.objects.filter(
            est_worksheet=ws, bundle__isnull=True,
        )
        container_bundles_qs = PlanBundle.objects.filter(est_worksheet=ws)
        BundlingService.unbundle_item(task, container_items_qs, container_bundles_qs)

        # Auto-dissolve bundles that may now have 0 or 1 items
        BundlingService.auto_dissolve_bundles(
            PlanBundle.objects.filter(est_worksheet=ws), PlanTask,
        )

    @staticmethod
    def reorder_items(worksheet_pk, item_type, item_id, direction):
        """Reorder PlanTasks at container level on a draft worksheet."""
        from apps.jobs.models import PlanTask
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError('Cannot reorder on a non-draft worksheet.')

        items_qs = PlanTask.objects.filter(est_worksheet=ws)
        BundlingService.reorder_container_items(
            items_qs, item_type, item_id, direction,
        )

    @staticmethod
    def reorder_in_bundle(worksheet_pk, task_pk, direction):
        """Reorder a PlanTask within its bundle on a draft worksheet."""
        from apps.jobs.models import PlanTask
        from apps.core.services import BundlingService
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError('Cannot reorder on a non-draft worksheet.')
        try:
            task = PlanTask.objects.get(
                pk=task_pk, est_worksheet=ws,
                mapping_strategy='bundle', bundle__isnull=False,
            )
        except PlanTask.DoesNotExist:
            raise NotFoundError(f'PlanTask {task_pk} not found in bundle')
        bundle_items_qs = PlanTask.objects.filter(bundle=task.bundle)
        BundlingService.reorder_in_bundle(bundle_items_qs, task, direction)

    @staticmethod
    def finalize(worksheet_pk):
        """Mark a draft worksheet as final."""
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot finalize a {ws.get_status_display().lower()} worksheet.'
            )
        ws.status = EstWorksheet.STATUS_FINAL
        ws.save()
        return ws


class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates using instance-level bundling."""

    def __init__(self):
        self.line_number = 1
        self._default_accounting_category = None

    def _get_default_accounting_category(self):
        """Get a fallback AccountingCategory when none is available from the source object."""
        if self._default_accounting_category is None:
            from apps.core.models import AccountingCategory
            self._default_accounting_category = AccountingCategory.objects.filter(is_active=True).first()
        return self._default_accounting_category

    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet) -> 'Estimate':
        """
        Convert EstWorksheet to Estimate using instance-level mapping config.

        Tasks are processed based on their own mapping_strategy field:
        - 'direct': Task becomes its own line item
        - 'bundle': Tasks in same PlanBundle are combined into one line item
        - 'exclude': Task is not included on estimate
        """
        plan_tasks = worksheet.plan_tasks.select_related('bundle').prefetch_related('plan_materials').all()

        if not plan_tasks:
            raise ValueError(f"EstWorksheet {worksheet.pk} has no tasks to convert")

        # Create the estimate
        estimate = self._create_estimate(worksheet)

        # Categorize plan tasks by their instance-level mapping strategy
        direct_tasks = []
        bundles = defaultdict(list)  # bundle_id -> [plan tasks]

        for plan_task in plan_tasks:
            if plan_task.mapping_strategy == 'exclude':
                continue
            elif plan_task.mapping_strategy == 'bundle' and plan_task.bundle:
                bundles[plan_task.bundle_id].append(plan_task)
            else:
                direct_tasks.append(plan_task)

        # Generate line items
        line_items = []

        # Process bundled plan tasks
        for bundle_id, bundle_tasks in bundles.items():
            plan_bundle = bundle_tasks[0].bundle
            line_item = self._create_bundle_line_item(bundle_tasks, plan_bundle, estimate)
            line_items.append(line_item)

        # Process direct plan tasks
        for plan_task in direct_tasks:
            has_materials = plan_task.plan_materials.exists()
            is_pass_through = (not plan_task.rate or plan_task.rate == Decimal('0.00')) and has_materials

            # Skip labor line item for pass-through tasks (no rate, only materials)
            if not is_pass_through:
                line_item = self._create_direct_line_item(plan_task, estimate)
                line_items.append(line_item)

            # Create material line items for each plan material on direct plan tasks
            for plan_material in plan_task.plan_materials.all():
                mat_li = self._create_material_line_item(plan_material, estimate)
                line_items.append(mat_li)

        # Task-less plan materials (attached to worksheet but no plan_task)
        for pm in worksheet.plan_materials.filter(plan_task__isnull=True):
            line_items.append(self._create_material_line_item(pm, estimate))

        # Bulk create all line items
        if line_items:
            EstimateLineItem.objects.bulk_create(line_items)

        # Link worksheet to estimate and finalize
        worksheet.estimate = estimate
        worksheet.save()
        if worksheet.status == EstWorksheet.STATUS_DRAFT:
            WorksheetService.finalize(worksheet.pk)

        return estimate

    def _create_estimate(self, worksheet) -> 'Estimate':
        """Create a new estimate for the worksheet's job."""
        version = 1
        parent_estimate = None

        if worksheet.parent and worksheet.parent.estimate:
            parent_estimate = worksheet.parent.estimate
            estimate_number = parent_estimate.estimate_number
            version = parent_estimate.version + 1
            parent_estimate.status = Estimate.STATUS_SUPERSEDED
            parent_estimate.save()
        else:
            estimate_number = NumberGenerationService.generate_next_number('estimate')

        estimate = Estimate.objects.create(
            job=worksheet.job,
            estimate_number=estimate_number,
            version=version,
            parent=parent_estimate,
            status=Estimate.STATUS_DRAFT
        )

        return estimate

    def _create_direct_line_item(self, task, estimate) -> 'EstimateLineItem':
        """Create a line item for a direct-mapped task.
        Uses PlanCharge if available; falls back to task fields."""
        from apps.jobs.models import PlanCharge
        try:
            charge = task.charge
            qty = charge.estimated_billable_qty
            rate = charge.effective_rate()
            units = charge.rate_scheme.unit_label
        except (PlanCharge.DoesNotExist, AttributeError):
            qty = task.est_qty or Decimal('1.00')
            rate = task.rate or Decimal('0.00')
            units = task.units or 'none'

        # Get accounting_category from task directly
        accounting_category = task.accounting_category

        if accounting_category is None:
            accounting_category = self._get_default_accounting_category()

        line_item = EstimateLineItem(
            estimate=estimate,
            task=task,
            line_number=self.line_number,
            description=task.name,
            qty=qty,
            units=units,
            price=rate,
            accounting_category=accounting_category
        )

        self.line_number += 1
        return line_item

    def _create_material_line_item(self, material, estimate) -> 'EstimateLineItem':
        """Create a line item for a material on a direct-mapped task."""
        # Derive accounting_category: PLI first, then material's own field, then fallback
        accounting_category = None
        if material.price_list_item:
            accounting_category = material.price_list_item.accounting_category
        if accounting_category is None:
            accounting_category = material.accounting_category
        if accounting_category is None:
            accounting_category = self._get_default_accounting_category()

        line_item = EstimateLineItem(
            estimate=estimate,
            material=material,
            line_number=self.line_number,
            description=material.description,
            qty=material.quantity,
            units='none',
            price=material.sell_price,
            accounting_category=accounting_category,
        )

        self.line_number += 1
        return line_item

    def _create_bundle_line_item(self, tasks, bundle, estimate) -> 'EstimateLineItem':
        """Create a single line item for bundled tasks, including material costs."""
        from apps.jobs.models import PlanCharge
        total_price = Decimal('0.00')

        for task in tasks:
            try:
                charge = task.charge
                qty = charge.estimated_billable_qty
                rate = charge.effective_rate()
            except (PlanCharge.DoesNotExist, AttributeError):
                qty = task.est_qty or Decimal('1.00')
                rate = task.rate or Decimal('0.00')
            total_price += qty * rate
            # Add material sell totals to bundle price
            for material in task.plan_materials.all():
                total_price += material.total_sell

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=bundle.name,
            qty=Decimal('1.00'),
            units='none',
            price=total_price,
            accounting_category=bundle.accounting_category
        )

        self.line_number += 1
        return line_item


class EstimateClaimConflict(Exception):
    """Raised when the estimate wizard tries to claim an atom already claimed elsewhere."""

    def __init__(self, atom_ids):
        self.atom_ids = atom_ids
        super().__init__(f'Atoms already claimed: {atom_ids}')


class EstimateWizardService:
    """Orchestration layer for the estimate wizard.

    Mirrors InvoiceWizardService shape. Composes on top of EstimateService rather
    than replacing it; manual line-item CRUD continues to use EstimateService.
    """

    @staticmethod
    def _validate_draft_worksheet(worksheet):
        from apps.estimates.models import EstWorksheet
        if worksheet.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot run wizard on worksheet in status "{worksheet.status}". '
                f'Worksheet must be in draft.'
            )

    @staticmethod
    def _validate_draft_estimate(estimate):
        from apps.estimates.models import Estimate
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot modify line items on estimate in status "{estimate.status}".'
            )

    @staticmethod
    def open_for_worksheet(worksheet):
        """Return the worksheet's draft Estimate, creating one if none exists.

        Raises ValidationError if the worksheet is not in draft.
        """
        from apps.estimates.models import Estimate
        EstimateWizardService._validate_draft_worksheet(worksheet)

        if worksheet.estimate and worksheet.estimate.status == Estimate.STATUS_DRAFT:
            return worksheet.estimate

        with transaction.atomic():
            estimate_number = NumberGenerationService.generate_next_number('estimate')
            estimate = Estimate.objects.create(
                job=worksheet.job,
                estimate_number=estimate_number,
                status=Estimate.STATUS_DRAFT,
            )
            worksheet.estimate = estimate
            worksheet.save()
        return estimate

    @staticmethod
    def _resolve_atom(atom_ref):
        """Convert {'type': 'plan_charge'|'plan_material', 'id': N} to a model instance."""
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        atom_type = atom_ref.get('type')
        atom_id = atom_ref.get('id')
        if atom_type == 'plan_charge':
            try:
                return PlanCharge.objects.get(pk=atom_id)
            except PlanCharge.DoesNotExist:
                raise ValidationError(f'PlanCharge {atom_id} not found')
        if atom_type == 'plan_material':
            try:
                return PlanMaterial.objects.get(pk=atom_id)
            except PlanMaterial.DoesNotExist:
                raise ValidationError(f'PlanMaterial {atom_id} not found')
        raise ValidationError(f'Unknown atom type: {atom_type}')

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        from apps.estimates.models import EstimateLineItemSource
        if isinstance(atom_instance, PlanCharge):
            return EstimateLineItemSource.SOURCE_PLAN_CHARGE
        if isinstance(atom_instance, PlanMaterial):
            return EstimateLineItemSource.SOURCE_PLAN_MATERIAL
        raise ValueError(f'Unknown atom instance type: {type(atom_instance)}')

    @staticmethod
    def _atom_category(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.accounting_category
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_description(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.name
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.description
        return ''

    @staticmethod
    def _atom_units(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.units
        if isinstance(atom_instance, PlanMaterial):
            return 'each'
        return 'each'

    @staticmethod
    def get_source_pool(worksheet):
        """Walk the worksheet's atoms and return a flat pool with claim state.

        Returns: {'atoms': [
            {'type': 'plan_charge'|'plan_material', 'id': N, 'description': str,
             'amount': Decimal, 'state': 'available'|'claimed_by_current'|'claimed_by_other',
             'category_id': N or None, 'units': str}
        ]}
        """
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial

        # Build the claim lookup: (source_type, source_pk) -> state info
        # Plan-side does NOT release on supersede, so we don't filter by status.
        claimed_sources = (
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=worksheet.job)
            .select_related('estimate_line_item', 'estimate_line_item__estimate')
        )
        current_estimate_pk = worksheet.estimate_id
        claims = {}
        for src in claimed_sources:
            li = src.estimate_line_item
            est = li.estimate
            key = (src.source_type, src.source_pk)
            if est.pk == current_estimate_pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_estimate_id': None,
                    'claiming_estimate_number': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_estimate_id': est.pk,
                    'claiming_estimate_number': est.estimate_number,
                }

        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_estimate_id': None,
            'claiming_estimate_number': None,
        }

        atoms = []

        for pc in PlanCharge.objects.filter(plan_task__est_worksheet=worksheet).select_related('plan_task', 'plan_task__accounting_category', 'rate_scheme'):
            key = (EstimateLineItemSource.SOURCE_PLAN_CHARGE, pc.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_charge',
                'id': pc.pk,
                'description': pc.plan_task.name,
                'amount': pc.compute_amount(),
                'units': pc.plan_task.units,
                'category_id': pc.plan_task.accounting_category_id,
                **state_info,
            })

        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
            key = (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_material',
                'id': pm.pk,
                'description': pm.description,
                'amount': pm.compute_amount(),
                'units': 'each',
                'category_id': pm.accounting_category_id,
                **state_info,
            })

        return {'atoms': atoms}

    @staticmethod
    def add_atoms_to_new_line_item(estimate, atoms):
        """Create a new EstimateLineItem on `estimate` with the given atoms as sources.

        atoms: list of {'type': 'plan_charge'|'plan_material', 'id': N} dicts.
        """
        from django.db import IntegrityError
        from apps.estimates.models import EstimateLineItem, EstimateLineItemSource

        EstimateWizardService._validate_draft_estimate(estimate)

        instances = [EstimateWizardService._resolve_atom(a) for a in atoms]

        total_price = sum(
            (i.compute_amount() for i in instances),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'))
        categories = {EstimateWizardService._atom_category(i) for i in instances}
        category = categories.pop() if len(categories) == 1 else None

        try:
            with transaction.atomic():
                line_item = EstimateLineItem.objects.create(
                    estimate=estimate,
                    description='',
                    qty=Decimal('1'),
                    units='each',
                    price=total_price,
                    accounting_category=category,
                )
                for instance in instances:
                    EstimateLineItemSource.objects.create(
                        estimate_line_item=line_item,
                        source_type=EstimateWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
        except IntegrityError:
            existing = set(
                EstimateLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [a for a in atoms if (a['type'], a['id']) in existing]
            raise EstimateClaimConflict(atom_ids=conflicts)

        return line_item
