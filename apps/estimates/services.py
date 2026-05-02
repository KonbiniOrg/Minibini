"""
Service classes for Estimate generation and management.
"""

from decimal import Decimal

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

        # Copy line items (source rows are NOT carried forward; the new revision
        # gets fresh atoms via worksheet revision or manual adds)
        for li in EstimateLineItem.objects.filter(estimate=parent):
            EstimateLineItem.objects.create(
                estimate=new_estimate,
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
        """Delete an association from a template."""
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
    def add_task_from_template(
        worksheet_pk, template_pk,
        est_qty=Decimal('1.00'),
        rate_scheme_id=None,
        active_modifiers=None,
        estimated_billable_qty=None,
    ):
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
            # Legacy fields — preserved while present (Task 13 removes them).
            est_qty=est_qty,
            units=tt.units,
            rate=tt.rate,
            # New atom billing fields — fall back to template defaults when not provided.
            rate_scheme_id=rate_scheme_id if rate_scheme_id else tt.rate_scheme_id,
            active_modifiers=active_modifiers if active_modifiers is not None else (tt.default_active_modifiers or []),
            estimated_billable_qty=estimated_billable_qty if estimated_billable_qty is not None else tt.default_billable_qty,
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
        """Convert {'type': 'plan_task'|'plan_material', 'id': N} to a model instance."""
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        atom_type = atom_ref.get('type')
        atom_id = atom_ref.get('id')
        if atom_type == 'plan_task':
            try:
                return PlanTask.objects.get(pk=atom_id)
            except PlanTask.DoesNotExist:
                raise ValidationError(f'PlanTask {atom_id} not found')
        if atom_type == 'plan_material':
            try:
                return PlanMaterial.objects.get(pk=atom_id)
            except PlanMaterial.DoesNotExist:
                raise ValidationError(f'PlanMaterial {atom_id} not found')
        raise ValidationError(f'Unknown atom type: {atom_type}')

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        from apps.estimates.models import EstimateLineItemSource
        if isinstance(atom_instance, PlanTask):
            return EstimateLineItemSource.SOURCE_PLAN_TASK
        if isinstance(atom_instance, PlanMaterial):
            return EstimateLineItemSource.SOURCE_PLAN_MATERIAL
        raise ValueError(f'Unknown atom instance type: {type(atom_instance)}')

    @staticmethod
    def _atom_category(atom_instance):
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanTask):
            return atom_instance.accounting_category
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_description(atom_instance):
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanTask):
            return atom_instance.name
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.description
        return ''

    @staticmethod
    def _atom_units(atom_instance):
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanTask):
            if atom_instance.rate_scheme_id:
                return atom_instance.rate_scheme.unit_label
            return 'each'
        if isinstance(atom_instance, PlanMaterial):
            return 'each'
        return 'each'

    @staticmethod
    def get_source_pool(worksheet):
        """Walk the worksheet's atoms and return a flat pool with claim state.

        Returns: {'atoms': [
            {'type': 'plan_task'|'plan_material', 'id': N, 'description': str,
             'amount': Decimal, 'state': 'available'|'claimed_by_current'|'claimed_by_other',
             'category_id': N or None, 'units': str}
        ]}
        """
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import PlanTask
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

        for pt in PlanTask.objects.filter(est_worksheet=worksheet).select_related(
            'accounting_category', 'rate_scheme',
        ):
            key = (EstimateLineItemSource.SOURCE_PLAN_TASK, pt.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_task',
                'id': pt.pk,
                'description': pt.name,
                'amount': pt.compute_amount().quantize(Decimal('0.01')),
                'units': EstimateWizardService._atom_units(pt),
                'category_id': pt.accounting_category_id,
                **state_info,
            })

        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
            key = (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_material',
                'id': pm.pk,
                'description': pm.description,
                'amount': pm.compute_amount().quantize(Decimal('0.01')),
                'units': 'each',
                'category_id': pm.accounting_category_id,
                **state_info,
            })

        return {'atoms': atoms}

    @staticmethod
    def add_atoms_to_new_line_item(estimate, atoms):
        """Create a new EstimateLineItem on `estimate` with the given atoms as sources.

        atoms: list of {'type': 'plan_task'|'plan_material', 'id': N} dicts.
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

    @staticmethod
    def _sum_sources(line_item):
        """Sum the computed amounts of all source atoms on a line item."""
        total = Decimal('0.00')
        for src in line_item.sources.all():
            instance = src.resolve()
            total += instance.compute_amount()
        return total

    @staticmethod
    def _expected_per_unit(sum_value, qty):
        """The per-unit price the wizard would compute right now: round(sum/qty, 2)."""
        if not qty:
            return Decimal('0.00')
        return (sum_value / qty).quantize(Decimal('0.01'))

    @staticmethod
    def _is_in_sync(line_item, sum_value):
        """In sync iff price == round(sum / qty, 2)."""
        if not line_item.qty:
            return False
        return line_item.price == EstimateWizardService._expected_per_unit(sum_value, line_item.qty)

    @staticmethod
    def add_atoms_to_line_item(line_item, atoms):
        """Append N atoms as sources to an existing line item.

        Recomputes the line item's price if it was in sync before the operation;
        preserves an overridden price otherwise.
        """
        from django.db import IntegrityError
        from apps.estimates.models import EstimateLineItemSource

        EstimateWizardService._validate_draft_estimate(line_item.estimate)

        old_sum = EstimateWizardService._sum_sources(line_item)
        was_in_sync = EstimateWizardService._is_in_sync(line_item, old_sum)

        instances = [EstimateWizardService._resolve_atom(a) for a in atoms]

        try:
            with transaction.atomic():
                for instance in instances:
                    EstimateLineItemSource.objects.create(
                        estimate_line_item=line_item,
                        source_type=EstimateWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
                if was_in_sync:
                    new_sum = EstimateWizardService._sum_sources(line_item)
                    line_item.price = EstimateWizardService._expected_per_unit(new_sum, line_item.qty)
                    line_item.save()
        except IntegrityError:
            existing = set(
                EstimateLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [a for a in atoms if (a['type'], a['id']) in existing]
            raise EstimateClaimConflict(atom_ids=conflicts)

        return line_item

    @staticmethod
    def remove_atoms_from_line_item(line_item, source_ids):
        """Remove a subset of source rows from a line item.

        - Recomputes price if the line item was in sync before.
        - Preserves price if it was overridden.
        - Deletes the line item if all sources are removed.

        Returns: {'line_item_deleted': bool}
        """
        EstimateWizardService._validate_draft_estimate(line_item.estimate)

        old_sum = EstimateWizardService._sum_sources(line_item)
        was_in_sync = EstimateWizardService._is_in_sync(line_item, old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                line_item.delete()
                return {'line_item_deleted': True}

            if was_in_sync:
                new_sum = EstimateWizardService._sum_sources(line_item)
                line_item.price = EstimateWizardService._expected_per_unit(new_sum, line_item.qty)
                line_item.save()

        return {'line_item_deleted': False}

    @staticmethod
    def send_all_atoms_to_estimate(worksheet):
        """Bulk 1:1 conversion of unclaimed atoms on the worksheet to EstimateLineItems.

        Iterates all PlanTasks and PlanMaterials on the worksheet that aren't yet
        claimed by any EstimateLineItemSource, and creates one EstimateLineItem per
        atom (with one source row pointing at the atom).

        Deliberately NOT wrapped in a transaction: if one atom fails (e.g. concurrent
        claim), the successful conversions are kept so the caller can re-run to finish.

        Returns: {'estimate': Estimate, 'created_count': int}
        """
        from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial

        estimate = EstimateWizardService.open_for_worksheet(worksheet)
        EstimateWizardService._validate_draft_estimate(estimate)

        # Build set of currently-claimed (type, pk) pairs, scoped to this job's estimates
        claimed = set(
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=worksheet.job)
            .values_list('source_type', 'source_pk')
        )

        created_count = 0

        # PlanTasks
        for pt in PlanTask.objects.filter(est_worksheet=worksheet).select_related(
            'accounting_category', 'rate_scheme',
        ):
            if (EstimateLineItemSource.SOURCE_PLAN_TASK, pt.pk) in claimed:
                continue
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pt.name,
                qty=Decimal('1'),
                units=EstimateWizardService._atom_units(pt),
                price=pt.compute_amount().quantize(Decimal('0.01')),
                accounting_category=pt.accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
                source_pk=pt.pk,
            )
            created_count += 1

        # PlanMaterials
        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
            if (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk) in claimed:
                continue
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pm.description,
                qty=Decimal('1'),
                units='each',
                price=pm.compute_amount().quantize(Decimal('0.01')),
                accounting_category=pm.accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
                source_pk=pm.pk,
            )
            created_count += 1

        return {'estimate': estimate, 'created_count': created_count}
