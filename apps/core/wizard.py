"""Shared base for the estimate and invoice wizards.

`BaseWizardService` holds the line-items-from-atoms logic that both
`InvoiceWizardService` and `EstimateWizardService` need. The two concrete
services subclass it, supply a small config block and a handful of hooks
for the genuine model-level divergences, and keep their own
container-specific methods (`open_for_*`, `get_source_pool`, etc.).

Methods are classmethods so `cls` resolves the subclass's hooks/config.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError


class BaseWizardService:
    # ── subclass config ────────────────────────────────────────────────
    # The line item's parent-container FK name ('invoice' / 'estimate').
    container_attr = None
    # The source model's FK name to the line item.
    source_fk = None
    # The claim-conflict exception class the subclass raises.
    claim_conflict_exc = None
    # Whether this document supports per-unit bundling (per-unit-lines
    # spec §2). False on the base — the invoice wizard never opts in, so it
    # inherits this unchanged. EstimateWizardService flips it True and
    # ChangeOrderWizardService inherits that.
    allows_per_unit = False

    # ── subclass hooks (must be implemented) ───────────────────────────
    @classmethod
    def _line_item_model(cls):
        raise NotImplementedError

    @classmethod
    def _source_model(cls):
        raise NotImplementedError

    @classmethod
    def _task_model(cls):
        """The task atom model — Task."""
        raise NotImplementedError

    @classmethod
    def _material_model(cls):
        """The material atom model — Material."""
        raise NotImplementedError

    @classmethod
    def _resolve_atom(cls, atom_ref):
        """Given {'type': str, 'id': N}, return the concrete atom instance."""
        raise NotImplementedError

    @classmethod
    def _atom_source_type(cls, atom_instance):
        """The source_type constant for an atom instance."""
        raise NotImplementedError

    @classmethod
    def _atom_units(cls, atom_instance):
        """The units label for an atom."""
        raise NotImplementedError

    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        """(qty, price) for a single-task line item copy-over."""
        raise NotImplementedError

    @classmethod
    def _task_actual_qty(cls, task):
        """The quantity a task contributes when summarizing a bundle."""
        raise NotImplementedError

    @classmethod
    def _validate_draft(cls, container):
        """Raise ValidationError unless the container is editable (draft)."""
        raise NotImplementedError

    @classmethod
    def _assert_atom_billable(cls, instance):
        """Override to reject atoms that aren't in a billable lifecycle state."""
        return None

    @classmethod
    def _resolve_line_category(cls, category):
        """Hook: the accounting_category actually stamped onto a freshly
        minted line item, given the derived `category` (None when the
        atom(s) carry no category of their own, or a mixed-category
        bundle collapsed to None by add_atoms_to_new_line_item).

        Base/identity implementation — the estimate and change-order
        wizards keep producing null-AC lines from null-AC atoms
        unchanged. InvoiceWizardService overrides this to stamp the
        configured fallback AccountingCategory (or raise) when category
        is None, since an invoice line must always be categorized before
        it can be sent."""
        return category

    @classmethod
    def _extra_line_kwargs(cls):
        """Extra kwargs to splat into the new line item's constructor,
        beyond the shared description/qty/units/price/accounting_category —
        e.g. the CO wizard's action='add' (a line minted from atoms is
        always an add). Defaults to none for the estimate/invoice paths."""
        return {}

    # ── shared atom helpers ────────────────────────────────────────────
    @classmethod
    def _atom_computed_amount(cls, atom_instance):
        """Billable amount for an atom, quantized to cents."""
        return atom_instance.compute_amount().quantize(Decimal('0.01'))

    @classmethod
    def _atom_category(cls, atom_instance):
        """The accounting category of an atom (the task's own field —
        task-owned-money Phase 1; no RateScheme lookup)."""
        if isinstance(atom_instance, cls._task_model()):
            return atom_instance.effective_accounting_category
        if isinstance(atom_instance, cls._material_model()):
            return atom_instance.accounting_category
        return None

    @classmethod
    def _atom_description(cls, atom_instance):
        if isinstance(atom_instance, cls._task_model()):
            return atom_instance.name
        if isinstance(atom_instance, cls._material_model()):
            return atom_instance.description
        return ''

    @classmethod
    def _atom_qty_and_price(cls, atom_instance, total_price):
        """(qty, price) for a single-atom copy-over so qty * price = total."""
        if isinstance(atom_instance, cls._material_model()):
            return atom_instance.quantity, atom_instance.sell_price
        return cls._task_qty_and_price(atom_instance, total_price)

    @classmethod
    def _atom_detail(cls, atom_instance):
        """The qty / rate / units / amount breakdown for an atom — the
        `qty units × rate = amount` line shown in the source pool. For a
        task, qty * rate == amount exactly (compute_amount is qty *
        effective_rate).

        The non-task branch is written for Material; sell_price is read
        defensively — callers rendering a doc surface must show null
        rather than 500."""
        amount = cls._atom_computed_amount(atom_instance)
        units = cls._atom_units(atom_instance)
        if isinstance(atom_instance, cls._task_model()):
            qty = cls._task_actual_qty(atom_instance)
            rate = atom_instance.effective_rate()  # already quantized to cents
        else:
            qty = atom_instance.quantity
            sell_price = getattr(atom_instance, 'sell_price', None)
            rate = None if sell_price is None else sell_price.quantize(Decimal('0.01'))
        return {'qty': qty, 'rate': rate, 'units': units, 'amount': amount}

    # ── line-item sync helpers ─────────────────────────────────────────
    @classmethod
    def _sum_sources(cls, line_item):
        """Sum the computed amounts of all source atoms on a line item."""
        total = Decimal('0.00')
        for src in line_item.sources.all():
            total += cls._atom_computed_amount(src.resolve())
        return total

    @classmethod
    def _sum_per_unit_sources(cls, line_item, sources=None):
        """Σ over resolvable source rows of `per_unit_qty × atom-rate` — the
        per-unit-lines spec §2/§3 reading: NO division by qty (a per_unit
        line's claimed atoms already describe ONE unit, not the whole-job
        total). atom-rate is `task.effective_rate()` for a task claim,
        `sell_price` (quantized to cents) for a material claim. A row is
        skipped when its own `per_unit_qty` is unset (not yet snapshotted)
        or its atom is dangling (already deleted out from under the claim —
        mirrors `_resolve_sources`' dangling tolerance) rather than either
        raising or contributing a bogus amount.

        `sources`: optional explicit iterable of raw source rows, for a
        caller whose per-unit claims don't live on `line_item.sources`
        itself — e.g. a draft/open replace ChangeOrderLineItem, whose
        claims still sit on the target EstimateLineItem pre-acceptance
        (see `_sources_for_replace` in apps/api/change_orders/serializers.py).
        Defaults to `line_item.sources.all()`."""
        from django.core.exceptions import ObjectDoesNotExist
        total = Decimal('0.00')
        task_model = cls._task_model()
        if sources is None:
            sources = line_item.sources.all()
        for src in sources:
            if src.per_unit_qty is None:
                continue
            try:
                instance = src.resolve()
            except ObjectDoesNotExist:
                continue
            if isinstance(instance, task_model):
                rate = instance.effective_rate()
            else:
                sell_price = getattr(instance, 'sell_price', None)
                if sell_price is None:
                    continue
                rate = sell_price.quantize(Decimal('0.01'))
            total += src.per_unit_qty * rate
        return total

    @classmethod
    def _line_sum(cls, line_item):
        """Dispatcher for the sum fed into `_is_in_sync`: the per-unit sum
        when the line is `per_unit`, else the whole-line source sum
        (today's rule, unchanged). `getattr` (not a direct attribute read)
        keeps InvoiceLineItem — which carries no `per_unit` field — safely
        on the base `_sum_sources` path."""
        if getattr(line_item, 'per_unit', False):
            return cls._sum_per_unit_sources(line_item)
        return cls._sum_sources(line_item)

    @classmethod
    def _expected_per_unit(cls, sum_value, qty):
        """The per-unit price the wizard would compute: round(sum/qty, 2)."""
        if not qty:
            return Decimal('0.00')
        return (sum_value / qty).quantize(Decimal('0.01'))

    @classmethod
    def _is_in_sync(cls, line_item, sum_value):
        """In sync iff price matches `sum_value`.

        A `per_unit` line's claimed atoms already describe ONE unit of
        qty (per-unit-lines spec §2), so its price is compared directly
        against the (quantized) sum — NO division by qty. A whole-line
        (per_unit=False) line keeps today's rule unchanged:
        price == round(sum / qty, 2), rounding-safe, false for qty=0."""
        if getattr(line_item, 'per_unit', False):
            return line_item.price == sum_value.quantize(Decimal('0.01'))
        if not line_item.qty:
            return False
        return line_item.price == cls._expected_per_unit(sum_value, line_item.qty)

    @classmethod
    def _uniform_money_bundle(cls, instances):
        """If every atom is a task sharing identical `(rate, unit_label,
        active_modifiers)`, return `(units, qty, price)` summarizing the
        bundle — units/price from the shared task money fields, qty =
        summed actual quantities. Otherwise None, and the caller falls
        back to qty=1 / units='none'.

        Uniformity is judged on the tasks' own money fields, not on
        `source_scheme` provenance — two tasks stamped from different
        presets (or one stamped and one hand-edited) still bundle if their
        current rate/unit/modifiers agree (task-owned-money Phase 1).

        Mirrored client-side (approximately — the source-pool atom shape
        exposes effective_rate + unit_label but not the raw stamped
        `rate`/`active_modifiers` this method compares) by BundleModal's
        `deriveMultiAtomSeed`
        (frontend/src/components/docsurface/BundleModal.svelte) to seed
        the bundle modal's qty/units/price fields for a uniform multi-atom
        selection. If this method's uniformity rule changes, check that
        seed function too."""
        task_model = cls._task_model()
        if not instances or not all(isinstance(i, task_model) for i in instances):
            return None
        if any(i.rate is None for i in instances):
            return None
        if len({i.rate for i in instances}) != 1:
            return None
        if len({i.unit_label for i in instances}) != 1:
            return None
        modifier_sets = {
            tuple(sorted(
                (m['key'], Decimal(str(m['percent'])))
                for m in (i.active_modifiers or [])
            ))
            for i in instances
        }
        if len(modifier_sets) != 1:
            return None
        unit_label = instances[0].unit_label
        actual_qtys = [cls._task_actual_qty(t) for t in instances]
        if any(q is None for q in actual_qtys):
            return None
        qty = sum(actual_qtys, Decimal('0'))
        price = instances[0].effective_rate()  # already quantized to cents
        return unit_label, qty, price

    @classmethod
    def _resync_in_sync_line_item(cls, line_item):
        """After a source-set change on an in-sync line item, re-derive its
        price (whole-line: units/qty/price). Saves via
        LineItemService.save_line_item.

        A `per_unit` line's price is recomputed straight from `_line_sum`
        (the per-unit Σ, no division) with qty/units left untouched — a
        per-unit line's price doesn't depend on qty, so the whole-line
        uniform-money-bundle resummarization (which folds multiple same-
        scheme tasks' actual quantities into qty) doesn't apply.

        A whole-line (per_unit=False) line keeps today's rule unchanged:
        if the sources form a uniform-money task bundle, summarize
        (units/qty/price); otherwise keep qty and recompute price =
        round(sum/qty, 2)."""
        from apps.core.services import LineItemService
        if getattr(line_item, 'per_unit', False):
            line_item.price = cls._line_sum(line_item).quantize(Decimal('0.01'))
        else:
            instances = [src.resolve() for src in line_item.sources.all()]
            summary = cls._uniform_money_bundle(instances)
            if summary is not None:
                line_item.units, line_item.qty, line_item.price = summary
            else:
                new_sum = cls._line_sum(line_item)
                line_item.price = cls._expected_per_unit(new_sum, line_item.qty)
        LineItemService.save_line_item(line_item)

    # ── claim-conflict helper ──────────────────────────────────────────
    @classmethod
    def _claim_conflict(cls, atoms):
        """Re-query which of `atoms` are already claimed and return the
        configured claim-conflict exception for them."""
        existing = set(
            cls._source_model().objects
            .filter(source_type__in=[a['type'] for a in atoms])
            .values_list('source_type', 'source_pk')
        )
        conflicts = [a for a in atoms if (a['type'], a['id']) in existing]
        return cls.claim_conflict_exc(atom_ids=conflicts)

    @classmethod
    def _create_source(cls, line_item, instance, **extra):
        cls._source_model().objects.create(
            **{cls.source_fk: line_item},
            source_type=cls._atom_source_type(instance),
            source_pk=instance.pk,
            **extra,
        )

    # ── per-unit bundling (per-unit-lines spec §2) ─────────────────────
    @classmethod
    def _stamp_atom_per_unit(cls, instance, atom_ref, qty):
        """Snapshot `instance`'s CURRENT per-unit values, then stamp the
        atom itself to the whole-job total for `qty` units and `.save()`
        it directly (never `QuerySet.update()`) — atoms always store
        totals; only the claim row remembers the per-unit agreement
        (spec §2).

        For a task atom, an atom-supplied `'per_unit_worker_time'`
        (ISO-8601 duration string — the modal's input for a task lacking
        an `est_worker_time`) SETS the task's `est_worker_time` first, so
        both the snapshot and the stamp see it.

        Returns `(per_unit_qty, per_unit_worker_time)` for the caller to
        snapshot onto the new source row (`per_unit_worker_time` is
        always None for a material atom).

        Deliberately bypasses `hours_pair_fill` — that helper only runs
        in TaskService/api paths; both task fields are set explicitly
        here so no pair-fill is wanted.
        """
        task_model = cls._task_model()
        material_model = cls._material_model()
        if isinstance(instance, task_model):
            worker_time_input = atom_ref.get('per_unit_worker_time')
            if worker_time_input is not None:
                from django.utils.dateparse import parse_duration
                parsed = parse_duration(worker_time_input)
                if parsed is None:
                    raise ValidationError(
                        {'per_unit_worker_time': ['Enter a valid duration.']})
                instance.est_worker_time = parsed
            per_unit_qty = instance.est_qty
            per_unit_worker_time = instance.est_worker_time
            instance.est_qty = (
                (per_unit_qty * qty).quantize(Decimal('0.01'))
                if per_unit_qty is not None else None
            )
            instance.est_worker_time = (
                per_unit_worker_time * float(qty)
                if per_unit_worker_time is not None else None
            )
            instance.save()
            return per_unit_qty, per_unit_worker_time
        if isinstance(instance, material_model):
            per_unit_qty = instance.quantity
            instance.quantity = (per_unit_qty * qty).quantize(Decimal('0.01'))
            instance.save()
            return per_unit_qty, None
        raise ValidationError('Per-unit lines only support task and material atoms.')

    # ── public: line items from atoms ──────────────────────────────────
    @classmethod
    def add_atoms_to_new_line_item(cls, container, atoms, *, overrides=None, per_unit=False):
        """Create a new line item on `container` with the given atoms as
        sources. `atoms` is a list of {'type': str, 'id': N} dicts; a task
        atom may also carry `'per_unit_worker_time'` (ISO-8601 duration
        string, per-unit calls only — the modal's input for a task lacking
        an `est_worker_time`).

        overrides: optional {'description','qty','units','price'} applied
        over the derived defaults before save (bundle-modal authoring). A
        provided qty/price pair wins; partial overrides merge onto the
        derivation. Claims/atomicity unchanged.

        per_unit: when True, requires `overrides['qty']` > 0 (that qty is
        the per-unit multiplier) and requires `cls.allows_per_unit`
        (estimate/CO wizards only — the invoice wizard never opts in).
        Each atom is snapshotted to its claim row and stamped to the
        whole-job total for that qty (see `_stamp_atom_per_unit`); the new
        line is saved with `per_unit=True`. Price/qty/units/description
        still come from `overrides` (WYSIWYG — the modal always sends all
        four) regardless of per_unit."""
        cls._validate_draft(container)

        if per_unit and not cls.allows_per_unit:
            raise ValidationError('This document does not support per-unit lines.')

        if overrides:
            unknown = set(overrides) - {'description', 'qty', 'units', 'price'}
            if unknown:
                raise ValidationError(
                    f"Unknown override field(s): {', '.join(sorted(unknown))}."
                )

        if per_unit:
            qty_override = overrides.get('qty') if overrides else None
            if not qty_override or qty_override <= 0:
                raise ValidationError(
                    {'qty': ['A quantity is required for per-unit lines.']})

        instances = [cls._resolve_atom(a) for a in atoms]
        for inst in instances:
            cls._assert_atom_billable(inst)
        total_price = sum(
            (cls._atom_computed_amount(i) for i in instances),
            Decimal('0.00'),
        )
        categories = {cls._atom_category(i) for i in instances}
        category = categories.pop() if len(categories) == 1 else None

        # Single atom: copy over description/units/qty/price from the atom.
        # Multi-atom: summarize a uniform-money task bundle, else fall
        # back to blank description, units='none', qty=1, price=total.
        if len(instances) == 1:
            description = cls._atom_description(instances[0])
            units = cls._atom_units(instances[0])
            qty, price = cls._atom_qty_and_price(instances[0], total_price)
        else:
            description = ''
            summary = cls._uniform_money_bundle(instances)
            if summary is not None:
                units, qty, price = summary
            else:
                units = 'none'
                qty = Decimal('1')
                price = total_price

        if overrides:
            if 'description' in overrides:
                description = overrides['description']
            if 'qty' in overrides:
                qty = overrides['qty']
            if 'units' in overrides:
                units = overrides['units']
            if 'price' in overrides:
                price = overrides['price']

        from apps.core.services import LineItemService
        try:
            with transaction.atomic():
                line_item = cls._line_item_model()(
                    **{cls.container_attr: container},
                    description=description,
                    qty=qty,
                    units=units,
                    price=price,
                    accounting_category=cls._resolve_line_category(category),
                    **cls._extra_line_kwargs(),
                    **({'per_unit': True} if per_unit else {}),
                )
                LineItemService.save_line_item(line_item)
                for instance, atom_ref in zip(instances, atoms):
                    if per_unit:
                        pu_qty, pu_worker_time = cls._stamp_atom_per_unit(
                            instance, atom_ref, qty)
                        cls._create_source(
                            line_item, instance,
                            per_unit_qty=pu_qty,
                            per_unit_worker_time=pu_worker_time,
                        )
                    else:
                        cls._create_source(line_item, instance)
        except IntegrityError:
            raise cls._claim_conflict(atoms)

        return line_item

    @classmethod
    def add_atoms_to_line_item(cls, line_item, atoms):
        """Append N atoms as sources to an existing line item. Re-derives an
        in-sync line item; preserves an overridden price."""
        cls._validate_draft(getattr(line_item, cls.container_attr))

        old_sum = cls._line_sum(line_item)
        was_in_sync = cls._is_in_sync(line_item, old_sum)
        instances = [cls._resolve_atom(a) for a in atoms]
        for inst in instances:
            cls._assert_atom_billable(inst)

        from apps.core.services import LineItemService
        from apps.core.adjustments import recompute_adjustments
        try:
            with transaction.atomic():
                for instance in instances:
                    cls._create_source(line_item, instance)
                if was_in_sync:
                    # _resync_in_sync_line_item calls save_line_item, which recomputes
                    cls._resync_in_sync_line_item(line_item)
        except IntegrityError:
            raise cls._claim_conflict(atoms)

        if not was_in_sync:
            # Price was overridden (no resync/save), but the source set changed;
            # still need to recompute any adjustment lines on the document.
            container = getattr(line_item, cls.container_attr)
            recompute_adjustments(
                LineItemService.get_line_items_for_container(container, type(line_item))
            )
        return line_item

    @classmethod
    def remove_atoms_from_line_item(cls, line_item, source_ids):
        """Remove a subset of source rows. Re-derives an in-sync line item;
        preserves an overridden price; deletes the line item if no sources
        remain. Returns {'line_item_deleted': bool}."""
        from apps.core.services import LineItemService
        from apps.core.adjustments import recompute_adjustments

        container = getattr(line_item, cls.container_attr)
        cls._validate_draft(container)

        old_sum = cls._line_sum(line_item)
        was_in_sync = cls._is_in_sync(line_item, old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                # delete_line_item_with_renumber now recomputes internally
                LineItemService.delete_line_item_with_renumber(line_item)
                return {'line_item_deleted': True}

            if was_in_sync:
                # _resync_in_sync_line_item calls save_line_item, which recomputes
                cls._resync_in_sync_line_item(line_item)

        if not was_in_sync:
            # Price overridden; no resync/save happened, but adjustments may need refresh.
            recompute_adjustments(
                LineItemService.get_line_items_for_container(container, type(line_item))
            )
        return {'line_item_deleted': False}
