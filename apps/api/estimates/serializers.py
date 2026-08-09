from decimal import Decimal
from rest_framework import serializers
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.core.units import UnitsField
from apps.api.mixins import JobScopedCanManageMixin


def _resolve_sources(line):
    """Resolve every source row on a line, skipping any dangling row (its
    atom already deleted out from under the claim — legal pre-purge state,
    see estimates-and-prices.md §6.2) rather than letting `resolve()`
    raise ObjectDoesNotExist. A line whose sources are ALL dangling
    resolves to an empty list, so callers treat it exactly as if the line
    had no sources at all; a partially-dangling line yields only the
    resolvable instances. Used by both `derive_estimate_backing` and
    `get_backing_total` so a line's sources are read from the DB once."""
    from django.core.exceptions import ObjectDoesNotExist
    resolved = []
    for src in line.sources.all():
        try:
            resolved.append(src.resolve())
        except ObjectDoesNotExist:
            continue
    return resolved


def derive_estimate_backing(line):
    """Classify how an estimate line's price is currently backed. Same
    "derive on every read, never store" style as InvoiceLineItemSerializer's
    module-level `derive_backing` (Task 5), reusing the wizard's own
    in-sync rule (`BaseWizardService._sum_sources`/`_is_in_sync`) — but the
    estimate enum is domain-specific: no deposit/agreement concepts, and it
    splits catalog vs hand-authored vs sourced lines instead.

    1. `adjustment_service_id` set -> 'adjustment'.
    2. `service_item_id` or `inventory_item_id` set -> 'from_catalog'. A
       bare `is_material=True` line with no `inventory_item` does NOT
       count — it stays 'hand' until crystallization narrows it further.
    3. Has RESOLVABLE claimed source rows (via `_resolve_sources`, which
       skips any dangling row — its atom already deleted, a legal
       pre-purge state — rather than 500ing; a line whose sources are
       ALL dangling is treated as having none, falling through to rule 4;
       a partially-dangling line sums/classifies only what still
       resolves):
       - not in sync with the source sum (price != round(sum/qty, 2)) ->
         'edited', regardless of source kind.
       - in sync, any task among the sources -> 'planned_work'.
       - in sync, materials only -> 'planned_materials'.
    4. Otherwise (no adjustment, no catalog ref, no resolvable sources) ->
       'hand'.

    `backing` is designed for DRAFT authoring surfaces (the estimate
    wizard's chip labels), not as a general-purpose lifecycle indicator.
    Two consequences of rule 2 firing before rule 3 fall out of that scope
    deliberately and are worth spelling out:

    - Post-acceptance, a service-item or inventory-item line KEEPS
      'from_catalog' even after `EstimateAcceptanceService.on_accept`
      crystallizes it into a live Task/Material source on that same line
      (see apps/estimates/acceptance.py) — rule 2 still fires first, so
      'from_catalog' means "this line is a catalog descriptor" for the
      line's whole life, not "not yet crystallized". This is intentional,
      not a staleness bug.
    - A legacy hand line crystallized into a fee source (pre-Fee-removal
      data) falls through the task-detection loop to 'planned_materials'.
      That is a known mislabel, confined to accepted (read-only) estimates,
      where the draft-only wizard chip surface never renders it anyway.
    """
    if line.adjustment_service_id is not None:
        return 'adjustment'

    if line.service_item_id is not None or line.inventory_item_id is not None:
        return 'from_catalog'

    resolved = _resolve_sources(line)
    if resolved:
        sum_value = sum(
            (EstimateWizardService._atom_computed_amount(i) for i in resolved),
            Decimal('0.00'),
        )
        if not EstimateWizardService._is_in_sync(line, sum_value):
            return 'edited'
        from apps.jobs.models import Task
        if any(isinstance(i, Task) for i in resolved):
            return 'planned_work'
        return 'planned_materials'

    return 'hand'


