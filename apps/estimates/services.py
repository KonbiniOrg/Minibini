"""
Service classes for Estimate generation and management.
"""

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.core.services import NumberGenerationService, NotFoundError
from apps.core.wizard import BaseWizardService
from apps.inventory.models import PriceListItem

logger = logging.getLogger(__name__)


class EstimateService:
    """Service class for Estimate creation and management."""

    @staticmethod
    def create_direct(job, **kwargs):
        """
        Create Estimate directly. Starts in 'draft' status.
        Estimate number is the job number plus the revision (one estimate tree
        per job): ``{job_number}-{version}``.
        """
        version = kwargs.pop('version', 1)
        estimate_number = kwargs.pop('estimate_number', f'{job.job_number}-{version}')
        return Estimate.objects.create(
            job=job,
            estimate_number=estimate_number,
            version=version,
            status=Estimate.STATUS_DRAFT,
            **kwargs
        )

    @staticmethod
    def create_for_job(job_pk):
        """Create a new draft Estimate for a job by PK.

        The estimate number derives from the job number plus the revision:
        ``{job_number}-1`` for the first version.
        """
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')

        estimate = Estimate.objects.create(
            job=job,
            estimate_number=f'{job.job_number}-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        return estimate

    @staticmethod
    def update_status(pk, new_status, actor=None):
        """Update estimate status. Model validates transitions.

        When ``actor`` is given (a dict describing a customer who acted via
        the portal link, e.g. ``{'contact_id': N, 'email': str,
        'reason': str|None}``), write an explicit, user-less action
        HistoryEntry recording the decision and the customer context.
        """
        try:
            estimate = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        old_status = estimate.status
        estimate.status = new_status
        estimate.save()  # Model.save() calls full_clean() and handles dates

        if actor:
            from apps.core.models import HistoryEntry
            label = {
                Estimate.STATUS_ACCEPTED: 'Accepted via customer link',
                Estimate.STATUS_REJECTED: 'Declined via customer link',
            }.get(new_status, f'{new_status} via customer link')
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='estimate',
                object_id=estimate.pk,
                user=None,
                changes={
                    'status': {'old': old_status, 'new': new_status},
                    '_action': label,
                    'contact_id': actor.get('contact_id'),
                    'customer_email': actor.get('email'),
                },
                text=actor.get('reason') or '',
            )
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

        # Guard: estimate cannot be sent without a non-empty Deliverables list.
        from apps.deliverables.models import Deliverable
        if not Deliverable.objects.filter(job=estimate.job).exists():
            raise ValidationError('Cannot send estimate: job has no deliverables.')

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        # The job's worksheet (if any) freezes automatically: editability is
        # derived from the now-sent estimate (WorksheetService.is_editable).

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

        new_version = parent.version + 1
        new_estimate = Estimate.objects.create(
            job=parent.job,
            estimate_number=f'{parent.job.job_number}-{new_version}',
            version=new_version,
            status=Estimate.STATUS_DRAFT,
            parent=parent,
        )

        # Copy line items, MOVING each line's source rows (atom claims) onto the
        # revision so it stays worksheet-backed and the atom remains claimed
        # exactly once. (Copying the rows would violate EstimateLineItemSource's
        # unique_together on the atom.) source_template is copied too so a
        # catalog-backed line keeps its origin for carry-over.
        for li in EstimateLineItem.objects.filter(estimate=parent):
            new_li = EstimateLineItem.objects.create(
                estimate=new_estimate,
                price_list_item=li.price_list_item,
                source_template=li.source_template,
                qty=li.qty,
                units=li.units,
                description=li.description,
                price=li.price,
                accounting_category=li.accounting_category,
            )
            for src in li.sources.all():
                src.estimate_line_item = new_li
                src.save()

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
    def discard_draft(estimate):
        """Hard-delete a draft estimate; cascades to line items and sources."""
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot discard estimate in status "{estimate.status}". '
                f'Estimate must be in draft.'
            )
        estimate.delete()

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


