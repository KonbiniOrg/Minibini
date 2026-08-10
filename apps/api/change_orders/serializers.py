from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.api.estimates.serializers import (
    EstimateLineItemSourceSerializer, _resolve_sources, derive_estimate_backing,
)
from apps.api.mixins import JobScopedCanManageMixin
from apps.core.units import UnitsField
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, EstimateLineItem
from apps.estimates.services import EstimateWizardService


class ChangeOrderLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    service_item_detail = serializers.SerializerMethodField()

    class Meta:
        model = ChangeOrderLineItem
        fields = [
            'line_item_id', 'line_number',
            'action', 'target_line_item',
            'description', 'qty', 'units', 'price',
            'accounting_category',
            'inventory_item', 'service_item', 'service_item_detail', 'is_material',
            'adjustment_service', 'adjustment_percent', 'adjustment_target_categories',
        ]
        read_only_fields = [
            'line_item_id', 'service_item_detail',
            # Writes go through the service (Task 6) — this serializer only
            # ever displays the CO line's adjustment triple.
            'adjustment_service', 'adjustment_percent', 'adjustment_target_categories',
        ]

    def get_service_item_detail(self, obj):
        if obj.service_item_id is None:
            return None
        return {
            'template_id': obj.service_item.template_id,
            'name': obj.service_item.template_name,
        }


# ---------------------------------------------------------------------------
# Amended-agreement composition: backing/sources display extras.
#
# compose_amended_agreement (apps/estimates/agreement.py) computes rows and
# their totals server-side; this module adds the per-row display extras the
# CO edit view needs (backing classification + resolvable claim rows) —
# these need DRF serialization, so they live in the API layer rather than
# the service layer.
# ---------------------------------------------------------------------------

def _resolve_rows(rows):
    """Resolve a list of raw source rows (Estimate/ChangeOrderLineItemSource),
    skipping any dangling row (its atom already deleted) rather than raising."""
    resolved = []
    for src in rows:
        try:
            resolved.append(src.resolve())
        except ObjectDoesNotExist:
            continue
    return resolved


def _sum_amounts(resolved):
    """Sum EstimateWizardService._atom_computed_amount over already-resolved
    atom instances (Task/Material), quantized to cents."""
    return sum(
        (EstimateWizardService._atom_computed_amount(i) for i in resolved),
        Decimal('0.00'),
    )


def _backing_total(line):
    """Sum of a line's own resolvable source amounts, or None when it has
    none. Generalizes EstimateLineItemSerializer.get_backing_total to any
    object with a `.sources` related manager (Estimate or ChangeOrder line)."""
    resolved = _resolve_sources(line)
    if not resolved:
        return None
    return str(_sum_amounts(resolved).quantize(Decimal('0.01')))


def _sources_for_replace(co_line):
    """Resolvable claim rows backing a replace CO line: the line's own
    sources if already crystallized (accepted CO — claims moved off the
    target at acceptance, ChangeOrderAcceptanceService._move_claims_to),
    else the target's own sources (draft/open CO — not yet moved). Either
    way these are the claims originally authored on the target line."""
    if co_line.sources.exists():
        return list(co_line.sources.all())
    target = co_line.target_line_item
    if target is None:
        return []
    return list(target.sources.all())


def derive_co_line_backing(co_line, resolved_sources=None):
    """Backing classification for a replace CO line: same enum as
    derive_estimate_backing, but summed off the resolvable sources backing
    the target — the line's OWN sources when the CO is already accepted
    (claims moved off the target at acceptance) else the TARGET's sources
    (draft/open CO, not yet moved) — see `_sources_for_replace` — against
    the CO line's own qty/price (in-sync -> planned_work / planned_materials;
    out-of-sync -> 'edited'). A replace line can never carry a catalog
    descriptor (model-enforced), so the classification reduces to
    adjustment / sourced / hand.

    `resolved_sources`: optional pre-resolved atom list (from
    `_resolve_rows(_sources_for_replace(co_line))`) — pass this when the
    caller already resolved sources for the same co_line (e.g. per-row
    endpoint serialization, which also needs them for backing_total/sources)
    to avoid a duplicate query round-trip. Computed fresh when omitted."""
    if co_line.adjustment_service_id is not None:
        return 'adjustment'

    if resolved_sources is None:
        resolved_sources = _resolve_rows(_sources_for_replace(co_line))

    if resolved_sources:
        sum_value = _sum_amounts(resolved_sources)
        if not EstimateWizardService._is_in_sync(co_line, sum_value):
            return 'edited'
        from apps.jobs.models import Task
        if any(isinstance(i, Task) for i in resolved_sources):
            return 'planned_work'
        return 'planned_materials'

    return 'hand'


def _replace_backing_total(resolved_sources):
    """backing_total for a replace row from an already-resolved source list
    (see derive_co_line_backing's resolved_sources param) — never re-queries."""
    if not resolved_sources:
        return None
    return str(_sum_amounts(resolved_sources).quantize(Decimal('0.01')))


def _serialize_sources(rows, *, inherited_from_line=None):
    data = list(EstimateLineItemSourceSerializer(rows, many=True).data)
    if inherited_from_line is not None:
        for d in data:
            d['inherited_from_line'] = inherited_from_line
    return data


