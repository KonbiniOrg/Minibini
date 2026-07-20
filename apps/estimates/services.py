"""
Service classes for Estimate generation and management.
"""

import logging
from apps.core.history import record_history
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.estimates.models import (
    Estimate, EstimateLineItem,
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
    ChangeOrder,
)
from apps.core.services import NumberGenerationService, NotFoundError
from apps.core.wizard import BaseWizardService
from apps.inventory.models import InventoryItem

logger = logging.getLogger(__name__)


def _decimal_or_invalid(value, field):
    """Coerce an API-supplied number to Decimal via str() (a raw JSON float
    would expand to its binary value and trip decimal_places validation)."""
    from decimal import InvalidOperation
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: 'Invalid decimal value.'})


class EstimateService:
    """Service class for Estimate creation and management."""

    @staticmethod
    def create_direct(job, **kwargs):
        """
        Create Estimate directly. Starts in 'draft' status.
        Estimate number IS the job number (one estimate tree per job); the
        revision lives in the separate ``version`` field, not in the number.
        """
        version = kwargs.pop('version', 1)
        estimate_number = kwargs.pop('estimate_number', job.job_number)
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

        The estimate number IS the job number; the revision lives in the
        separate ``version`` field. Enforces the one-live-estimate-tree-per-job
        invariant: a second concurrent estimate would let acceptance
        crystallize duplicate speculative atoms — new versions come from
        ``revise_estimate`` (which supersedes the parent), never a second
        tree. (``revise_estimate`` creates its revision directly, so the
        transient two-live-rows moment inside that operation is exempt.)
        """
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')

        # Estimates belong to the quoting phase. A job that advanced without
        # one (hand-approved or duplicated-as-approved) is past that phase —
        # a fresh estimate there would restart a negotiation the job already
        # skipped. Revisions of an existing tree go through revise_estimate,
        # not here.
        if job.status not in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED):
            raise ValidationError(
                f'Cannot start an estimate for a job in status '
                f'"{job.status}" — the job is past the estimating phase.'
            )

        if Estimate.objects.filter(job=job).exclude(
            status=Estimate.STATUS_SUPERSEDED
        ).exists():
            raise ValidationError(
                'This job already has an estimate. Revise the existing one instead.'
            )

        estimate = Estimate.objects.create(
            job=job,
            estimate_number=job.job_number,
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        return estimate

    @staticmethod
    @transaction.atomic
    def update_status(pk, new_status, actor=None):
        """Update estimate status. Model validates transitions.

        Atomic: accepting an estimate fires a synchronous signal cascade
        (``estimate.save()`` → job-status update(s) → atom carry-over → earmarking).
        Wrapping the whole thing in one transaction keeps that cascade all-or-nothing
        — a failure partway (e.g. the carry-over's job-state guard, or any DB error)
        rolls back the status change too, instead of leaving a half-accepted estimate
        (job approved but no tasks carried over, or tasks without earmarks).

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
            label = {
                Estimate.STATUS_ACCEPTED: 'Accepted via customer link',
                Estimate.STATUS_REJECTED: 'Declined via customer link',
            }.get(new_status, f'{new_status} via customer link')
            record_history(
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
    def update_fields(estimate, **fields):
        """Non-status field updates (status routes through mark_open /
        update_status). Exists so the viewset owns no persistence."""
        for k, v in fields.items():
            setattr(estimate, k, v)
        estimate.save()
        return estimate

    @staticmethod
    def _apply_material_ac_default(li):
        """A material line (is_material=True) with no AC defaults to the
        `default_material_accounting_category` Configuration value (a string
        AccountingCategory pk). An explicitly-supplied AC is respected. Raises
        if the marker is set, no AC was supplied, and no default is configured.
        Fees (is_material=False) are untouched — they still hit the hand-line
        AC-required rule downstream."""
        if not li.is_material or li.accounting_category_id is not None:
            return
        from apps.core.models import AccountingCategory, Configuration
        cfg = Configuration.objects.filter(
            key='default_material_accounting_category',
        ).first()
        pk = (cfg.value or '').strip() if cfg else ''
        if not pk:
            raise ValidationError({'accounting_category': (
                'This material line has no accounting category and no default is '
                'configured. Set the default_material_accounting_category setting '
                'or supply an accounting category.'
            )})
        try:
            li.accounting_category = AccountingCategory.objects.get(pk=pk)
        except (AccountingCategory.DoesNotExist, ValueError, TypeError):
            raise ValidationError({'accounting_category': (
                f'The configured default material accounting category ({pk!r}) '
                'does not exist.'
            )})

    @staticmethod
    def _assert_is_material_only_on_bare_line(li):
        """`is_material` is meaningful only on a bare line. A line with an
        inventory_item is already a (catalog) material; an adjustment line is
        document-only — the marker must not conflict with either."""
        if not li.is_material:
            return
        if li.inventory_item_id is not None:
            raise ValidationError({'is_material': (
                'A line with an inventory item is already a material; '
                'the "is material" marker only applies to a bare line.'
            )})
        if li.adjustment_service_id is not None:
            raise ValidationError({'is_material': (
                'An adjustment line cannot be marked as a material.'
            )})

    @staticmethod
    def assert_all_hand_lines_have_ac(estimate):
        """Raise if any hand-line (no atom source, not a percentage adjustment)
        lacks an accounting category. Enforced at send-time (mark_open / email)
        so the AC-required rule is caught before the estimate goes out — not only
        at acceptance. Atom-backed and adjustment lines are exempt (same predicate
        as EstimateAcceptanceService.on_accept)."""
        missing = []
        for li in estimate.estimatelineitem_set.all():
            if li.sources.exists():
                continue
            if li.adjustment_service_id is not None:
                continue
            if li.accounting_category_id is None:
                missing.append(li.description or f'line {li.line_number}')
        if missing:
            raise ValidationError(
                'Cannot send: every line item needs an accounting category first. '
                'Missing on: ' + ', '.join(missing) + '.'
            )

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

        # Guard: every hand-line must have an accounting category before send.
        EstimateService.assert_all_hand_lines_have_ac(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        # Once sent, the estimate freezes the job's quoting state: a sent
        # (non-draft) live estimate blocks further wizard edits.

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
            estimate_number=parent.job.job_number,
            version=new_version,
            status=Estimate.STATUS_DRAFT,
            parent=parent,
        )

        # Copy line items onto the new revision and MOVE each source row
        # (EstimateLineItemSource) from the parent's line to the new revision's
        # copied line.  Net effect: the superseded estimate keeps its
        # EstimateLineItem rows as a frozen snapshot (description/qty/price
        # intact) but has no source rows; the new revision's lines carry the
        # live atom references by default.  Each atom remains claimed exactly
        # once (unique_together is satisfied because the row is re-pointed, not
        # duplicated).
        for li in EstimateLineItem.objects.filter(estimate=parent):
            new_li = EstimateLineItem.objects.create(
                estimate=new_estimate,
                inventory_item=li.inventory_item,
                qty=li.qty,
                units=li.units,
                description=li.description,
                price=li.price,
                accounting_category=li.accounting_category,
                adjustment_service_id=li.adjustment_service_id,
                service_item=li.service_item,
                is_material=li.is_material,
            )
            # Copy M2M adjustment target categories (empty set is fine — means "all lines")
            cats = li.adjustment_target_categories.all()
            if cats:
                new_li.adjustment_target_categories.set(cats)
            # Move the source rows to the new revision's line item so the atom
            # is claimed by the revision (not dropped).  The parent line ends up
            # with no sources — a correct frozen snapshot.
            for src in li.sources.all():
                src.estimate_line_item = new_li
                src.save()

        # Supersede parent
        parent.status = Estimate.STATUS_SUPERSEDED
        parent.save()

        # Freeze the deliverables the customer saw while this estimate was the
        # live proposal. The list was read-only while the estimate was `open`
        # (DeliverableService.is_editable), so the live list at this point is
        # exactly what was shown. The portal renders this snapshot for the now-
        # out-of-date estimate; the new draft keeps using the live list.
        from apps.deliverables.services import DeliverableService
        DeliverableService.snapshot_document(estimate=parent)

        return new_estimate

    @staticmethod
    def request_changes(pk, actor):
        """Customer-initiated revision from the portal.

        Records the customer's comment, revises the estimate (new draft, parent
        superseded), and reverts the job ``submitted -> draft`` so a draft job +
        draft estimate keep it in the quoting pipeline. ``actor`` is the portal
        actor dict ``{'contact_id', 'email', 'reason'}``. Returns the new draft.
        """
        from apps.jobs.models import Job
        from apps.jobs.services import JobService
        try:
            parent = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        with transaction.atomic():
            # Record the change request against the estimate the customer saw,
            # reusing the customer-action HistoryEntry shape (see update_status).
            record_history(
                entry_type='action',
                object_type='estimate',
                object_id=parent.pk,
                user=None,
                changes={
                    '_action': 'Changes requested via customer link',
                    'contact_id': actor.get('contact_id'),
                    'customer_email': actor.get('email'),
                },
                text=actor.get('reason') or '',
            )
            new_estimate = EstimateService.revise_estimate(parent.pk)
            # Revising supersedes the parent but doesn't touch job status.
            job = parent.job
            if job.status == Job.STATUS_SUBMITTED:
                JobService.update_status(job.pk, Job.STATUS_DRAFT)
        return new_estimate

    # NOTE: direct line authoring (manual add_line_item + add_line_item_from_pli) was
    # removed in Phase 6 — estimate lines come only from atoms (the wizard / Show
    # Client View). Editing/deleting/reordering existing lines + adjustments remain.

    @staticmethod
    def add_line_item(estimate_pk, **kwargs):
        """Add a manual (hand-authored) line item to a draft estimate.

        A hand-line has no atom source and isn't an adjustment, so it must carry
        an accounting category (Decision 1) — the same rule enforced on update."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft estimates.')
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(EstimateLineItem, kwargs)
        li = EstimateLineItem(estimate=estimate, **kwargs)
        # Material lines (is_material=True) get their AC from config if not supplied.
        EstimateService._apply_material_ac_default(li)
        # A freshly-added line has no sources; if it isn't an adjustment it needs an AC.
        if li.adjustment_service_id is None and li.accounting_category_id is None:
            raise ValidationError(
                {'accounting_category': (
                    'Accounting category is required for hand-line items '
                    '(lines with no atom source).'
                )}
            )
        EstimateService._assert_is_material_only_on_bare_line(li)
        li.full_clean()
        LineItemService.save_line_item(li)
        return li

    @staticmethod
    def add_line_item_from_pli(estimate_pk, pli_pk, qty):
        """Add a line item from an InventoryItem to a draft estimate."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft estimates.')
        try:
            pli = InventoryItem.objects.get(pk=pli_pk)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {pli_pk} not found')
        from apps.core.services import LineItemService
        li = EstimateLineItem(
            estimate=estimate,
            inventory_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            accounting_category=pli.accounting_category,
        )
        li.full_clean()
        LineItemService.save_line_item(li)
        return li

    @staticmethod
    def add_line_item_from_service(estimate_pk, service_item_pk, qty):
        """Add a deferred service line to a draft estimate.

        Mirrors add_line_item_from_pli: snapshots the priced values off the
        ServiceItem at instantiation (price/accounting_category/units/description)
        and keeps `service_item` on the line purely as the crystallization target.
        Mints NO Task — the Task is created at acceptance (on_accept)."""
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft estimates.')
        try:
            service_item = ServiceItem.objects.get(pk=service_item_pk)
        except ServiceItem.DoesNotExist:
            raise NotFoundError(f'ServiceItem {service_item_pk} not found')
        from apps.core.services import LineItemService
        scheme = service_item.rate_scheme
        li = EstimateLineItem(
            estimate=estimate,
            service_item=service_item,
            description=service_item.template_name,
            # str() first: a raw JSON float would expand to its binary value
            # and trip the 2-decimal-places validator.
            qty=_decimal_or_invalid(qty, 'qty'),
            units=scheme.unit_label or 'none',
            price=scheme.effective_rate(service_item.default_active_modifiers),
            accounting_category=service_item.effective_accounting_category,
        )
        li.full_clean()
        LineItemService.save_line_item(li)
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
        # Hand-lines (no atom source, not an adjustment) must have an accounting category.
        # Atom-backed lines (sources exist) and adjustment lines are exempt.
        is_adjustment = li.adjustment_service_id is not None
        has_source = li.sources.exists()
        # Material lines (is_material=True) get their AC from config if not supplied.
        EstimateService._apply_material_ac_default(li)
        if not has_source and not is_adjustment and li.accounting_category_id is None:
            raise ValidationError(
                {'accounting_category': (
                    'Accounting category is required for hand-line items '
                    '(lines with no atom source).'
                )}
            )
        EstimateService._assert_is_material_only_on_bare_line(li)
        li.full_clean()
        LineItemService.save_line_item(li)
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
    @transaction.atomic
    def add_adjustment_line(estimate, *, adjustment_service_id, target_category_ids=None):
        """Add a percentage-adjustment line item to a draft estimate.

        Creates an EstimateLineItem backed by a PERCENTAGE RateScheme, sets
        target categories (empty list = apply to all non-adjustment lines),
        computes the initial price via ``compute_adjustment_amount``, and
        returns the saved line.

        Raises ValidationError if the estimate is not draft or the service is
        not a PERCENTAGE algorithm.
        """
        from django.db.models import Max
        from apps.jobs.models import RateScheme
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Adjustments can only be added to a draft estimate.')
        svc = RateScheme.objects.get(pk=adjustment_service_id)
        if svc.algorithm != RateScheme.PERCENTAGE:
            raise ValidationError('Adjustment line requires a percentage service.')
        max_ln = (EstimateLineItem.objects.filter(estimate=estimate)
                  .aggregate(Max('line_number'))['line_number__max'] or 0)
        from apps.core.services import LineItemService
        line = EstimateLineItem(
            estimate=estimate,
            line_number=max_ln + 1,
            qty=Decimal('1'),
            units=svc.unit_label or 'none',
            description=svc.name,
            price=Decimal('0.00'),
            accounting_category=svc.accounting_category,
            adjustment_service=svc,
        )
        line.save()
        if target_category_ids:
            line.adjustment_target_categories.set(target_category_ids)
        LineItemService.save_line_item(line)
        line.refresh_from_db()
        return line


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
                      extra_attachments=None):
        """Send an Estimate. Generates the PDF, persists an outbound
        EmailRecord via send_tracked, transitions draft → open on success.

        Args:
            estimate: Estimate instance
            to: list or comma-separated str
            subject / body: composed strings
            cc / bcc: list or None
            extra_attachments: list of (filename, bytes, mime) tuples beyond
                the auto-attached document PDF

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

        # Every hand-line must have an accounting category before it goes out.
        EstimateService.assert_all_hand_lines_have_ac(estimate)

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


class ChangeOrderEmailService:
    """Customer send + shop-notification email for ChangeOrders.

    Mirrors EstimateEmailService: the customer email carries the portal link
    plus a generated change-order PDF (the diff). Transitions the CO
    draft -> open on send success (no job-status side effect, unlike an
    estimate send).
    """

    DEFAULT_SUBJECT = 'Change order {document_number}'
    DEFAULT_BODY = (
        'Hi {contact_fname},\n\n'
        'We have a change to estimate {estimate_number} for {job_name}. '
        'You can review and approve the change online here:\n'
        '{object_url}\n\n'
        'Let us know if you have any questions.\n\n'
        'Thanks,\n{my_user_name}'
    )

    @staticmethod
    def get_email_defaults(co):
        """Pre-populated send-form fields for a ChangeOrder: to, subject,
        body, attachments_preview (the auto-attached change-order PDF)."""
        from apps.core.models import Configuration
        from apps.core.email_templates import (
            build_object_url, render_email_template,
        )

        subject_template = ChangeOrderEmailService.DEFAULT_SUBJECT
        body_template = ChangeOrderEmailService.DEFAULT_BODY
        try:
            subject_template = Configuration.objects.get(
                key='change_order_email_subject_template').value
        except Configuration.DoesNotExist:
            pass
        try:
            body_template = Configuration.objects.get(
                key='change_order_email_body_template').value
        except Configuration.DoesNotExist:
            pass

        job = co.job
        contact = job.contact if job else None
        contact_business = ''
        if contact and contact.business:
            contact_business = contact.business.business_name

        values = {
            'contact_fname': contact.first_name if contact else '',
            'contact_lname': contact.last_name if contact else '',
            'contact_business': contact_business,
            'my_user_name': '',
            'job_number': job.job_number if job else '',
            'job_name': job.name if job else '',
            'document_number': co.change_order_number,
            'change_order_number': co.change_order_number,
            'estimate_number': co.estimate.estimate_number if co.estimate_id else '',
            'object_url': build_object_url('change_order', co.change_order_id),
        }
        subject = render_email_template(subject_template, **values)
        body = render_email_template(body_template, **values)

        to = contact.email if (contact and contact.email) else ''
        pdf_filename = f'ChangeOrder-{co.change_order_number}.pdf'
        attachments_preview = [
            {'filename': pdf_filename, 'content_type': 'application/pdf', 'size': 0},
        ]
        return {
            'to': to, 'subject': subject, 'body': body,
            'attachments_preview': attachments_preview,
        }

    @staticmethod
    def notify_shop_of_decision(co, decision, reason=''):
        """Best-effort email to the shop's business_email when a customer
        accepts/rejects/requests changes via the portal. Never raises — the
        customer's action has already committed and must not be rolled back by
        a send failure.
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

        job_name = co.job.name if co.job_id else ''
        subject = f'Change order {co.change_order_number} {decision} by customer'
        body = (f'Change order {co.change_order_number} for job "{job_name}" '
                f'was {decision} by the customer.')
        if reason:
            body += f'\n\nReason given:\n{reason}'
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [addr])
        except Exception:
            logger.exception(
                'Shop notification failed for change order %s', co.pk)

    @staticmethod
    def send_change_order(co, *, to, subject, body, cc=None, bcc=None,
                          extra_attachments=None):
        """Send a ChangeOrder to the customer (portal link + generated CO PDF).
        Persists an outbound EmailRecord via send_tracked and transitions
        draft -> open on success.

        Raises ValidationError when ``to`` is empty. Re-raises SMTP errors
        after the EmailRecord is persisted (with last_send_error set).
        """
        from apps.core.services import OutboundEmailService
        from apps.estimates.pdf import generate_change_order_pdf

        if not to:
            raise ValidationError('Recipient email address is required.')

        if not co.changeorderlineitem_set.exists():
            raise ValidationError(
                'Cannot send a change order with no line items.'
            )

        pdf_bytes = generate_change_order_pdf(co)
        pdf_filename = f'ChangeOrder-{co.change_order_number}.pdf'
        attachments = [(pdf_filename, pdf_bytes, 'application/pdf')]
        if extra_attachments:
            attachments.extend(extra_attachments)

        record = OutboundEmailService.send_tracked(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachments=attachments,
            associate_with={'job': co.job},
        )

        # Send succeeded — transition draft -> open (no job-status side effect).
        if co.status == ChangeOrder.STATUS_DRAFT:
            co.status = ChangeOrder.STATUS_OPEN
            co.save()

        return record


