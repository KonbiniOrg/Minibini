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
        'estimate_line_id': eli.pk,
        'co_line_id': None,
    }


def _line_dict_from_co_item(coli):
    """Build a line dict from a ChangeOrderLineItem (replace or add).

    Reads the CO line's own adjustment triple — same shape
    `_line_dict_from_estimate_item` emits. A CO line only ever carries
    adjustment fields on a replace-of-adjustment line (model-enforced,
    ChangeOrderLineItem.clean); add lines simply read as falsey.
    """
    amount = coli.qty * coli.price
    is_adjustment = coli.adjustment_service_id is not None
    return {
        'description': coli.description,
        'qty': coli.qty,
        'units': coli.units,
        'price': coli.price,
        'amount': amount,
        'accounting_category_id': coli.accounting_category_id,
        'origin': 'change_order',
        'is_adjustment': is_adjustment,
        'adjustment_service_id': coli.adjustment_service_id,
        'percent': (coli.adjustment_percent if is_adjustment else None),
        'target_category_ids': (
            list(coli.adjustment_target_categories.values_list('pk', flat=True))
            if is_adjustment else []
        ),
        'estimate_line_id': None,
        'co_line_id': coli.pk,
    }


def _fold(estimate, cos):
    """Fold `cos` (ChangeOrders, in application order) onto `estimate`'s line
    items. Shared by compose_agreement (accepted COs only) and
    compose_amended_agreement (a caller-selected baseline slice) — the single
    place the add/remove/replace walk lives, so the two callers can never
    diverge.

    Returns (keyed_lines, added_lines):
    - keyed_lines: OrderedDict keyed by EstimateLineItem pk, in line_number
      order, values are line dicts or None (removed).
    - added_lines: list of line dicts for ACTION_ADD lines, in the order
      encountered across `cos`.
    """
    est_line_items = list(
        estimate.estimatelineitem_set
        .select_related('adjustment_service')
        .prefetch_related('adjustment_target_categories')
        .order_by('line_number'))

    # Use an OrderedDict so insertion order (= line_number order) is preserved.
    keyed_lines = OrderedDict()
    for eli in est_line_items:
        keyed_lines[eli.pk] = _line_dict_from_estimate_item(eli)

    added_lines = []

    for co in cos:
        co_lines = (co.changeorderlineitem_set
                    .select_related('adjustment_service')
                    .prefetch_related('adjustment_target_categories')
                    .order_by('line_number'))
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

    return keyed_lines, added_lines


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

    # Process accepted COs in acceptance order: closed_date asc, pk asc (tie-break).
    accepted_cos = ChangeOrder.objects.filter(
        estimate=estimate,
        status=ChangeOrder.STATUS_ACCEPTED,
    ).order_by('closed_date', 'change_order_id')

    keyed_lines, added_lines = _fold(estimate, accepted_cos)

    # Compose final ordered list: surviving estimate-position lines first, then added lines.
    lines = [v for v in keyed_lines.values() if v is not None]
    lines.extend(added_lines)

    grand_total = sum((line['amount'] for line in lines), Decimal('0'))

    return {'lines': lines, 'grand_total': grand_total}


def adjustment_expected_amount(adj_line, amended_lines):
    """The amended-basis adjustment amount: percent/100 × Σ surviving amended
    non-adjustment line amounts, filtered by the target-category set (empty
    set = all). Mirrors apps.core.adjustments.compute_adjustment_amount but
    operates on the composed line-dict shape (post CO-application) rather
    than live model instances/siblings. Public: also the basis for
    ChangeOrderService.recompute_adjustment_replaces (Task 6) — the single
    place this math lives so the "amended agreement" hint and the CO line's
    stored price can never disagree."""
    percent = adj_line['percent'] or Decimal('0')
    target_ids = set(adj_line['target_category_ids'])
    total = Decimal('0.00')
    for line in amended_lines:
        if line is adj_line or line['is_adjustment']:
            continue
        if target_ids and line['accounting_category_id'] not in target_ids:
            continue
        total += line['amount']
    return (percent / Decimal('100') * total).quantize(Decimal('0.01'))


def _billed_on(line_dict):
    """The display_number of the live (non-cancelled) invoice referencing
    this agreement line, or None. Same liveness rule as
    ChangeOrderService._assert_target_not_billed."""
    from apps.invoicing.models import Invoice, InvoiceLineItem

    if line_dict['estimate_line_id'] is not None:
        ref_filter = {'agreement_estimate_line_id': line_dict['estimate_line_id']}
    else:
        ref_filter = {'agreement_co_line_id': line_dict['co_line_id']}

    ref = (InvoiceLineItem.objects
           .filter(**ref_filter)
           .exclude(invoice__status=Invoice.STATUS_CANCELLED)
           .select_related('invoice')
           .first())
    return ref.invoice.display_number if ref is not None else None


