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