class WorkTemplateService:
    """Service for WorkTemplate and ServiceItem CRUD."""

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

    # --- ServiceItem ---

    @staticmethod
    def create_service_item(**kwargs):
        """Create a new ServiceItem."""
        tt = ServiceItem(**kwargs)
        tt.full_clean()
        tt.save()
        return tt

    @staticmethod
    def update_service_item(pk, **kwargs):
        """Update an existing ServiceItem by PK."""
        try:
            tt = ServiceItem.objects.get(pk=pk)
        except ServiceItem.DoesNotExist:
            raise NotFoundError(f'ServiceItem {pk} not found')
        for field, value in kwargs.items():
            setattr(tt, field, value)
        tt.full_clean()
        tt.save()
        return tt

    @staticmethod
    def delete_service_item(pk):
        """Delete a ServiceItem if not used in any WorkTemplate."""
        try:
            tt = ServiceItem.objects.get(pk=pk)
        except ServiceItem.DoesNotExist:
            raise NotFoundError(f'ServiceItem {pk} not found')
        if TemplateTaskAssociation.objects.filter(service_item=tt).exists():
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
    def _resolve_atom(atom_ref):
        """Convert {'type': 'task'|'material', 'id': N} to a model instance.

        The estimate now projects the Job's own atoms (Tasks + Materials),
        per the job-owns-atoms refactor.
        """
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        atom_type = atom_ref.get('type')
        atom_id = atom_ref.get('id')
        if atom_type == 'task':
            try:
                return Task.objects.get(pk=atom_id)
            except Task.DoesNotExist:
                raise ValidationError(f'Task {atom_id} not found')
        if atom_type == 'material':
            try:
                return Material.objects.get(pk=atom_id)
            except Material.DoesNotExist:
                raise ValidationError(f'Material {atom_id} not found')
        raise ValidationError(f'Unknown atom type: {atom_type}')

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        from apps.estimates.models import EstimateLineItemSource
        if isinstance(atom_instance, Task):
            return EstimateLineItemSource.SOURCE_TASK
        if isinstance(atom_instance, Material):
            return EstimateLineItemSource.SOURCE_MATERIAL
        raise ValueError(f'Unknown atom instance type: {type(atom_instance)}')

    @classmethod
    def _atom_computed_amount(cls, atom_instance):
        """Estimate-side billable amount, quantized to cents.

        Tasks bill est_qty here (compute_estimate_amount), NOT actuals — the
        estimate projects expected cost. The invoice wizard keeps the base
        implementation (compute_amount → actuals). Materials use compute_amount
        either way (quantity × sell_price; no actuals divergence).
        """
        from apps.jobs.models import Task
        if isinstance(atom_instance, Task):
            return atom_instance.compute_estimate_amount().quantize(Decimal('0.01'))
        return super()._atom_computed_amount(atom_instance)

    @staticmethod
    def _atom_units(atom_instance):
        """Return the units label for an atom.

        Task: from rate_scheme.unit_label (rate_scheme is NOT NULL on Task).
        Material: from the atom's own units field (which is populated from the
                  linked PLI at create time via _populate_from_pli, so PLI-linked
                  materials reflect the PLI's units; freeform materials carry
                  whatever units the user set).
        """
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            if atom_instance.rate_scheme_id:
                return atom_instance.rate_scheme.unit_label
            return 'none'
        if isinstance(atom_instance, Material):
            return atom_instance.units or 'none'
        return 'none'

    @staticmethod
    def get_source_pool(estimate):
        """Walk the estimate's Job's atoms (Tasks + Materials) and return a flat
        pool with claim state (job-owns-atoms refactor).

        Returns: {'atoms': [
            {'type': 'task'|'material', 'id': N, 'description': str,
             'qty': Decimal, 'rate': Decimal, 'amount': Decimal,
             'state': 'available'|'claimed_by_current'|'claimed_by_other',
             'category_id': N or None, 'units': str}
        ]}
        """
        from apps.estimates.models import EstimateLineItemSource
        from apps.jobs.models import Task
        from apps.inventory.models import Material

        job = estimate.job

        # Build the claim lookup: (source_type, source_pk) -> state info.
        claimed_sources = (
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=job)
            .select_related('estimate_line_item', 'estimate_line_item__estimate')
        )
        # "Current" = the estimate being built (passed in).
        current_estimate_pk = estimate.pk
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

        # Cancelled tasks stay OUT of the estimate pool: estimates project
        # PLANNED work (est_qty), and a cancelled task is not planned work.
        # (The invoice pool is the opposite — recorded actuals on a
        # cancelled task remain billable. Plan C3.)
        for task in Task.objects.filter(job=job).exclude(
            status=Task.STATUS_CANCELLED,
        ).select_related(
            'rate_scheme', 'rate_scheme__accounting_category',
        ):
            key = (EstimateLineItemSource.SOURCE_TASK, task.pk)
            state_info = claims.get(key, default_state)
            eff_cat = task.effective_accounting_category
            detail = EstimateWizardService._atom_detail(task)
            atoms.append({
                'type': 'task',
                'id': task.pk,
                'description': task.name,
                'qty': detail['qty'],
                'rate': detail['rate'],
                'amount': detail['amount'],
                'units': detail['units'],
                'category_id': eff_cat.pk if eff_cat else None,
                **state_info,
            })

        # Released materials (descoped/returned — qty moved to released_qty)
        # are job history, not quotable work; keep them out of the pool.
        for mat in Material.objects.filter(job=job).exclude(
            consumption_state=Material.CONSUMPTION_STATE_RELEASED,
        ).select_related(
            'accounting_category', 'inventory_item',
        ):
            key = (EstimateLineItemSource.SOURCE_MATERIAL, mat.pk)
            state_info = claims.get(key, default_state)
            detail = EstimateWizardService._atom_detail(mat)
            atoms.append({
                'type': 'material',
                'id': mat.pk,
                'description': mat.description,
                'qty': detail['qty'],
                'rate': detail['rate'],
                'amount': detail['amount'],
                'units': detail['units'],
                'category_id': mat.accounting_category_id,
                **state_info,
            })

        return {'atoms': atoms}

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
        from apps.jobs.models import Task
        return Task

    @classmethod
    def _material_model(cls):
        from apps.inventory.models import Material
        return Material

    @classmethod
    def _validate_draft(cls, container):
        from apps.estimates.models import Estimate
        if container.status != Estimate.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot modify line items on estimate in status "{container.status}".'
            )

    @staticmethod
    def send_all_atoms(estimate):
        """Project every currently-available atom onto the estimate, one line
        per atom (the wizard's one-click "send all"). Skips claimed atoms, so
        it composes with lines already present — unlike the invoice's
        fresh-document seed_all_atoms. Returns the number of lines created."""
        from django.db import transaction
        EstimateWizardService._validate_draft(estimate)
        pool = EstimateWizardService.get_source_pool(estimate)
        available = [
            {'type': a['type'], 'id': a['id']}
            for a in pool['atoms'] if a['state'] == 'available'
        ]
        with transaction.atomic():
            for ref in available:
                EstimateWizardService.add_atoms_to_new_line_item(estimate, [ref])
        return len(available)

    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        if task.rate_scheme_id and task.est_qty is not None:
            return task.est_qty, task.effective_rate()
        return Decimal('1'), total_price

    @classmethod
    def _task_actual_qty(cls, task):
        return task.est_qty