class EstimateLineItemSourceSerializer(serializers.Serializer):
    """Serializer for EstimateLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()
    qty = serializers.SerializerMethodField()
    units = serializers.SerializerMethodField()
    rate = serializers.SerializerMethodField()

    def _resolve_or_none(self, obj):
        # A dangling row (atom deleted out from under the claim — pre-purge
        # data, or a race) must render as null, never 500 the list endpoint.
        from django.core.exceptions import ObjectDoesNotExist
        try:
            return obj.resolve()
        except ObjectDoesNotExist:
            return None

    def get_description(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return instance.name
        return instance.description  # Material / legacy Fee

    def get_computed_amount(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        # Estimate line items project the ESTIMATE quote (est_qty), not actuals.
        # A Task bills actuals via compute_amount() — $0 until it's worked — so the
        # estimate must use compute_estimate_amount() instead; Material has
        # only compute_amount() (no est/actual split) and falls through.
        amount_fn = getattr(instance, 'compute_estimate_amount', instance.compute_amount)
        return str(amount_fn().quantize(Decimal('0.01')))

    # qty/units/rate values here are display-only, purely derived from the
    # resolved instance, and feed a doc-surface's nested atom-row (never
    # re-summed into the line's own total — that stays
    # `computed_amount`/`backing_total`).
    #
    # The non-Task fallthroughs are written for Material but may also receive
    # a LEGACY resolved Fee (pre-Fee-removal source rows survive until Task
    # 6's purge). Fee shares description/quantity/compute_amount/units with
    # Material; the attribute it lacks (sell_price) is read defensively —
    # null over 500, same philosophy as `_resolve_or_none` for dangling rows.
    def get_qty(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return str(instance.est_qty if instance.est_qty is not None else Decimal('0'))
        return str(instance.quantity)  # Material / legacy Fee

    def get_units(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return instance.unit_label or 'none'
        # Material's units field; a legacy Fee's `units` property is 'none'.
        return getattr(instance, 'units', None) or 'none'

    def get_rate(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return str(instance.effective_rate())
        # Material's sell_price; a legacy Fee has none → null, not a 500.
        sell_price = getattr(instance, 'sell_price', None)
        return None if sell_price is None else str(sell_price)


class EstimateLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    sources = EstimateLineItemSourceSerializer(many=True, read_only=True)
    adjustment_service_detail = serializers.SerializerMethodField()
    service_item_detail = serializers.SerializerMethodField()
    backing = serializers.SerializerMethodField()
    backing_total = serializers.SerializerMethodField()

    class Meta:
        model = EstimateLineItem
        fields = [
            'line_item_id', 'line_number', 'inventory_item', 'service_item', 'is_material',
            'qty', 'units', 'description', 'price',
            'accounting_category',
            'adjustment_service', 'adjustment_target_categories',
            'adjustment_service_detail', 'service_item_detail',
            'sources', 'backing', 'backing_total',
        ]
        read_only_fields = ['line_item_id']

    def get_backing(self, obj):
        return derive_estimate_backing(obj)

    def get_backing_total(self, obj):
        """Sum of source compute_estimate_amount()/compute_amount() — the
        "work totals $X" reference figure; null when the line has no
        resolvable sources (no source rows at all, OR every source row is
        dangling — see `_resolve_sources`). Independent of `backing`: an
        out-of-sync 'edited' sourced line still reports its total; a
        partially-dangling line sums only the resolvable sources."""
        resolved = _resolve_sources(obj)
        if not resolved:
            return None
        total = sum(
            (EstimateWizardService._atom_computed_amount(i) for i in resolved),
            Decimal('0.00'),
        )
        return str(total.quantize(Decimal('0.01')))

    def get_adjustment_service_detail(self, obj):
        if obj.adjustment_service_id is None:
            return None
        svc = obj.adjustment_service
        return {
            'name': svc.name,
            'rate': str(svc.rate),
            'algorithm': svc.algorithm,
        }

    def get_service_item_detail(self, obj):
        if obj.service_item_id is None:
            return None
        si = obj.service_item
        return {'template_id': si.template_id, 'name': si.template_name}


class EstimateSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
    line_items = EstimateLineItemSerializer(
        source='estimatelineitem_set', many=True, read_only=True
    )
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    is_amended = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = Estimate
        fields = [
            'estimate_id', 'job', 'job_number', 'job_name',
            'estimate_number', 'version', 'status', 'is_amended',
            'parent', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items', 'can_manage', 'total',
        ]
        read_only_fields = [
            'estimate_id', 'estimate_number', 'version',
            'created_date', 'sent_date', 'closed_date',
        ]

    def get_is_amended(self, obj):
        # Derived "amended" flag — see Estimate.is_amended() for the rule (the
        # single source of truth shared with the board pipeline payload).
        return obj.is_amended()

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job_id else None

    def get_job_name(self, obj):
        return obj.job.name if obj.job_id else ''

    def get_total(self, obj):
        # Authoritative document total: summed line qty*price, the same figure
        # the PDF (apps/estimates/pdf.py) and financials._estimated use. The
        # job-overview Scope block consumes this rather than recomputing on the
        # client (adjustment/percentage lines make client qty*price fragile).
        from decimal import Decimal
        total = sum(
            (li.qty * li.price for li in obj.estimatelineitem_set.all()),
            Decimal('0'),
        )
        return str(total.quantize(Decimal('0.01')))