def _serialize_line_dict(d):
    """Stringify the Decimal fields of a compose_agreement/compose_amended_
    agreement line dict for JSON; leave ids/lists/bools alone."""
    if d is None:
        return None
    out = dict(d)
    for k in ('qty', 'price', 'amount', 'percent'):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out


def _serialize_amended_row(row, co_lines_by_id, estimate_lines_by_id):
    """`co_lines_by_id`/`estimate_lines_by_id`: pk -> instance maps, batch-
    fetched once by `serialize_amended_agreement` for every row (never a
    per-row `.get()` — see that function)."""
    kind = row['kind']

    if kind == 'agreement':
        line = row['line']
        out = {
            'kind': 'agreement',
            'line': _serialize_line_dict(line),
            'billed_on': row['billed_on'],
            'adjustment_expected_amount': (
                None if row['adjustment_expected_amount'] is None
                else str(row['adjustment_expected_amount'])
            ),
        }
        if line['estimate_line_id'] is not None:
            eli = estimate_lines_by_id[line['estimate_line_id']]
            out['backing'] = derive_estimate_backing(eli)
            out['backing_total'] = _backing_total(eli)
        else:
            # CO-origin baseline line (an earlier accepted CO's add/replace) —
            # rare under single-CO; no estimate line to derive backing from.
            out['backing'] = None
            out['backing_total'] = None
        return out

    if kind == 'removed':
        return {
            'kind': 'removed',
            'original': _serialize_line_dict(row['original']),
            'co_line_id': row['co_line_id'],
        }

    if kind == 'replaced':
        co_line = co_lines_by_id[row['co_line_id']]
        target = co_line.target_line_item
        # Resolve sources ONCE per row and thread the same list into backing,
        # backing_total, and the sources block — _sources_for_replace does its
        # own query (own-sources-first, else target's), so calling it more
        # than once per row would triple the round trips.
        raw_sources = _sources_for_replace(co_line)
        resolved_sources = _resolve_rows(raw_sources)
        return {
            'kind': 'replaced',
            'line': _serialize_line_dict(row['line']),
            'original': _serialize_line_dict(row['original']),
            'co_line_id': row['co_line_id'],
            'co_index': row['co_index'],
            'backing': derive_co_line_backing(co_line, resolved_sources),
            'backing_total': _replace_backing_total(resolved_sources),
            'sources': _serialize_sources(
                raw_sources,
                inherited_from_line=(target.line_number if target else None),
            ),
        }

    if kind == 'added':
        co_line = co_lines_by_id[row['co_line_id']]
        return {
            'kind': 'added',
            'line': _serialize_line_dict(row['line']),
            'co_line_id': row['co_line_id'],
            'co_index': row['co_index'],
            'backing': derive_estimate_backing(co_line),
            'backing_total': _backing_total(co_line),
            'sources': _serialize_sources(list(co_line.sources.all())),
        }

    raise ValueError(f'Unknown amended-agreement row kind: {kind}')


def serialize_amended_agreement(result):
    """JSON-safe payload for GET .../amended-agreement/ from
    compose_amended_agreement(co)'s result dict.

    Batch-fetches every ChangeOrderLineItem/EstimateLineItem the rows
    reference (`in_bulk`, one query each) instead of a `.get()` per row."""
    rows = result['rows']

    co_line_ids = [
        r['co_line_id'] for r in rows if r['kind'] in ('replaced', 'added')
    ]
    estimate_line_ids = [
        r['line']['estimate_line_id'] for r in rows
        if r['kind'] == 'agreement' and r['line']['estimate_line_id'] is not None
    ]

    co_lines_by_id = (
        ChangeOrderLineItem.objects
        .select_related('target_line_item')
        .in_bulk(co_line_ids)
    )
    estimate_lines_by_id = EstimateLineItem.objects.in_bulk(estimate_line_ids)

    return {
        'rows': [
            _serialize_amended_row(r, co_lines_by_id, estimate_lines_by_id)
            for r in rows
        ],
        'original_total': str(result['original_total'].quantize(Decimal('0.01'))),
        'co_delta': str(result['co_delta'].quantize(Decimal('0.01'))),
        'revised_total': str(result['revised_total'].quantize(Decimal('0.01'))),
    }


class ChangeOrderSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'

    line_items = ChangeOrderLineItemSerializer(
        source='changeorderlineitem_set', many=True, read_only=True
    )
    total = serializers.SerializerMethodField()

    class Meta:
        model = ChangeOrder
        fields = [
            'change_order_id', 'job', 'estimate',
            'change_order_number', 'version', 'parent',
            'status', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items', 'can_manage', 'total',
        ]
        read_only_fields = [
            'change_order_id', 'change_order_number', 'version',
            'estimate', 'created_date', 'sent_date', 'closed_date',
        ]

    def get_total(self, obj):
        # Authoritative CO delta: proposed − prior against the base estimate,
        # from compose_change_order_diff (the same figure the CO PDF and
        # portal diff use). NOT qty*price of the CO's own add/remove/replace
        # lines — a remove subtracts, a replace swaps. The job-overview Scope
        # block adds this delta onto the frozen estimate total.
        from decimal import Decimal
        from apps.estimates.agreement import compose_change_order_diff
        diff = compose_change_order_diff(obj)
        return str(diff['diff_total'].quantize(Decimal('0.01')))
