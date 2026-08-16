"""Mint-by-modal claim minting (2026-08-15 estimating-structure spec §2/§4).

The gesture "Plan work on this estimate line" (mint-by-modal) creates a real
atom via the existing job endpoints and binds it to the line with an
EstimateLineItemSource claim. Binding is allowed ONLY while the estimate is
ACCEPTED — draft and open both refuse. Mint-by-modal exists to serve the
post-acceptance checklist workflow (see Task 7); the estimate document
itself isn't final until acceptance, so minting a claim earlier would race
the wizard's own line composition. Dead documents (rejected / superseded /
expired) never gain claims either.

Mint-by-modal is for plain hand lines only: lines that already carry
catalog identity (a service_item, an inventory_item, or the is_material
flag) crystallize their own atom at acceptance (Task 4) and must not also
be claimable through this gesture. Lines already marked work_declined have
answered "no work needed" and must be un-marked before they can be minted.
"""
from django.core.exceptions import ValidationError

# apps.estimates.models has no dependency back on this module (or on
# anything that transitively imports it), so a top-level import here
# doesn't cycle — unlike claim_atom_for_line below, which keeps its model
# imports function-local because Material/Task's own modules eventually
# pull in the estimates app.
from apps.estimates.models import Estimate

MINT_STATUSES = (Estimate.STATUS_ACCEPTED,)


class MintService:

    @staticmethod
    def claim_atom_for_line(line_item, source_type, source_pk):
        """Mint the claim binding atom (source_type, source_pk) to
        line_item. Returns the EstimateLineItemSource. Raises
        ValidationError when the estimate isn't accepted, the line is an
        adjustment, the line carries catalog identity, the line is marked
        work_declined, the atom is missing/cross-job, or already claimed.

        Only checks the estimate table for a live claim status. Callers
        that pass a PRE-EXISTING atom (rather than one just minted for this
        gesture) must also consult the ChangeOrder lens — see
        `claims.py`'s atom_is_claimed — because a claim can equally live on
        an accepted CO's own line-item sources. The three endpoints that
        call this service only ever claim just-created atoms, so that
        second table is never in play here."""
        from apps.estimates.models import EstimateLineItemSource
        from apps.inventory.models import Material
        from apps.jobs.models import Task

        estimate = line_item.estimate
        if estimate.status not in MINT_STATUSES:
            raise ValidationError(
                f'Cannot plan work on an estimate in status "{estimate.status}".')
        if line_item.adjustment_service_id is not None:
            raise ValidationError('Cannot plan work on an adjustment line.')
        if (line_item.service_item_id is not None
                or line_item.inventory_item_id is not None
                or line_item.is_material):
            raise ValidationError('Cannot plan work on a catalog line.')
        if line_item.work_declined:
            raise ValidationError(
                'This line is marked as needing no work — un-mark it first.')

        model = (Task if source_type == EstimateLineItemSource.SOURCE_TASK
                 else Material)
        atom = model.objects.filter(pk=source_pk).first()
        if atom is None:
            raise ValidationError('Atom to claim was not found.')
        if atom.job_id != estimate.job_id:
            raise ValidationError('Atom belongs to a different job.')
        if EstimateLineItemSource.objects.filter(
                source_type=source_type, source_pk=source_pk).exists():
            raise ValidationError('This atom is already claimed.')

        return EstimateLineItemSource.objects.create(
            estimate_line_item=line_item,
            source_type=source_type,
            source_pk=source_pk,
        )