def compose_amended_agreement(co):
    """Server-composed "amended agreement": the baseline agreement (the
    estimate plus the accepted COs that precede `co`) with `co`'s own
    add/remove/replace lines applied on top. This is the CO edit view's
    one-table composition — computed server-side so the view, footer
    totals, and future seeding can never disagree.

    Baseline selection:
    - `co` accepted: only accepted COs whose acceptance order (closed_date
      asc, change_order_id asc) precedes `co` — so the record view of an
      already-accepted CO never double-applies its own deltas.
    - `co` draft/open/other: every accepted CO on the estimate.

    Returns {'rows': [...], 'original_total', 'co_delta', 'revised_total'}
    (Decimals). Row kinds:
    - {'kind': 'agreement', 'line': <dict>, 'billed_on': str|None,
       'adjustment_expected_amount': Decimal|None} — an untouched baseline
      line. adjustment_expected_amount is set only for adjustment lines,
      and only when it differs from the line's own stored amount (the
      "stale adjustment" hint) — computed against the FINAL amended
      non-adjustment rows, i.e. after `co`'s own edits.
    - {'kind': 'replaced', 'line': <dict from CO line>, 'original': <baseline
       dict>, 'co_line_id', 'co_index'}
    - {'kind': 'removed', 'original': <baseline dict>, 'co_line_id'} — the
      strike is the row; no own line.
    - {'kind': 'added', 'line': <dict from CO line>, 'co_line_id', 'co_index'}
    `co_index` numbers `co`'s own add+replace lines 1… in line_number order;
    removes get no index.
    """
    estimate = co.estimate

    all_accepted = list(ChangeOrder.objects.filter(
        estimate=estimate, status=ChangeOrder.STATUS_ACCEPTED,
    ).order_by('closed_date', 'change_order_id'))

    if co.status == ChangeOrder.STATUS_ACCEPTED:
        baseline_cos = []
        for c in all_accepted:
            if c.pk == co.pk:
                break
            baseline_cos.append(c)
    else:
        baseline_cos = all_accepted

    keyed_lines, baseline_added = _fold(estimate, baseline_cos)

    baseline_lines = [v for v in keyed_lines.values() if v is not None] + baseline_added
    original_total = sum((l['amount'] for l in baseline_lines), Decimal('0'))

    co_lines = list(
        co.changeorderlineitem_set
        .select_related('adjustment_service')
        .prefetch_related('adjustment_target_categories')
        .order_by('line_number'))

    touched = {}
    add_lines = []
    for coli in co_lines:
        if coli.action == ChangeOrderLineItem.ACTION_ADD:
            add_lines.append(coli)
        else:
            touched[coli.target_line_item_id] = coli

    index_map = {}
    counter = 0
    for coli in co_lines:
        if coli.action in (ChangeOrderLineItem.ACTION_ADD, ChangeOrderLineItem.ACTION_REPLACE):
            counter += 1
            index_map[coli.pk] = counter

    rows = []
    for target_pk, baseline_dict in keyed_lines.items():
        coli = touched.get(target_pk)
        if coli is None:
            if baseline_dict is None:
                continue  # removed by an earlier (baseline) accepted CO
            rows.append({'kind': 'agreement', 'line': baseline_dict})
        elif coli.action == ChangeOrderLineItem.ACTION_REMOVE:
            if baseline_dict is None:
                continue  # already gone from the baseline — nothing to strike
            rows.append({
                'kind': 'removed', 'original': baseline_dict, 'co_line_id': coli.pk,
            })
        elif coli.action == ChangeOrderLineItem.ACTION_REPLACE:
            if baseline_dict is None:
                continue  # target already removed upstream — mirrors _fold
            rows.append({
                'kind': 'replaced',
                'line': _line_dict_from_co_item(coli),
                'original': baseline_dict,
                'co_line_id': coli.pk,
                'co_index': index_map[coli.pk],
            })

    for coli in add_lines:
        rows.append({
            'kind': 'added',
            'line': _line_dict_from_co_item(coli),
            'co_line_id': coli.pk,
            'co_index': index_map[coli.pk],
        })

    amended_lines = [row['line'] for row in rows if row['kind'] != 'removed']
    revised_total = sum((l['amount'] for l in amended_lines), Decimal('0'))

    for row in rows:
        if row['kind'] != 'agreement':
            continue
        line = row['line']
        row['billed_on'] = _billed_on(line)
        if line['is_adjustment']:
            expected = adjustment_expected_amount(line, amended_lines)
            stored = line['amount'].quantize(Decimal('0.01'))
            row['adjustment_expected_amount'] = None if expected == stored else expected
        else:
            row['adjustment_expected_amount'] = None

    return {
        'rows': rows,
        'original_total': original_total,
        'co_delta': revised_total - original_total,
        'revised_total': revised_total,
    }


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
