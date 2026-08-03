"""CO acceptance crystallizes add/remove/replace deltas onto Job atoms.

Triggered when a ChangeOrder transitions to ACCEPTED
(ChangeOrderService._handle_accepted), after the Job's hold has been cleared
and inside the same transaction — atom mutations are blocked while a job is
held, so crystallization runs against the released job.

Mirrors EstimateAcceptanceService.on_accept (apps/estimates/acceptance.py):

- **add** — crystallize a new atom via the same explicit discriminator
  (service_item → Task, inventory_item → Material, freeform_kind='material' bare →
  established Material at a reverse-markup placeholder cost, freeform_kind='work'
  bare → flat Task, else → Fee) and link it back to the CO line with a
  ChangeOrderLineItemSource row.
- **remove** — resolve the target estimate line to its *current* atom (through
  the accepted-CO replace chain) and retire it: cancel a service-backed Task
  (bleps preserved — cancelled-task time stays on record), **delete** an
  un-invoiced flat work Task (task-owned money Phase 2, Task 3 — a bare hand-
  line's Task never had a lifecycle promise beyond the document that
  crystallized it, so it is retired like a Fee, not cancelled; the same
  bleps/in-progress/complete guards that block a plain task delete still
  apply and surface as a ValidationError), **release** a pending un-invoiced
  Material (earmark backed out, quantity moved to released_qty, claims kept as
  job history), delete an un-invoiced Fee. Consumed / invoiced / PO-linked /
  terminal atoms are deliberately left alone — physical or billed reality is
  not unwound by a document; the human reconciles those.
- **replace** — crystallize the replacement first (so a cancel never leaves the
  job transiently task-less and auto-advances it), then retire the old atom.
  A bare replace line mirrors the old atom's type: a Task target yields a new
  Task on the same rate scheme/modifiers at the CO line's qty; a Material
  target a new Material on the same inventory item; a Fee target a new Fee.
  A CO line carrying its own descriptor (service/inventory/freeform_kind)
  crystallizes per that descriptor instead. A document-only target (adjustment
  line, or an atom already retired) stays document-only.

Adds are processed before replaces, and replaces before removes, so a CO that
swaps out the job's only task never transiently empties the live work set.
After the walk the job's inventoried materials are (re-)earmarked, exactly as
estimate acceptance does. Billing stays with compose_agreement — the
crystallized atoms are the *work* mirror, traced via the source rows so the
invoice claims each crystallized Fee exactly once (see compose_agreement's
source_fee_id).

Idempotency: each crystallized add/replace line gets a source row and is
skipped on re-run; retirement re-checks atom state before acting.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction


class ChangeOrderAcceptanceService:

    @staticmethod
    @transaction.atomic
    def on_accept(co):
        """Apply the accepted CO's line deltas to its Job's atoms.

        Returns {'tasks_created', 'materials_created', 'fees_created',
                 'work_tasks_created', 'tasks_cancelled', 'materials_removed',
                 'fees_removed', 'work_tasks_removed'}.
        """
        from apps.inventory.services import InventoryService
        from apps.jobs.models import Job

        # The caller (_handle_accepted) just cleared the job's hold; fetch
        # fresh so the on-hold guards see committed state.
        job = Job.objects.get(pk=co.job_id)

        counts = {
            'tasks_created': 0, 'materials_created': 0, 'fees_created': 0,
            'work_tasks_created': 0,
            'tasks_cancelled': 0, 'materials_removed': 0, 'fees_removed': 0,
            'work_tasks_removed': 0,
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
            # freeform_kind='work'/'fee' are real descriptors (task-owned
            # money Phase 2, Task 3 and the I4 review finding) and force
            # crystallization here exactly like 'material' already does — an
            # explicit KIND_FEE must not be treated as "no descriptor" just
            # because Fee is also the fallback default below: a REPLACE line
            # explicitly marked 'fee' targeting a document-only/no-mirror
            # atom (e.g. a task atom whose mirror this line intentionally
            # overrides) still needs to crystallize a Fee at THIS line's
            # price. Only a truly bare line (freeform_kind unset, no
            # explicit choice at all) is the case that stays document-only
            # when there's nothing to mirror.
            has_descriptor = (li.service_item_id is not None
                              or li.inventory_item_id is not None
                              or li.freeform_kind in (li.KIND_MATERIAL, li.KIND_WORK, li.KIND_FEE))
            if mirror is not None or has_descriptor:
                ChangeOrderAcceptanceService._crystallize(job, li, mirror=mirror, counts=counts)
            for source_type, atom, claiming_kind in atoms:
                ChangeOrderAcceptanceService._retire(job, source_type, atom, claiming_kind, counts)

        for li in removes:
            for source_type, atom, claiming_kind in ChangeOrderAcceptanceService._current_atoms(li.target_line_item):
                ChangeOrderAcceptanceService._retire(job, source_type, atom, claiming_kind, counts)

        InventoryService.create_earmarks_for_job(job)
        return counts

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _current_atoms(target_line_item):
        """Resolve an estimate line to its *current* atoms as
        [(type, atom, claiming_kind), …].

        The current atom is the one crystallized by the latest accepted-CO
        replace line targeting this estimate line (multi-CO chain), falling
        back to the estimate line's own source rows. Sources whose atom no
        longer exists (already retired) are skipped.

        ``claiming_kind`` is the CLAIMING line's own ``freeform_kind`` (the
        EstimateLineItem or ChangeOrderLineItem whose source row currently
        resolves to this atom) — 'work' iff that line crystallized a bare
        freeform_kind='work' hand-line; NULL for every other line shape
        (service_item lines, inventory_item lines, and atom-backed lines
        whose atom was claimed onto them wholesale — e.g. the wizard's
        add_atoms_to_new_line_item, which never sets freeform_kind). _retire
        uses this, NOT any field on the atom itself, to tell a flat work Task
        apart from every other Task — a Task's own fields (service_item_id,
        source_scheme) can't: a plain ad-hoc Task made via
        TaskService.create_direct also has service_item_id=None, and a bare
        CO replace's mirrored Task also ends up with source_scheme=None
        (copy_fields() excludes it as pure provenance) regardless of what it
        mirrors.
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
                atom = src.resolve()
            except Exception:
                continue  # dangling row — atom already retired
            # EstimateLineItemSource carries `estimate_line_item`;
            # ChangeOrderLineItemSource carries `change_order_line_item`.
            # Exactly one of the two attributes exists on any given `src`.
            claiming_line = (getattr(src, 'estimate_line_item', None)
                              or getattr(src, 'change_order_line_item', None))
            claiming_kind = claiming_line.freeform_kind if claiming_line is not None else None
            atoms.append((src.source_type, atom, claiming_kind))
        return atoms

    @staticmethod
    def _mirror_of(atoms):
        """Snapshot of the primary current atom, used to type a bare replace."""
        if not atoms:
            return None
        source_type, atom, claiming_kind = atoms[0]
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
        return {
            'type': 'fee',
            'description': atom.description,
            'accounting_category': atom.accounting_category,
        }

    # ------------------------------------------------------------------
    # Crystallization (adds and replacements)
    # ------------------------------------------------------------------

    @staticmethod
    def _crystallize(job, li, *, mirror, counts):
        """Create the atom a CO add/replace line describes and source-link it.

        Same discriminator order as estimate acceptance (service_item →
        inventory_item → freeform_kind='material' → freeform_kind='work' → Fee);
        a bare replace line falls through to mirroring the retired atom's type
        instead.
        """
        from apps.estimates.models import ChangeOrderLineItemSource
        from apps.inventory.services import MaterialService
        from apps.jobs.models import Fee, Task

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

        if li.freeform_kind == li.KIND_MATERIAL:
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

        if li.freeform_kind == li.KIND_WORK:
            # Defensive guard: entry-time validation (Task 4) is meant to
            # keep a negative-price work line from ever reaching acceptance,
            # but CO acceptance must not mint a negative-rate Task regardless.
            if li.price is not None and li.price < 0:
                raise ValidationError(
                    f'Change order line "{li.description or "(no description)"}" '
                    f'has a negative price. Work lines cannot bill a negative rate.'
                )
            task = Task(
                job=job, name=(li.description or 'Work')[:100],
                description=li.description or '',
                qty_source=Task.QTY_ENTERED, est_qty=li.qty, rate=li.price,
                unit_label=li.units, accounting_category=li.accounting_category,
                source_scheme=None,
            )
            task.save()
            from apps.jobs.services import JobService
            JobService.mark_work_reopened(job)
            ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_TASK, task.pk)
            counts['work_tasks_created'] += 1
            return

        # Mirror-the-old-atom's-type only applies to a truly BARE replace
        # line (freeform_kind is None — MATERIAL/WORK already returned
        # above). An explicit freeform_kind='fee' (I4 review finding) must
        # NEVER fall into a mirror branch just because the target's current
        # atom happens to be a Task/Material — it crystallizes a Fee at
        # THIS line's price via the fallback section below, same as when
        # there's no mirror at all.
        if mirror is not None and mirror['type'] == 'task' and li.freeform_kind is None:
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

        if mirror is not None and mirror['type'] == 'material' and li.freeform_kind is None:
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

        # Fee (default). AC comes from the line, falling back to the retired
        # fee's category on a bare replace. Same defensive guard as estimate
        # acceptance: Fee.accounting_category is NOT NULL.
        accounting_category = li.accounting_category or (
            mirror.get('accounting_category') if mirror else None)
        if accounting_category is None:
            raise ValidationError(
                f'Change order line "{li.description or "(no description)"}" '
                f'has no accounting category. All added line items must have '
                f'an accounting category before the change order can be accepted.'
            )
        # M1 review finding: a bare replace line (freeform_kind=None, no
        # price set) mirroring a Fee target falls through to here with
        # `li.price or Decimal('0')` — same defensive zero-rate guard Fee's
        # own service layer enforces (FeeService._reject_zero_unit_rate),
        # needed here because this branch calls Fee.objects.create()
        # directly, bypassing that service guard exactly like the
        # AC-required guard above it already does.
        unit_rate = li.price or Decimal('0')
        if unit_rate == Decimal('0'):
            raise ValidationError(
                f'Change order line "{li.description or "(no description)"}" '
                f'would crystallize a Fee with a zero rate. Set a non-zero price.'
            )
        fee = Fee.objects.create(
            job=job,
            description=li.description or '',
            quantity=qty,
            unit_rate=unit_rate,
            accounting_category=accounting_category,
            sort_order=li.line_number or 0,
        )
        ChangeOrderAcceptanceService._link(li, ChangeOrderLineItemSource.SOURCE_FEE, fee.pk)
        counts['fees_created'] += 1

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
    def _retire(job, source_type, atom, claiming_kind, counts):
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        from apps.inventory.models import Material
        from apps.jobs.models import Blep, Task
        from apps.jobs.services import TaskLifecycleService
        from apps.estimates.models import EstimateLineItem

        if source_type == 'task':
            if claiming_kind == EstimateLineItem.KIND_WORK:
                # Flat work task (task-owned money Phase 2, Task 3): its
                # CLAIMING line (the EstimateLineItem or ChangeOrderLineItem
                # whose source row currently resolves to this atom) is a bare
                # freeform_kind='work' hand-line — it was crystallized
                # straight from that hand-line, never carried a
                # catalog/scheduling promise, and has (normally) no bleps yet
                # — retire it like a Fee (delete), not like a service-backed
                # or ad-hoc/wizard-claimed Task (cancel, bleps preserved).
                # Do NOT discriminate on any field of the atom itself
                # (service_item_id, source_scheme) — see _current_atoms'
                # docstring for why neither reliably identifies this
                # population. Re-apply the guards TaskService.delete_task
                # enforces (bleps, in-progress/complete) so the same failure
                # surfaces as a ValidationError; the "claimed by a non-draft
                # document" guard from delete_task is deliberately NOT
                # re-applied here — retiring THIS claim (the CO/estimate
                # source row that resolved this atom) is exactly what this
                # call is doing, mirroring how the Fee branch below skips
                # atom_is_claimed and only checks is_invoiced.
                if InvoiceClaimService.is_invoiced(
                        InvoiceLineItemSource.SOURCE_TASK, atom.pk):
                    return  # billed money: leave it alone
                if atom.status in (Task.STATUS_IN_PROGRESS, Task.STATUS_COMPLETE):
                    raise ValidationError(
                        f'Cannot retire a {atom.status} work task via change '
                        f'order. Cancel it instead.'
                    )
                if Blep.objects.filter(task=atom).exists():
                    raise ValidationError(
                        'Cannot retire a work task that has time entries via '
                        'change order. Cancel it instead.'
                    )
                if atom.materials.filter(
                        consumption_state=Material.CONSUMPTION_STATE_CONSUMED).exists():
                    raise ValidationError(
                        'Cannot retire a work task with consumed materials via '
                        'change order. Cancel it instead.'
                    )
                atom.delete()  # Task.delete() purges its source rows
                counts['work_tasks_removed'] += 1
                return
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

        if source_type == 'fee':
            if InvoiceClaimService.is_invoiced(
                    InvoiceLineItemSource.SOURCE_FEE, atom.pk):
                return
            atom.delete()  # Fee.delete() purges its source rows
            counts['fees_removed'] += 1
