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

Per-unit-lines spec §5/§6 (Task 5): a plain hand line's one-unit-or-whole-
line interpretation is asked ONCE, on its first mint — see
`claim_atom_for_line`'s `set_line_per_unit` param. On a per-unit line, the
mint API views multiply the submitted per-unit qty/worker-time by the
line's qty BEFORE creating the atom (atoms are always born with totals)
and hand this service the RAW per-unit values for the claim-row snapshot.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

# apps.estimates.models has no dependency back on this module (or on
# anything that transitively imports it), so a top-level import here
# doesn't cycle — unlike claim_atom_for_line below, which keeps its model
# imports function-local because Material/Task's own modules eventually
# pull in the estimates app.
from apps.estimates.models import Estimate

MINT_STATUSES = (Estimate.STATUS_ACCEPTED,)


class MintService:

    @staticmethod
    @transaction.atomic
    def claim_atom_for_line(line_item, source_type, source_pk,
                             per_unit_qty=None, per_unit_worker_time=None,
                             set_line_per_unit=None):
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
        second table is never in play here.

        `set_line_per_unit` (True/False/None — the mint flow's one-unit-or-
        whole-line question, per-unit-lines spec §5/§6) is the "ask ONCE
        per line" gesture: honored ONLY when line_item has NO existing
        sources yet (the first mint against it). On that first mint, a
        non-None value sets `line_item.per_unit` via
        `LineItemService.save_line_item` — a deliberate service-level write
        to a field on an ACCEPTED estimate line, the second carve-out of
        its kind beside `EstimateService._set_work_declined` (see that
        docstring for the shape of the pattern this mirrors). Once sources
        exist, the question is answered: a non-None value that DIFFERS from
        the line's current `per_unit` raises `ValidationError("This line's
        one-unit-or-whole-line choice is already set.")`; a value that
        agrees is a harmless no-op. `None` (the param's default — later
        mints simply omit it) never writes and never conflicts.

        When the line ends up per-unit (whether just set above or already
        `per_unit=True` from an earlier mint), `per_unit_qty` is REQUIRED —
        `ValidationError('A per-unit quantity is required for this
        line.')` otherwise — and is stored on the new source row together
        with `per_unit_worker_time` (the per-unit snapshot, spec §2/§3).
        Callers (the mint API views) are responsible for multiplying the
        submitted per-unit values by `line_item.qty` BEFORE creating the
        atom itself — atoms are born with totals, never restamped after
        the fact — and for passing the RAW per-unit values here for the
        snapshot. Both are silently ignored (never stored) on a
        non-per-unit line.

        After a successful claim, calls JobService.maybe_auto_release —
        this claim may have been the job's last unanswered checklist line."""
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

        if set_line_per_unit is not None:
            set_line_per_unit = bool(set_line_per_unit)
            has_sources = EstimateLineItemSource.objects.filter(
                estimate_line_item=line_item).exists()
            if has_sources:
                if set_line_per_unit != line_item.per_unit:
                    raise ValidationError(
                        "This line's one-unit-or-whole-line choice is "
                        "already set.")
            else:
                from apps.core.services import LineItemService
                line_item.per_unit = set_line_per_unit
                LineItemService.save_line_item(line_item)

        if line_item.per_unit and per_unit_qty is None:
            raise ValidationError(
                'A per-unit quantity is required for this line.')

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

        source = EstimateLineItemSource.objects.create(
            estimate_line_item=line_item,
            source_type=source_type,
            source_pk=source_pk,
            per_unit_qty=per_unit_qty if line_item.per_unit else None,
            per_unit_worker_time=(
                per_unit_worker_time if line_item.per_unit else None),
        )

        # Answering a checklist line can be the last unanswered one — the
        # estimate is always ACCEPTED here (the gate above admits nothing
        # else), so this is unconditional, not a re-check of estimate.status.
        from apps.jobs.services import JobService
        JobService.maybe_auto_release(estimate.job)
        return source
