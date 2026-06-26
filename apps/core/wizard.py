"""Shared base for the estimate and invoice wizards.

`BaseWizardService` holds the line-items-from-atoms logic that both
`InvoiceWizardService` and `EstimateWizardService` need. The two concrete
services subclass it, supply a small config block and a handful of hooks
for the genuine model-level divergences, and keep their own
container-specific methods (`open_for_*`, `get_source_pool`, etc.).

Methods are classmethods so `cls` resolves the subclass's hooks/config.
"""

from decimal import Decimal

from django.db import transaction, IntegrityError


class BaseWizardService:
    # ── subclass config ────────────────────────────────────────────────
    # The line item's parent-container FK name ('invoice' / 'estimate').
    container_attr = None
    # The source model's FK name to the line item.
    source_fk = None
    # The claim-conflict exception class the subclass raises.
    claim_conflict_exc = None

    # ── subclass hooks (must be implemented) ───────────────────────────
    @classmethod
    def _line_item_model(cls):
        raise NotImplementedError

    @classmethod
    def _source_model(cls):
        raise NotImplementedError

    @classmethod
    def _task_model(cls):
        """The task atom model — Task / PlanTask."""
        raise NotImplementedError

    @classmethod
    def _material_model(cls):
        """The material atom model — Material / PlanMaterial."""
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

    # ── shared atom helpers ────────────────────────────────────────────
    @classmethod
    def _atom_computed_amount(cls, atom_instance):
        """Billable amount for an atom, quantized to cents."""
        return atom_instance.compute_amount().quantize(Decimal('0.01'))

    @classmethod
    def _atom_category(cls, atom_instance):
        """The accounting category of an atom (via rate scheme for tasks)."""
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
        effective_rate)."""
        amount = cls._atom_computed_amount(atom_instance)
        units = cls._atom_units(atom_instance)
        if isinstance(atom_instance, cls._task_model()):
            qty = cls._task_actual_qty(atom_instance)
            rate = atom_instance.effective_rate()  # already quantized to cents
        else:
            qty = atom_instance.quantity
            rate = atom_instance.sell_price.quantize(Decimal('0.01'))
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
    def _expected_per_unit(cls, sum_value, qty):
        """The per-unit price the wizard would compute: round(sum/qty, 2)."""
        if not qty:
            return Decimal('0.00')
        return (sum_value / qty).quantize(Decimal('0.01'))

    @classmethod
    def _is_in_sync(cls, line_item, sum_value):
        """In sync iff price == round(sum / qty, 2). Rounding-safe."""
        if not line_item.qty:
            return False
        return line_item.price == cls._expected_per_unit(sum_value, line_item.qty)

    @classmethod
    def _uniform_scheme_bundle(cls, instances):
        """If every atom is a task sharing one ServiceItem and identical
        `active_modifiers`, return `(units, qty, price)` summarizing the
        bundle — units from the scheme, qty = summed actual quantities,
        price = the common effective rate. Otherwise None, and the caller
        falls back to qty=1 / units='none'."""
        task_model = cls._task_model()
        if not instances or not all(isinstance(i, task_model) for i in instances):
            return None
        if any(i.service_item_id is None for i in instances):
            return None
        if len({i.service_item_id for i in instances}) != 1:
            return None
        modifier_sets = {
            tuple(sorted(i.active_modifiers or [])) for i in instances
        }
        if len(modifier_sets) != 1:
            return None
        scheme = instances[0].service_item
        modifiers = instances[0].active_modifiers or []
        actual_qtys = [cls._task_actual_qty(t) for t in instances]
        if any(q is None for q in actual_qtys):
            return None
        qty = sum(actual_qtys, Decimal('0'))
        price = scheme.effective_rate(modifiers)  # already quantized to cents
        return scheme.unit_label, qty, price

    @classmethod
    def _resync_in_sync_line_item(cls, line_item):
        """After a source-set change on an in-sync line item, re-derive its
        units/qty/price. If the sources form a uniform same-scheme task
        bundle, summarize; otherwise keep qty and recompute the per-unit
        price. Saves the line item."""
        instances = [src.resolve() for src in line_item.sources.all()]
        summary = cls._uniform_scheme_bundle(instances)
        if summary is not None:
            line_item.units, line_item.qty, line_item.price = summary
        else:
            new_sum = cls._sum_sources(line_item)
            line_item.price = cls._expected_per_unit(new_sum, line_item.qty)
        line_item.save()

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
    def _create_source(cls, line_item, instance):
        cls._source_model().objects.create(
            **{cls.source_fk: line_item},
            source_type=cls._atom_source_type(instance),
            source_pk=instance.pk,
        )

    @classmethod
    def _recompute_adjustments(cls, container):
        """Recompute all percentage-adjustment lines on the container document."""
        from apps.core.adjustments import recompute_adjustments
        recompute_adjustments(
            cls._line_item_model().objects.filter(**{cls.container_attr: container})
        )

    # ── public: line items from atoms ──────────────────────────────────
    @classmethod
    def add_atoms_to_new_line_item(cls, container, atoms):
        """Create a new line item on `container` with the given atoms as
        sources. `atoms` is a list of {'type': str, 'id': N} dicts."""
        cls._validate_draft(container)

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
        # Multi-atom: summarize a uniform same-scheme task bundle, else fall
        # back to blank description, units='none', qty=1, price=total.
        if len(instances) == 1:
            description = cls._atom_description(instances[0])
            units = cls._atom_units(instances[0])
            qty, price = cls._atom_qty_and_price(instances[0], total_price)
        else:
            description = ''
            summary = cls._uniform_scheme_bundle(instances)
            if summary is not None:
                units, qty, price = summary
            else:
                units = 'none'
                qty = Decimal('1')
                price = total_price

        try:
            with transaction.atomic():
                line_item = cls._line_item_model().objects.create(
                    **{cls.container_attr: container},
                    description=description,
                    qty=qty,
                    units=units,
                    price=price,
                    accounting_category=category,
                )
                for instance in instances:
                    cls._create_source(line_item, instance)
        except IntegrityError:
            raise cls._claim_conflict(atoms)

        cls._recompute_adjustments(container)
        return line_item

    @classmethod
    def add_atoms_to_line_item(cls, line_item, atoms):
        """Append N atoms as sources to an existing line item. Re-derives an
        in-sync line item; preserves an overridden price."""
        cls._validate_draft(getattr(line_item, cls.container_attr))

        old_sum = cls._sum_sources(line_item)
        was_in_sync = cls._is_in_sync(line_item, old_sum)
        instances = [cls._resolve_atom(a) for a in atoms]
        for inst in instances:
            cls._assert_atom_billable(inst)

        try:
            with transaction.atomic():
                for instance in instances:
                    cls._create_source(line_item, instance)
                if was_in_sync:
                    cls._resync_in_sync_line_item(line_item)
        except IntegrityError:
            raise cls._claim_conflict(atoms)

        container = getattr(line_item, cls.container_attr)
        cls._recompute_adjustments(container)
        return line_item

    @classmethod
    def remove_atoms_from_line_item(cls, line_item, source_ids):
        """Remove a subset of source rows. Re-derives an in-sync line item;
        preserves an overridden price; deletes the line item if no sources
        remain. Returns {'line_item_deleted': bool}."""
        from apps.core.services import LineItemService

        container = getattr(line_item, cls.container_attr)
        cls._validate_draft(container)

        old_sum = cls._sum_sources(line_item)
        was_in_sync = cls._is_in_sync(line_item, old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                LineItemService.delete_line_item_with_renumber(line_item)
                cls._recompute_adjustments(container)
                return {'line_item_deleted': True}

            if was_in_sync:
                cls._resync_in_sync_line_item(line_item)

        cls._recompute_adjustments(container)
        return {'line_item_deleted': False}
