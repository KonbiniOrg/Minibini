"""Token-authorized, login-not-required customer portal API for Estimates.

Named 'portal', not 'public' — these documents aren't public, they just
don't require a Minibini login to view. Every endpoint authorizes by the
estimate's opaque public_token.
"""
from decimal import Decimal

from apps.estimates.models import Estimate


def _money(value):
    return str((value or Decimal('0')).quantize(Decimal('0.01')))


def _line_amount(li):
    return (li.qty or Decimal('0')) * (li.price or Decimal('0'))


def _current_token(estimate):
    """The live head of the revision lineage for a superseded estimate:
    highest-version row with the same estimate_number that isn't superseded.
    """
    head = (Estimate.objects
            .filter(estimate_number=estimate.estimate_number)
            .exclude(status=Estimate.STATUS_SUPERSEDED)
            .order_by('-version')
            .first())
    return head.public_token if head else None


def build_estimate_payload(estimate):
    """Customer-safe dict for an estimate. Exposes only what a customer
    needs to decide — never the internal serializer's fields."""
    actions = (['accept', 'reject']
               if estimate.status == Estimate.STATUS_OPEN else [])

    line_items = []
    total = Decimal('0')
    for li in estimate.estimatelineitem_set.all().order_by('line_number'):
        amount = _line_amount(li)
        total += amount
        line_items.append({
            'description': li.description,
            'qty': str(li.qty) if li.qty is not None else None,
            'units': li.units,
            'price': _money(li.price),
            'amount': _money(amount),
        })

    deliverables = [
        {
            'description': d.description,
            'qty_ordered': str(d.qty_ordered),
            'units': d.units,
        }
        for d in estimate.job.deliverables.all()  # Meta ordering = sort_order
    ] if estimate.job_id else []

    payload = {
        'estimate_number': estimate.estimate_number,
        'status': estimate.status,
        'sent_date': estimate.sent_date,
        'expiration_date': estimate.expiration_date,
        'closed_date': estimate.closed_date,
        'deliverables': deliverables,
        'line_items': line_items,
        'grand_total': _money(total),
        'actions': actions,
    }
    if estimate.status == Estimate.STATUS_SUPERSEDED:
        payload['current_token'] = _current_token(estimate)
    return payload
