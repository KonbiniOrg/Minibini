"""CO acceptance crystallizes add/remove/replace deltas onto Job atoms.

Triggered when a ChangeOrder transitions to ACCEPTED
(ChangeOrderService._handle_accepted), after the Job's hold has been cleared
and inside the same transaction — atom mutations are blocked while a job is
held, so crystallization runs against the released job.

Mirrors EstimateAcceptanceService.on_accept (apps/estimates/acceptance.py):

- **add** — crystallize a new atom via the same discriminator (service_item →
  Task, inventory_item → Material, is_material bare → established Material at
  a reverse-markup placeholder cost, else → skip: a plain line stays
  document-only, no atom, no source row) and, when an atom is created, link
  it back to the CO line with a ChangeOrderLineItemSource row.
- **remove** — resolve the target estimate line to its *current* atom (through
  the accepted-CO replace chain) and retire it: cancel a Task (bleps preserved
  — cancelled-task time stays on record), **release** a pending un-invoiced
  Material (earmark backed out, quantity moved to released_qty, claims kept as
  job history). Consumed / invoiced / PO-linked / terminal atoms are
  deliberately left alone — physical or billed reality is not unwound by a
  document; the human reconciles those. Historical fee-sourced targets
  (legacy SOURCE_FEE rows) are likewise left untouched.
- **replace** — crystallize the replacement first (so a cancel never leaves the
  job transiently task-less and auto-advances it), then retire the old atom.
  A bare replace line mirrors the old atom's type: a Task target yields a new
  Task on the same rate scheme/modifiers at the CO line's qty; a Material
  target a new Material on the same inventory item. A CO line carrying its
  own descriptor (service/inventory/is_material) crystallizes per that
  descriptor instead. A document-only target (adjustment line, a plain line,
  or an atom already retired) stays document-only.

Adds are processed before replaces, and replaces before removes, so a CO that
swaps out the job's only task never transiently empties the live work set.
After the walk the job's inventoried materials are (re-)earmarked, exactly as
estimate acceptance does. Billing stays with compose_agreement — the
crystallized atoms are the *work* mirror, traced via the source rows.

Idempotency: each crystallized add/replace line gets a source row and is
skipped on re-run; retirement re-checks atom state before acting.
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
            ChangeOrderAcceptanceService._crystallize(job, li, mirror=None, counts=counts)

        for li in replaces:
            if li.sources.exists():
                continue
            atoms = ChangeOrderAcceptanceService._current_atoms(li.target_line_item)
            mirror = ChangeOrderAcceptanceService._mirror_of(atoms)
            # Document-only target (adjustment line / already-retired atom) and
            # no descriptor on the CO line: the delta stays document-only.
            has_descriptor = (li.service_item_id is not None
                              or li.inventory_item_id is not None
                              or li.is_material)
            if mirror is not None or has_descriptor:
                ChangeOrderAcceptanceService._crystallize(job, li, mirror=mirror, counts=counts)
            for source_type, atom in atoms:
                ChangeOrderAcceptanceService._retire(job, source_type, atom, counts)

        for li in removes:
            for source_type, atom in ChangeOrderAcceptanceService._current_atoms(li.target_line_item):
                ChangeOrderAcceptanceService._retire(job, source_type, atom, counts)

        InventoryService.create_earmarks_for_job(job)
        return counts

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _current_atoms(target_line_item):
        """Resolve an estimate line to its *current* atoms as [(type, atom), …].

        The current atom is the one crystallized by the latest accepted-CO
        replace line targeting this estimate line (multi-CO chain), falling
        back to the estimate line's own source rows. Sources whose atom no
        longer exists (already retired) are skipped.
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

    @staticmethod
    def _mirror_of(atoms):
        """Snapshot of the primary current atom, used to type a bare replace.

        Explicit dispatch: task and material are the only mirrorable atom
        kinds. Anything else (a future source type, or the retired 'fee')
        raises rather than silently mistyping the replacement.
        """
        if not atoms:
            return None
        source_type, atom = atoms[0]
        if source_type == 'task':
            return {
                'type': 'task',
                'copy_fields': atom.copy_fields(),
                'assignee_id': atom.assignee_id,
                'worker_queue': atom.worker_queue,
            }
        if source_type == 'material':
            return {
                'type': 'material',
                'description': atom.description,
                'inventory_item': atom.inventory_item,
                'accounting_category': atom.accounting_category,
                'units': atom.units,
            }
        raise ValueError(f'unknown source_type {source_type!r}')

    # ------------------------------------------------------------------
    # Crystallization (adds and replacements)
    # ------------------------------------------------------------------

    @staticmethod
    def _crystallize(job, li, *, mirror, counts):
        """Create the atom a CO add/replace line describes and source-link it.

        Same discriminator order as estimate acceptance (service_item →
        inventory_item → is_material → skip); a bare replace line falls
        through to mirroring the retired atom's type instead. A plain line
        (no descriptor, no mirror) crystallizes nothing — it stays a
        document-only line.
        """
        from apps.estimates.models import ChangeOrderLineItemSource
        from apps.inventory.services import MaterialService
        from apps.jobs.models import Task

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

        if mirror is not None and mirror['type'] == 'task':
            fields = mirror['copy_fields']
            fields['est_qty'] = qty
            if li.description:
                fields['description'] = li.description
            task = Task.objects.create(
                job=job,
                assignee_id=mirror['assignee_id'],
                worker_queue=mirror['worker_queue'],
                **fields,
            )
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_TASK, task.pk)
            counts['tasks_created'] += 1
            return

        if mirror is not None and mirror['type'] == 'material':
            material = MaterialService.create_on_job(
                job=job, task=None,
                description=li.description or mirror['description'],
                quantity=qty,
                sell_price=li.price or Decimal('0'),
                inventory_item=mirror['inventory_item'],
                accounting_category=li.accounting_category or mirror['accounting_category'],
                units=li.units or mirror['units'],
            )
            if material.inventory_item_id is None:
                # The mirrored atom was provisional (pre-parity CO row) — the
                # replacement is still born established, never provisional.
                material = MaterialService.establish_reverse_markup(material)
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_MATERIAL, material.pk)
            counts['materials_created'] += 1
            return

        # Plain line (no service_item, no inventory_item, not marked
        # material, no mirror): stays a document-only line. No atom, no
        # source row.

    @staticmethod
    def _link(li, source_type, source_pk):
        from apps.estimates.models import ChangeOrderLineItemSource
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=li,
            source_type=source_type,
            source_pk=source_pk,
        )

    # ------------------------------------------------------------------
    # Retirement (removes and the old side of replaces)
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

        # Any other source_type (a legacy 'fee' row) falls through: nothing
        # to retire — the document delta stays document-level.
