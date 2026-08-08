"""
Agreement-of-record composition.

compose_agreement(job) returns the effective billing lines for a job: the
accepted estimate's EstimateLineItems with each accepted ChangeOrder's
add/remove/replace deltas applied in acceptance order (closed_date asc,
then change_order_id asc as tie-break), plus the grand total.

Amount convention: qty * price, matching BaseLineItem.total_amount.
"""
from collections import OrderedDict
from decimal import Decimal

from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItemSource,
)


def _line_dict_from_estimate_item(eli, source_fee_id=None):
    """Build a line dict from an EstimateLineItem.

    source_fee_id: the Fee pk crystallized from this hand-line at acceptance time
    (None for atom-backed lines and adjustment lines).  Populated by
    compose_agreement via a bulk prefetch to avoid N+1 queries.
    """
    amount = eli.qty * eli.price
    is_adjustment = eli.adjustment_service_id is not None
    return {
        'description': eli.description,
        'qty': eli.qty,
        'units': eli.units,
        'price': eli.price,
        'amount': amount,
        'accounting_category_id': eli.accounting_category_id,
        'origin': 'estimate',
        'is_adjustment': is_adjustment,
        'adjustment_service_id': eli.adjustment_service_id,
        # Line's own snapshot, never the live scheme (adjustment_service is
        # provenance only — see EstimateLineItem.adjustment_service).
        'percent': (eli.adjustment_percent if is_adjustment else None),
        'target_category_ids': (
            list(eli.adjustment_target_categories.values_list('pk', flat=True))
            if is_adjustment else []
        ),
        'source_fee_id': source_fee_id,
        'estimate_line_id': eli.pk,
        'co_line_id': None,
    }


def _line_dict_from_co_item(coli, source_fee_id=None):
    """Build a line dict from a ChangeOrderLineItem (replace or add).

    CO-origin lines are never adjustment lines — adjustments are estimate-only
    for now.  Keep is_adjustment falsey so agreement-adjustments filtering skips
    them.

    source_fee_id: the Fee pk crystallized from this CO line at CO acceptance
    (None for lines that crystallized a Task/Material or nothing). Populated by
    compose_agreement via a bulk prefetch, exactly parallel to the estimate
    hand-line fee provenance, so copy_from_estimate claims the Fee once.
    """
    amount = coli.qty * coli.price
    return {
        'description': coli.description,
        'qty': coli.qty,
        'units': coli.units,
        'price': coli.price,
        'amount': amount,
        'accounting_category_id': coli.accounting_category_id,
        'origin': 'change_order',
        'is_adjustment': False,
        'adjustment_service_id': None,
        'percent': None,
        'target_category_ids': [],
        'source_fee_id': source_fee_id,
        'estimate_line_id': None,
        'co_line_id': coli.pk,
    }


def compose_agreement(job):
    """Return the effective agreement = the job's accepted estimate's line items
    with each accepted ChangeOrder's deltas applied, in acceptance order.

    Returns {'lines': [ {description, qty, units, price, amount, origin,
                         estimate_line_id, co_line_id, ...}, ... ],
             'grand_total': Decimal}, where origin is 'estimate' or 'change_order'.
    Each line carries exactly one non-null identity: estimate_line_id (int)
    for estimate-origin lines, co_line_id (int) for CO-origin lines (add/replace).
    Returns {'lines': [], 'grand_total': Decimal('0')} if the job has no accepted estimate.
    """
    empty = {'lines': [], 'grand_total': Decimal('0')}

    estimate = Estimate.objects.filter(
        job=job,
        status=Estimate.STATUS_ACCEPTED,
    ).first()

    if estimate is None:
        return empty

    # Build an ordered dict keyed by EstimateLineItem pk preserving line_number order.
    # Values are mutable line dicts (or None when removed).
    est_line_items = list(
        estimate.estimatelineitem_set
        .select_related('adjustment_service')
        .prefetch_related('adjustment_target_categories')
        .order_by('line_number'))

    # Prefetch the fee-source mapping in a single query to avoid N+1.
    # Each hand-line that was crystallized into a Fee has exactly one
    # EstimateLineItemSource(source_type='fee') row created at acceptance time.
    fee_source_map = {
        src.estimate_line_item_id: src.source_pk
        for src in EstimateLineItemSource.objects.filter(
            estimate_line_item__in=[eli.pk for eli in est_line_items],
            source_type=EstimateLineItemSource.SOURCE_FEE,
        )
    }

    # Use an OrderedDict so insertion order (= line_number order) is preserved.
    keyed_lines = OrderedDict()
    for eli in est_line_items:
        keyed_lines[eli.pk] = _line_dict_from_estimate_item(
            eli, source_fee_id=fee_source_map.get(eli.pk),
        )

    # Added lines come after all estimate lines.
    added_lines = []

    # Process accepted COs in acceptance order: closed_date asc, pk asc (tie-break).
    accepted_cos = ChangeOrder.objects.filter(
        estimate=estimate,
        status=ChangeOrder.STATUS_ACCEPTED,
    ).order_by('closed_date', 'change_order_id')

    # Prefetch the CO-line fee provenance in a single query (parallel to the
    # estimate fee_source_map above): each add/replace line crystallized into
    # a Fee at CO acceptance has one ChangeOrderLineItemSource(fee) row.
    co_fee_source_map = {
        src.change_order_line_item_id: src.source_pk
        for src in ChangeOrderLineItemSource.objects.filter(
            change_order_line_item__change_order__in=accepted_cos,
            source_type=ChangeOrderLineItemSource.SOURCE_FEE,
        )
    }

    for co in accepted_cos:
        co_lines = co.changeorderlineitem_set.order_by('line_number')
        for coli in co_lines:
            action = coli.action

            if action == ChangeOrderLineItem.ACTION_REMOVE:
                target_pk = coli.target_line_item_id
                if target_pk in keyed_lines:
                    # Mark as removed (None keeps the slot, we filter it out at end)
                    keyed_lines[target_pk] = None

            elif action == ChangeOrderLineItem.ACTION_REPLACE:
                target_pk = coli.target_line_item_id
                if target_pk in keyed_lines and keyed_lines[target_pk] is not None:
                    keyed_lines[target_pk] = _line_dict_from_co_item(
                        coli, source_fee_id=co_fee_source_map.get(coli.pk))

            elif action == ChangeOrderLineItem.ACTION_ADD:
                added_lines.append(_line_dict_from_co_item(
                    coli, source_fee_id=co_fee_source_map.get(coli.pk)))

    # Compose final ordered list: surviving estimate-position lines first, then added lines.
    lines = [v for v in keyed_lines.values() if v is not None]
    lines.extend(added_lines)

    grand_total = sum((line['amount'] for line in lines), Decimal('0'))

    return {'lines': lines, 'grand_total': grand_total}


