"""CO acceptance crystallizes add deltas and applies remove/replace deltas to
Job atoms.

Triggered when a ChangeOrder transitions to ACCEPTED
(ChangeOrderService._handle_accepted), after the Job's hold has been cleared
and inside the same transaction — atom mutations are blocked while a job is
held, so crystallization runs against the released job.

The add path mirrors EstimateAcceptanceService.on_accept
(apps/estimates/acceptance.py); remove and replace are CO-specific
(amend-in-place, spec §9.3 / §11 #1):

- **add** — crystallize a new atom via the same discriminator (service_item →
  Task, inventory_item → Material, is_material bare → established Material at
  a reverse-markup placeholder cost, else → skip: a plain line stays
  document-only, no atom, no source row) and, when an atom is created, link
  it back to the CO line with a ChangeOrderLineItemSource row.
- **remove** — resolve the target estimate line to its *current* atom(s)
  (through the accepted-CO replace chain), stamp `descoped_by = co` on each
  and save it, then retire: cancel a Task (bleps preserved — cancelled-task
  time stays on record), **release** a pending un-invoiced Material (earmark
  backed out, quantity moved to released_qty, claims kept as job history).
  Exception: an atom the same CO re-claims on an add line (a removed line's
  atom pulled back from the pool — the wizard frees this CO's removed
  targets) is carried forward untouched — no stamp, no retirement.
  Consumed / invoiced / PO-linked / terminal atoms are deliberately left
  alone by retirement — physical or billed reality is not unwound by a
  document, the human reconciles those — but they are still stamped: the
  stamp is stored descope provenance, not a retirement outcome, and is what
  the invoice pool's 'struck from agreement' badge reads.
- **replace** — amends the commercial line only (the model forbids a
  crystallization descriptor on a replace line — see
  ChangeOrderLineItem.clean). Nothing is crystallized and nothing is
  retired: the target's *current* claim rows (its EstimateLineItemSource
  rows, or — chain-aware — the prior accepted replace CO line's
  ChangeOrderLineItemSource rows) simply move onto the replacement CO line —
  "backing inheritance", the same move-the-source-rows pattern
  EstimateService.revise_estimate uses across a whole revision, applied here
  to one line. The underlying Task/Material is completely untouched (same
  pk, same status): only the document line that prices/describes the work
  changes; the physical work and its claim carry forward unchanged. A
  document-only target (adjustment line, a plain line, or a target with no
  current claim rows) is a no-op beyond the CO line itself.

Adds are processed before replaces, and replaces before removes, so a CO
that also removes another of the job's tasks never transiently empties the
live work set. After the walk the job's inventoried materials are
(re-)earmarked, exactly as estimate acceptance does. Billing stays with
compose_agreement — the crystallized/inherited atoms are the *work* mirror,
traced via the source rows.

Idempotency: each crystallized add line and each claim-inheriting replace
line gets a source row and is skipped on re-run; retirement re-checks atom
state before acting.
"""
from decimal import Decimal

from django.db import transaction


