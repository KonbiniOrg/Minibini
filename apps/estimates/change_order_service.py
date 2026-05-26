"""
Service class for ChangeOrder lifecycle operations.

Rules:
- A CO can only be created while the job is on_hold.
- Accepting a CO auto-advances the job on_hold -> approved (no Task/Material mutations).
- Rejecting/expiring a CO snapshots the proposal and leaves the job on_hold.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.services import NotFoundError
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate
from apps.jobs.models import Job


class ChangeOrderService:
    """Lifecycle operations for ChangeOrder."""

    @staticmethod
    @transaction.atomic
    def create(*, job_id):
        """Create a draft ChangeOrder for the given job.

        Guards:
        - job.status must be on_hold.
        - job must have an accepted estimate.

        Trigger 1: snapshot the prior agreement onto the latest accepted CO
        for that estimate (if one exists) or the accepted estimate itself.
        snapshot_document is idempotent, so repeat calls are safe.
        """
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')

        if job.status != Job.STATUS_ON_HOLD:
            raise ValidationError(
                'A change order can only be created while the job is on hold.'
            )

        try:
            accepted_est = Estimate.objects.get(job=job, status=Estimate.STATUS_ACCEPTED)
        except Estimate.DoesNotExist:
            raise ValidationError('Job has no accepted estimate to amend.')

        # Trigger 1: snapshot the prior agreement.
        # Find the latest accepted CO on this estimate; if none, snapshot the estimate.
        latest_accepted_co = (
            ChangeOrder.objects
            .filter(estimate=accepted_est, status=ChangeOrder.STATUS_ACCEPTED)
            .order_by('-change_order_id')
            .first()
        )
        from apps.deliverables.services import DeliverableService
        if latest_accepted_co is not None:
            DeliverableService.snapshot_document(change_order=latest_accepted_co)
        else:
            DeliverableService.snapshot_document(estimate=accepted_est)

        co = ChangeOrder.objects.create(job=job, estimate=accepted_est)
        return co

    @staticmethod
    @transaction.atomic
    def update_status(pk, new_status):
        """Update a ChangeOrder's status with lifecycle side-effects.

        - Accepted: advance job on_hold -> approved; write system HistoryEntry.
          Does NOT create or modify any Task or Material.
        - Rejected / Expired: snapshot the proposal (Trigger 2); leave job on_hold.
        """
        try:
            co = ChangeOrder.objects.select_for_update().get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        old_status = co.status
        co.status = new_status
        co.save()  # Model.clean() validates the transition and sets dates.

        if new_status == ChangeOrder.STATUS_ACCEPTED and old_status != ChangeOrder.STATUS_ACCEPTED:
            ChangeOrderService._handle_accepted(co)

        elif new_status in (ChangeOrder.STATUS_REJECTED, ChangeOrder.STATUS_EXPIRED):
            # Trigger 2: snapshot the proposal.
            from apps.deliverables.services import DeliverableService
            DeliverableService.snapshot_document(change_order=co)

        return co

    @staticmethod
    def _handle_accepted(co):
        """Advance the job on_hold -> approved and write a system-attributed HistoryEntry."""
        from apps.core.models import HistoryEntry, User
        from apps.jobs.services import JobService

        job = co.job
        job.refresh_from_db()

        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )

        if job.status == Job.STATUS_ON_HOLD:
            old_status = job.status
            JobService.update_job(job.pk, status=Job.STATUS_APPROVED)
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='change_order',
                object_id=co.pk,
                user=system_user,
                changes={
                    'status': {
                        'old': old_status,
                        'new': Job.STATUS_APPROVED,
                    },
                    '_action': 'Change order accepted',
                },
            )

    @staticmethod
    def mark_open(pk):
        """Transition a draft CO to open."""
        return ChangeOrderService.update_status(pk, ChangeOrder.STATUS_OPEN)

    @staticmethod
    @transaction.atomic
    def seed_new(pk):
        """Create a new draft CO by copying all line items from an existing (terminal) CO.

        The source CO retains its status. The new CO gets parent=source.
        Line items are copied directly (no renumbering).
        """
        try:
            src = ChangeOrder.objects.get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        new_co = ChangeOrder.objects.create(
            job=src.job,
            estimate=src.estimate,
            parent=src,
        )

        for li in ChangeOrderLineItem.objects.filter(change_order=src):
            ChangeOrderLineItem.objects.create(
                change_order=new_co,
                action=li.action,
                target_line_item=li.target_line_item,
                description=li.description,
                qty=li.qty,
                units=li.units,
                price=li.price,
                line_number=li.line_number,
                source_template=li.source_template,
                price_list_item=li.price_list_item,
            )

        return new_co

    @staticmethod
    def discard_draft(pk):
        """Hard-delete a draft CO. Cascades to line items.

        Raises ValidationError if the CO is not in draft status.
        """
        try:
            co = ChangeOrder.objects.get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError(
                'Only draft change orders can be discarded.'
            )
        co.delete()