def _amount(qty, price):
    return (qty or Decimal('0')) * (price or Decimal('0'))


def _diff_row(kind, line_number, src):
    """Build a merged-diff display row from an Estimate/CO line item."""
    return {
        'kind': kind,
        'line_number': line_number,
        'description': src.description,
        'qty': src.qty,
        'units': src.units,
        'price': src.price,
        'amount': _amount(src.qty, src.price),
    }


def compose_change_order_diff(co):
    """Customer/portal-facing line-item diff of a ChangeOrder.

    Diffs the CO's add/remove/replace deltas against the line items of the
    estimate the CO amends (``co.estimate`` — always the accepted estimate, set
    by ChangeOrderService.create). Mirrors the shop CO-detail page's merged-rows
    logic so shop and customer see the same diff.

    Returns ``{'line_rows': [...], 'prior_total', 'proposed_total',
    'diff_total'}`` where each row is
    ``{kind, line_number, description, qty, units, price, amount}`` and
    ``kind ∈ {unchanged, changed, changed-orig, removed, added}``:

    - ``changed``      — the CO 'replace' value (new), shown above…
    - ``changed-orig`` — …the struck original estimate line
    - ``removed``      — an estimate line struck by a CO 'remove'
    - ``added``        — a CO 'add' line, appended after all estimate lines
    - ``unchanged``    — an estimate line no CO line touches

    ``prior_total`` sums the estimate baseline; ``proposed_total`` sums the
    surviving + changed + added rows; ``diff_total`` = proposed − prior.

    Note (faithful to the shop page): the line-item baseline is the flat
    accepted estimate, NOT compose_agreement. With multiple accepted COs this
    can understate the true current agreement — single-CO is the validated path.
    """
    est_lines = list(
        co.estimate.estimatelineitem_set.order_by('line_number'))
    co_lines = list(co.changeorderlineitem_set.order_by('line_number'))

    replace_by_target = {}
    remove_by_target = {}
    add_lines = []
    for cli in co_lines:
        if cli.action == ChangeOrderLineItem.ACTION_REPLACE and cli.target_line_item_id:
            replace_by_target[cli.target_line_item_id] = cli
        elif cli.action == ChangeOrderLineItem.ACTION_REMOVE and cli.target_line_item_id:
            remove_by_target[cli.target_line_item_id] = cli
        elif cli.action == ChangeOrderLineItem.ACTION_ADD:
            add_lines.append(cli)

    rows = []
    prior_total = Decimal('0')
    proposed_total = Decimal('0')

    for eli in est_lines:
        prior_total += _amount(eli.qty, eli.price)
        replace_cli = replace_by_target.get(eli.line_item_id)
        remove_cli = remove_by_target.get(eli.line_item_id)
        if replace_cli is not None:
            changed = _diff_row('changed', eli.line_number, replace_cli)
            rows.append(changed)
            rows.append(_diff_row('changed-orig', eli.line_number, eli))
            proposed_total += changed['amount']
        elif remove_cli is not None:
            rows.append(_diff_row('removed', eli.line_number, eli))
            # removed: contributes nothing to proposed
        else:
            unchanged = _diff_row('unchanged', eli.line_number, eli)
            rows.append(unchanged)
            proposed_total += unchanged['amount']

    for cli in sorted(add_lines, key=lambda c: (c.line_number or 0)):
        added = _diff_row('added', cli.line_number, cli)
        rows.append(added)
        proposed_total += added['amount']

    return {
        'line_rows': rows,
        'prior_total': prior_total,
        'proposed_total': proposed_total,
        'diff_total': proposed_total - prior_total,
    }
