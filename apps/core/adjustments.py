"""Helpers for percentage-adjustment line items (rush surcharges, discounts, etc.)."""
from decimal import Decimal


def recompute_adjustments(line_items):
    """Recompute every percentage-adjustment line's price from its current
    siblings. `line_items` = all line items on ONE document (iterable/queryset).
    Saves each adjustment line whose price changed. Returns count updated."""
    lines = list(line_items)
    updated = 0
    for adj in lines:
        if not getattr(adj, 'adjustment_service_id', None):
            continue
        siblings = [li for li in lines if li.pk != adj.pk]
        new_price = compute_adjustment_amount(adj, siblings)
        if adj.price != new_price:
            adj.price = new_price
            adj.save()
            updated += 1
    return updated


def compute_adjustment_amount(adjustment_line, sibling_lines):
    """Return the dollar amount for a percentage-adjustment line item.

    amount = (service.rate / 100) * sum(total_amount of non-adjustment siblings
    whose accounting_category is in the target-category set; empty target set
    means ALL non-adjustment siblings).

    Result is quantized to the nearest cent (Decimal('0.01')).

    Args:
        adjustment_line: an EstimateLineItem (or InvoiceLineItem) whose
            ``adjustment_service`` is set to a PERCENTAGE ServiceItem.
        sibling_lines: iterable of line items on the same parent document,
            excluding ``adjustment_line`` itself.

    Returns:
        Decimal quantized to two decimal places.
    """
    svc = adjustment_line.adjustment_service
    percent = svc.rate
    target_ids = set(
        adjustment_line.adjustment_target_categories.values_list('pk', flat=True)
    )
    total = Decimal('0.00')
    for line in sibling_lines:
        # Skip other adjustment lines — no stacking on adjustments
        if getattr(line, 'adjustment_service_id', None):
            continue
        # If a target set is specified, skip lines not in that set
        if target_ids and line.accounting_category_id not in target_ids:
            continue
        total += line.total_amount  # BaseLineItem.total_amount == qty * price
    return (percent / Decimal('100') * total).quantize(Decimal('0.01'))
