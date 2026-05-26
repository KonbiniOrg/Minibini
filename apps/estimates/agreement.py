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

from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate


def _line_dict_from_estimate_item(eli):
    """Build a line dict from an EstimateLineItem."""
    amount = eli.qty * eli.price
    return {
        'description': eli.description,
        'qty': eli.qty,
        'units': eli.units,
        'price': eli.price,
        'amount': amount,
        'origin': 'estimate',
    }


def _line_dict_from_co_item(coli):
    """Build a line dict from a ChangeOrderLineItem (replace or add)."""
    amount = coli.qty * coli.price
    return {
        'description': coli.description,
        'qty': coli.qty,
        'units': coli.units,
        'price': coli.price,
        'amount': amount,
        'origin': 'change_order',
    }


def compose_agreement(job):
    """Return the effective agreement = the job's accepted estimate's line items
    with each accepted ChangeOrder's deltas applied, in acceptance order.

    Returns {'lines': [ {description, qty, units, price, amount, origin}, ... ],
             'grand_total': Decimal}, where origin is 'estimate' or 'change_order'.
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
    est_line_items = estimate.estimatelineitem_set.order_by('line_number')
    # Use an OrderedDict so insertion order (= line_number order) is preserved.
    keyed_lines = OrderedDict()
    for eli in est_line_items:
        keyed_lines[eli.pk] = _line_dict_from_estimate_item(eli)

    # Added lines come after all estimate lines.
    added_lines = []

    # Process accepted COs in acceptance order: closed_date asc, pk asc (tie-break).
    accepted_cos = ChangeOrder.objects.filter(
        estimate=estimate,
        status=ChangeOrder.STATUS_ACCEPTED,
    ).order_by('closed_date', 'change_order_id')

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
                    keyed_lines[target_pk] = _line_dict_from_co_item(coli)

            elif action == ChangeOrderLineItem.ACTION_ADD:
                added_lines.append(_line_dict_from_co_item(coli))

    # Compose final ordered list: surviving estimate-position lines first, then added lines.
    lines = [v for v in keyed_lines.values() if v is not None]
    lines.extend(added_lines)

    grand_total = sum((line['amount'] for line in lines), Decimal('0'))

    return {'lines': lines, 'grand_total': grand_total}
