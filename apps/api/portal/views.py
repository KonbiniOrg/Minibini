"""Token-authorized, login-not-required customer portal API for Estimates.

Named 'portal', not 'public' — these documents aren't public, they just
don't require a Minibini login to view. Every endpoint authorizes by the
estimate's opaque public_token.
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.estimates.models import Estimate
from apps.estimates.services import EstimateEmailService, EstimateService


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


def _not_available():
    return Response({'detail': 'Not available.'},
                    status=status.HTTP_404_NOT_FOUND)


def _actor_for(estimate, reason=None):
    contact = estimate.job.contact if estimate.job_id else None
    return {
        'contact_id': contact.pk if contact else None,
        'email': (contact.email if contact else '') or '',
        'reason': reason,
    }


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate(request, token):
    estimate = Estimate.objects.filter(public_token=token).first()
    if estimate is None or estimate.status == Estimate.STATUS_DRAFT:
        return _not_available()
    return Response(build_estimate_payload(estimate))


def _decide(token, target_status, decision_word, reason=None):
    with transaction.atomic():
        estimate = (Estimate.objects
                    .select_for_update()
                    .filter(public_token=token)
                    .first())
        if estimate is None or estimate.status == Estimate.STATUS_DRAFT:
            return _not_available()
        # Only act from 'open'; a click racing the shop is a no-op.
        if estimate.status == Estimate.STATUS_OPEN:
            EstimateService.update_status(
                estimate.pk, target_status,
                actor=_actor_for(estimate, reason))
            acted = True
        else:
            acted = False
        estimate.refresh_from_db()
    if acted:
        EstimateEmailService.notify_shop_of_decision(
            estimate, decision_word, reason=reason or '')
    return Response(build_estimate_payload(estimate))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate_accept(request, token):
    return _decide(token, Estimate.STATUS_ACCEPTED, 'accepted')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate_reject(request, token):
    reason = (request.data.get('reason') or '').strip()
    return _decide(token, Estimate.STATUS_REJECTED, 'declined', reason=reason)