class ChangeOrderAcceptanceService:

    @staticmethod
    @transaction.atomic
    def on_accept(co):
        """Apply the accepted CO's line deltas to its Job's atoms.

        Returns {'tasks_created', 'materials_created',
                 'tasks_cancelled', 'materials_removed'}.
        """
        from apps.inventory.services import InventoryService
        from apps.jobs.models import Job

        # The caller (_handle_accepted) just cleared the job's hold; fetch
        # fresh so the on-hold guards see committed state.
        job = Job.objects.get(pk=co.job_id)

        counts = {
            'tasks_created': 0, 'materials_created': 0,
            'tasks_cancelled': 0, 'materials_removed': 0,
        }

        from apps.estimates.models import ChangeOrderLineItem
        lines = list(co.changeorderlineitem_set.order_by('line_number'))
        adds = [li for li in lines if li.action == ChangeOrderLineItem.ACTION_ADD]
        replaces = [li for li in lines if li.action == ChangeOrderLineItem.ACTION_REPLACE]
        removes = [li for li in lines if li.action == ChangeOrderLineItem.ACTION_REMOVE]

        for li in adds:
            if li.sources.exists():          # already crystallized (re-run)
                continue
            ChangeOrderAcceptanceService._crystallize(job, li, counts=counts)

        for li in replaces:
            if li.sources.exists():          # already inherited (re-run)
                continue
            ChangeOrderAcceptanceService._move_claims_to(li)

        # An atom this CO re-claimed on an add line (a removed line's atom
        # pulled back from the pool — "restate the work under new terms") is
        # carried forward, not descoped: no stamp, no retirement. Computed
        # after the adds loop so it also covers freshly-crystallized claims
        # (harmless — new atoms are never remove targets).
        readded = {
            (src.source_type, src.source_pk)
            for add_li in adds for src in add_li.sources.all()
        }

        for li in removes:
            for source_type, atom in ChangeOrderAcceptanceService._current_atoms(li.target_line_item):
                if (source_type, atom.pk) in readded:
                    continue
                atom.descoped_by = co
                atom.save()
                ChangeOrderAcceptanceService._retire(job, source_type, atom, counts)

        InventoryService.create_earmarks_for_job(job)
        return counts

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _current_atoms(target_line_item):
        """Resolve an estimate line to its *current* atoms as [(type, atom), …].

        The current atom is the one whose claim row lives on the latest
        accepted-CO replace line targeting this estimate line (multi-CO
        chain, backing inheritance moved the rows there), falling back to
        the estimate line's own source rows. Sources whose atom no longer
        exists (already retired) are skipped.
        """
        from apps.estimates.models import ChangeOrder, ChangeOrderLineItem

        if target_line_item is None:
            return []

        latest_replace = (
            ChangeOrderLineItem.objects
            .filter(
                target_line_item=target_line_item,
                action=ChangeOrderLineItem.ACTION_REPLACE,
                change_order__status=ChangeOrder.STATUS_ACCEPTED,
                sources__isnull=False,
            )
            .order_by('-change_order__closed_date',
                      '-change_order__change_order_id', '-line_number')
            .distinct()
            .first()
        )
        source_rows = (latest_replace.sources.all() if latest_replace is not None
                       else target_line_item.sources.all())

        atoms = []
        for src in source_rows:
            try:
                atoms.append((src.source_type, src.resolve()))
            except Exception:
                continue  # dangling row — atom already retired
        return atoms

    # ------------------------------------------------------------------
    # Crystallization (adds only — replace no longer crystallizes)
    # ------------------------------------------------------------------

    @staticmethod
    def _crystallize(job, li, *, counts):
        """Create the atom a CO add line describes and source-link it.

        Same discriminator order as estimate acceptance (service_item →
        inventory_item → is_material → skip). A plain line (no descriptor)
        crystallizes nothing — it stays a document-only line.
        """
        from apps.estimates.models import ChangeOrderLineItemSource
        from apps.inventory.services import MaterialService

        qty = li.qty or Decimal('1')

        if li.service_item_id is not None:
            task = li.service_item.generate_task(
                job, est_qty=qty,
                description=li.description or '',
                allow_inactive_scheme=True,
            )
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_TASK, task.pk)
            counts['tasks_created'] += 1
            return

        if li.inventory_item_id is not None:
            material = MaterialService.create_on_job(
                job=job, task=None,
                description=li.description or '',
                quantity=qty,
                sell_price=li.price or Decimal('0'),
                inventory_item=li.inventory_item,
                accounting_category=li.accounting_category,
                units=li.units or 'none',
            )
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_MATERIAL, material.pk)
            counts['materials_created'] += 1
            return

        if li.is_material:
            material = MaterialService.create_on_job(
                job=job, task=None,
                description=li.description or '',
                quantity=qty,
                sell_price=li.price or Decimal('0'),
                inventory_item=None,
                accounting_category=li.accounting_category,
                units=li.units or 'none',
            )
            # Parity with estimate acceptance: established at acceptance with
            # a reverse-markup placeholder cost, never left provisional.
            material = MaterialService.establish_reverse_markup(material)
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_MATERIAL, material.pk)
            counts['materials_created'] += 1
            return

        # Plain line (no service_item, no inventory_item, not marked
        # material): stays a document-only line. No atom, no source row.

    @staticmethod
    def _link(li, source_type, source_pk):
        from apps.estimates.models import ChangeOrderLineItemSource
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=li,
            source_type=source_type,
            source_pk=source_pk,
        )

    # ------------------------------------------------------------------
    # Backing inheritance (replaces)
    # ------------------------------------------------------------------

    @staticmethod
    def _move_claims_to(replace_li):
        """Backing inheritance (spec §9.3 / §11 #1): the target line's current
        claim rows move to the replacement — same move-the-source-rows pattern
        as revise_estimate, applied to one line. Chain-aware: if a prior
        accepted CO already replaced this target, the rows live on that CO
        line's sources instead of the estimate line's."""
        from apps.estimates.models import (
            ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource)
        target = replace_li.target_line_item
        if target is None:
            return
        prior = (ChangeOrderLineItem.objects.filter(
                     target_line_item=target,
                     action=ChangeOrderLineItem.ACTION_REPLACE,
                     change_order__status=ChangeOrder.STATUS_ACCEPTED,
                     sources__isnull=False)
                 .exclude(pk=replace_li.pk)
                 .order_by('-change_order__closed_date',
                           '-change_order__change_order_id', '-line_number')
                 .distinct().first())
        rows = list(prior.sources.all()) if prior is not None else list(target.sources.all())
        for row in rows:
            # Delete before create: (source_type, source_pk) is globally
            # unique on ChangeOrderLineItemSource too, and in the chained
            # case `row` IS a ChangeOrderLineItemSource (a prior replace's
            # source) — creating first would collide with itself still
            # being live.
            source_type, source_pk = row.source_type, row.source_pk
            row.delete()
            ChangeOrderLineItemSource.objects.create(
                change_order_line_item=replace_li,
                source_type=source_type, source_pk=source_pk)

    # ------------------------------------------------------------------
    # Retirement (removes only — replace no longer retires)
    # ------------------------------------------------------------------

    @staticmethod
    def _retire(job, source_type, atom, counts):
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        from apps.inventory.models import Material
        from apps.jobs.models import Task
        from apps.jobs.services import TaskLifecycleService

        if source_type == 'task':
            cancellable = (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS,
                           Task.STATUS_BLOCKED)
            if atom.status in cancellable:
                TaskLifecycleService.cancel_task(atom.pk)
                counts['tasks_cancelled'] += 1
            return

        if source_type == 'material':
            if (atom.consumption_state != Material.CONSUMPTION_STATE_PENDING
                    or atom.is_expense_bound
                    or atom.po_line_item_id is not None
                    or InvoiceClaimService.is_invoiced(
                        InvoiceLineItemSource.SOURCE_MATERIAL, atom.pk)):
                return  # consumed / document-bound / billed: leave it alone
            # A CO target is by definition claimed, so it is *released* — the
            # named descope retirement — never deleted: the earmark is backed
            # out, quantity moves to released_qty, and the estimate/CO claims
            # keep resolving as job history.
            from apps.inventory.services import MaterialService
            MaterialService.release(atom)
            counts['materials_removed'] += 1
            return

        # Any other source_type (a future atom kind) falls through: nothing
        # to retire — the document delta stays document-level.