class EstimateEmailService:
    """Sends an Estimate as a PDF attachment via email. Transitions the
    Estimate to STATUS_OPEN on send success."""

    DEFAULT_SUBJECT = 'Estimate {document_number}'
    DEFAULT_BODY = (
        'Hi {contact_fname},\n\n'
        'Please find attached our estimate {document_number} for {job_name}. '
        'You can review it and accept or decline it online here:\n'
        '{object_url}\n\n'
        'Let us know if you have any questions.\n\n'
        'Thanks,\n{my_user_name}'
    )

    @staticmethod
    def get_email_defaults(estimate):
        """Pre-populated send-form fields for an Estimate: to, subject,
        body, attachments_preview."""
        from apps.core.models import Configuration
        from apps.core.email_templates import render_email_template

        subject_template = EstimateEmailService.DEFAULT_SUBJECT
        body_template = EstimateEmailService.DEFAULT_BODY
        try:
            subject_template = Configuration.objects.get(
                key='estimate_email_subject_template'
            ).value
        except Configuration.DoesNotExist:
            pass
        try:
            body_template = Configuration.objects.get(
                key='estimate_email_body_template'
            ).value
        except Configuration.DoesNotExist:
            pass
        job = estimate.job
        contact = job.contact if job else None
        contact_business = ''
        if contact and contact.business:
            contact_business = contact.business.business_name

        from apps.core.email_templates import build_object_url
        values = {
            'contact_fname': contact.first_name if contact else '',
            'contact_lname': contact.last_name if contact else '',
            'contact_business': contact_business,
            'my_user_name': '',
            'job_number': job.job_number if job else '',
            'job_name': job.name if job else '',
            'document_number': estimate.estimate_number,
            'estimate_number': estimate.estimate_number,
            'object_url': build_object_url('estimate', estimate.estimate_id),
        }

        subject = render_email_template(subject_template, **values)
        body = render_email_template(body_template, **values)

        to = ''
        if contact and contact.email:
            to = contact.email

        pdf_filename = f'Estimate-{estimate.estimate_number}.pdf'
        # We don't run the PDF render here — just preview metadata. The send
        # path renders the actual bytes.
        attachments_preview = [
            {'filename': pdf_filename, 'content_type': 'application/pdf', 'size': 0},
        ]

        return {
            'to': to, 'subject': subject, 'body': body,
            'attachments_preview': attachments_preview,
        }

    @staticmethod
    def notify_shop_of_decision(estimate, decision, reason=''):
        """Best-effort email to the shop's business_email when a customer
        accepts/rejects via the portal. Never raises — the customer's action
        has already committed and must not be rolled back by a send failure.
        """
        from django.conf import settings
        from django.core.mail import send_mail
        from apps.core.models import Configuration

        try:
            addr = Configuration.objects.get(key='business_email').value.strip()
        except Configuration.DoesNotExist:
            addr = ''
        if not addr:
            return

        job_name = estimate.job.name if estimate.job_id else ''
        subject = f'Estimate {estimate.estimate_number} {decision} by customer'
        body = (f'Estimate {estimate.estimate_number} for job "{job_name}" '
                f'was {decision} by the customer.')
        if reason:
            body += f'\n\nReason given:\n{reason}'
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [addr])
        except Exception:
            logger.exception(
                'Shop notification failed for estimate %s', estimate.pk)

    @staticmethod
    def send_estimate(estimate, *, to, subject, body, cc=None, bcc=None,
                      extra_attachments=None, user=None):
        """Send an Estimate. Generates the PDF, persists an outbound
        EmailRecord via send_tracked, transitions draft → open on success.

        Args:
            estimate: Estimate instance
            to: list or comma-separated str
            subject / body: composed strings
            cc / bcc: list or None
            extra_attachments: list of (filename, bytes, mime) tuples beyond
                the auto-attached document PDF
            user: User performing the send (for HistoryEntry; optional)

        Returns:
            The outbound EmailRecord.

        Raises:
            ValidationError: missing to, no line items.
            Whatever SMTP raises (after persistence — the outbound row will
            still exist with last_send_error populated).
        """
        from apps.core.services import OutboundEmailService
        from apps.estimates.pdf import generate_estimate_pdf

        if not to:
            raise ValidationError('Recipient email address is required.')

        if not estimate.estimatelineitem_set.exists():
            raise ValidationError(
                'Cannot send an estimate with no line items.'
            )

        pdf_bytes = generate_estimate_pdf(estimate)
        pdf_filename = f'Estimate-{estimate.estimate_number}.pdf'

        attachments = [(pdf_filename, pdf_bytes, 'application/pdf')]
        if extra_attachments:
            attachments.extend(extra_attachments)

        # send_tracked persists the outbound EmailRecord before SMTP; on
        # SMTP failure the error is recorded and the exception re-raised
        # so the caller can return a useful error to the user.
        record = OutboundEmailService.send_tracked(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachments=attachments,
            associate_with={'job': estimate.job},
        )

        # Send succeeded — transition draft → open.
        if estimate.status == Estimate.STATUS_DRAFT:
            estimate.status = Estimate.STATUS_OPEN
            estimate.save()

        return record


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
    def is_editable(worksheet):
        """A worksheet is editable while the job is still quoting — its live
        (non-superseded) estimate is a draft, or the job has no estimate yet.
        It freezes once an estimate is sent (and stays frozen through accept);
        revising a sent estimate yields a new draft, which unlocks it again.
        """
        live = (
            Estimate.objects
            .filter(job_id=worksheet.job_id)
            .exclude(status=Estimate.STATUS_SUPERSEDED)
            .order_by('-version', '-pk')
            .first()
        )
        return live is None or live.status == Estimate.STATUS_DRAFT

    @staticmethod
    def create_worksheet(job_pk, **kwargs):
        """Create a new EstWorksheet for a job (one per job)."""
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')
        ws = EstWorksheet(job=job, **kwargs)
        ws.save()
        return ws

    @staticmethod
    def has_claimed_atoms(worksheet):
        """True if any of the worksheet's plan tasks/materials are claimed by an
        estimate line item source. Such a worksheet can't be deleted until those
        line items are removed (the frontend uses this to suppress the Delete
        button so the user never hits the 400)."""
        from django.db.models import Q
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        from apps.estimates.models import EstimateLineItemSource
        pt_ids = list(
            PlanTask.objects.filter(est_worksheet=worksheet).values_list('pk', flat=True)
        )
        pm_ids = list(
            PlanMaterial.objects.filter(est_worksheet=worksheet).values_list('pk', flat=True)
        )
        return EstimateLineItemSource.objects.filter(
            Q(source_type=EstimateLineItemSource.SOURCE_PLAN_TASK, source_pk__in=pt_ids)
            | Q(source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL, source_pk__in=pm_ids)
        ).exists()

    @staticmethod
    def delete_worksheet(worksheet):
        """Delete a worksheet. Refuses if any of its plan tasks/materials are
        claimed by an estimate line item — those line items must be removed
        first so their source rows don't outlive the atoms they reference.
        """
        if WorksheetService.has_claimed_atoms(worksheet):
            raise ValidationError(
                'Cannot delete a worksheet whose tasks or materials are used by '
                'an estimate. Remove those estimate line items first.'
            )
        worksheet.delete()

    @staticmethod
    def add_task_from_template(
        worksheet_pk, template_pk,
        rate_scheme_id=None,
        active_modifiers=None,
        est_qty=None,
        est_worker_time=None,
        name=None,
        description=None,
    ):
        """Add a PlanTask to a draft worksheet from a TaskTemplate.

        Optional overrides:
          name        – if truthy, replaces template_name; empty string falls back to template default.
          description – if not None, replaces template description (empty string is kept as-is).
        """
        from apps.jobs.models import PlanTask
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if not WorksheetService.is_editable(ws):
            raise ValidationError(
                'Cannot add tasks to a worksheet whose estimate has been sent.'
            )
        try:
            tt = TaskTemplate.objects.get(pk=template_pk)
        except TaskTemplate.DoesNotExist:
            raise NotFoundError(f'TaskTemplate {template_pk} not found')

        # Guard: refuse to use a template whose RateScheme has been superseded.
        # Only fires when the caller is relying on the template's rate_scheme
        # (i.e. they didn't supply an explicit override).
        if rate_scheme_id is None and tt.rate_scheme_id and tt.rate_scheme.replaced_by_id is not None:
            from apps.core.services import SchemeSupersededError
            raise SchemeSupersededError(
                f'Template "{tt.template_name}" references a superseded '
                f'RateScheme. Update the template before adding tasks from it.'
            )

        task = PlanTask.objects.create(
            name=name if name else tt.template_name,
            description=description if description is not None else tt.description,
            est_worksheet=ws,
            rate_scheme_id=rate_scheme_id if rate_scheme_id is not None else tt.rate_scheme_id,
            active_modifiers=active_modifiers if active_modifiers is not None else (tt.default_active_modifiers or []),
            est_qty=est_qty if est_qty is not None else tt.default_billable_qty,
            est_worker_time=est_worker_time,
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
        if not WorksheetService.is_editable(ws):
            raise ValidationError(
                'Cannot add tasks to a worksheet whose estimate has been sent.'
            )
        if not kwargs.get('rate_scheme_id') and not kwargs.get('rate_scheme'):
            raise ValidationError(
                {'rate_scheme': 'A RateScheme is required to add a task.'}
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
        if not WorksheetService.is_editable(ws):
            raise ValidationError('Cannot reorder a worksheet whose estimate has been sent.')

        items_qs = PlanTask.objects.filter(est_worksheet=ws)
        BundlingService.reorder_container_items(
            items_qs, item_type, item_id, direction,
        )


class EstimateClaimConflict(Exception):
    """Raised when the estimate wizard tries to claim an atom already claimed elsewhere."""

    def __init__(self, atom_ids):
        self.atom_ids = atom_ids
        super().__init__(f'Atoms already claimed: {atom_ids}')


class EstimateWizardService(BaseWizardService):
    """Orchestration layer for the estimate wizard.

    Composes on top of EstimateService rather than replacing it; manual
    line-item CRUD continues to use EstimateService. Shared
    line-items-from-atoms logic lives in BaseWizardService.
    """

    container_attr = 'estimate'
    source_fk = 'estimate_line_item'
    claim_conflict_exc = EstimateClaimConflict

    @staticmethod
    def open_for_worksheet(worksheet):
        """Return the job's draft Estimate, creating one if none exists.

        Worksheet and estimate are related only through the job (one estimate
        tree per job). Adopts the job's existing draft estimate rather than
        minting a second. Refuses if the worksheet is frozen (its job already
        has a sent/accepted estimate).
        """
        from apps.estimates.models import Estimate
        if not WorksheetService.is_editable(worksheet):
            raise ValidationError(
                'Cannot generate an estimate from a worksheet whose estimate '
                'has already been sent.'
            )

        existing = (
            Estimate.objects
            .filter(job=worksheet.job, status=Estimate.STATUS_DRAFT)
            .order_by('pk')
            .first()
        )
        if existing is not None:
            return existing

        return Estimate.objects.create(
            job=worksheet.job,
            estimate_number=f'{worksheet.job.job_number}-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )

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
    def _atom_units(atom_instance):
        """Return the units label for an atom.

        PlanTask: from rate_scheme.unit_label (or 'none' if no scheme).
        PlanMaterial: from the atom's own units field (which is populated
                      from the linked PLI at create time via _populate_from_pli,
                      so PLI-linked PMs reflect the PLI's units; freeform PMs
                      carry whatever units the user set).
        """
        from apps.jobs.models import PlanTask
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanTask):
            if atom_instance.rate_scheme_id:
                return atom_instance.rate_scheme.unit_label
            return 'none'
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.units or 'none'
        return 'none'

    @staticmethod
    def get_source_pool(worksheet):
        """Walk the worksheet's atoms and return a flat pool with claim state.

        Returns: {'atoms': [
            {'type': 'plan_task'|'plan_material', 'id': N, 'description': str,
             'qty': Decimal, 'rate': Decimal, 'amount': Decimal,
             'state': 'available'|'claimed_by_current'|'claimed_by_other',
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
        # "Current" = the job's draft estimate (the one being built). Worksheet
        # and estimate relate only through the job now.
        current_estimate = (
            Estimate.objects
            .filter(job=worksheet.job, status=Estimate.STATUS_DRAFT)
            .order_by('pk')
            .first()
        )
        current_estimate_pk = current_estimate.pk if current_estimate else None
        claims = {}
        for src in claimed_sources:
            li = src.estimate_line_item
            est = li.estimate
            key = (src.source_type, src.source_pk)
            if est.pk == current_estimate_pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_line_number': li.line_number,
                    'claiming_estimate_id': None,
                    'claiming_estimate_number': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_line_number': None,
                    'claiming_estimate_id': est.pk,
                    'claiming_estimate_number': est.estimate_number,
                }

        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_line_number': None,
            'claiming_estimate_id': None,
            'claiming_estimate_number': None,
        }

        atoms = []

        for pt in PlanTask.objects.filter(est_worksheet=worksheet).select_related(
            'rate_scheme', 'rate_scheme__accounting_category',
        ):
            key = (EstimateLineItemSource.SOURCE_PLAN_TASK, pt.pk)
            state_info = claims.get(key, default_state)
            eff_cat = pt.effective_accounting_category
            detail = EstimateWizardService._atom_detail(pt)
            atoms.append({
                'type': 'plan_task',
                'id': pt.pk,
                'description': pt.name,
                'qty': detail['qty'],
                'rate': detail['rate'],
                'amount': detail['amount'],
                'units': detail['units'],
                'category_id': eff_cat.pk if eff_cat else None,
                **state_info,
            })

        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related(
            'accounting_category', 'price_list_item',
        ):
            key = (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk)
            state_info = claims.get(key, default_state)
            detail = EstimateWizardService._atom_detail(pm)
            atoms.append({
                'type': 'plan_material',
                'id': pm.pk,
                'description': pm.description,
                'qty': detail['qty'],
                'rate': detail['rate'],
                'amount': detail['amount'],
                'units': detail['units'],
                'category_id': pm.accounting_category_id,
                **state_info,
            })

        return {'atoms': atoms}

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
        EstimateWizardService._validate_draft(estimate)

        # Build set of currently-claimed (type, pk) pairs, scoped to this job's estimates
        claimed = set(
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=worksheet.job)
            .values_list('source_type', 'source_pk')
        )

        created_count = 0

        # PlanTasks
        for pt in PlanTask.objects.filter(est_worksheet=worksheet).select_related(
            'rate_scheme', 'rate_scheme__accounting_category',
        ):
            if (EstimateLineItemSource.SOURCE_PLAN_TASK, pt.pk) in claimed:
                continue
            total = pt.compute_amount().quantize(Decimal('0.01'))
            qty, price = EstimateWizardService._atom_qty_and_price(pt, total)
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pt.name,
                qty=qty,
                units=EstimateWizardService._atom_units(pt),
                price=price,
                accounting_category=pt.effective_accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
                source_pk=pt.pk,
            )
            created_count += 1

        # PlanMaterials
        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related(
            'accounting_category', 'price_list_item',
        ):
            if (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk) in claimed:
                continue
            total = pm.compute_amount().quantize(Decimal('0.01'))
            qty, price = EstimateWizardService._atom_qty_and_price(pm, total)
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pm.description,
                qty=qty,
                units=EstimateWizardService._atom_units(pm),
                price=price,
                accounting_category=pm.accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
                source_pk=pm.pk,
            )
            created_count += 1

        return {'estimate': estimate, 'created_count': created_count}

    # ── BaseWizardService hooks ────────────────────────────────────────
    @classmethod
    def _line_item_model(cls):
        from apps.estimates.models import EstimateLineItem
        return EstimateLineItem

    @classmethod
    def _source_model(cls):
        from apps.estimates.models import EstimateLineItemSource
        return EstimateLineItemSource

    @classmethod
    def _task_model(cls):
        from apps.jobs.models import PlanTask
        return PlanTask

    @classmethod
    def _material_model(cls):
        from apps.inventory.models import PlanMaterial
        return PlanMaterial

    @classmethod
    def _validate_draft(cls, container):
        from apps.estimates.models import Estimate
        if container.status != Estimate.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot modify line items on estimate in status "{container.status}".'
            )

    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        if task.rate_scheme_id and task.est_qty is not None:
            return task.est_qty, task.effective_rate()
        return Decimal('1'), total_price

    @classmethod
    def _task_actual_qty(cls, task):
        return task.est_qty
