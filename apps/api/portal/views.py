"""Token-authorized, login-not-required customer portal API for Estimates.

Named 'portal', not 'public' — these documents aren't public, they just
don't require a Minibini login to view. Every endpoint authorizes by the
estimate's opaque public_token.
"""
from decimal import Decimal

from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.api.portal.common import (
    actor_for, decide, money, not_available, visible_document,
)
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateEmailService, EstimateService
from apps.jobs.models import Job


# Shown when an estimate is still `open` but its job has moved on (the shop
# cancelled/rejected/advanced/reopened it) — the customer can no longer respond.
CLOSED_MESSAGE = (
    'This estimate is not open for response.  Please contact us for further '
    'information.'
)


def _is_actionable(estimate):
    """Customer may act only on an OPEN estimate whose job is still awaiting the
    customer (SUBMITTED). The shop can move the job independently (cancel,
    reject, reopen) without touching the estimate; the portal respects job
    status but never mutates the estimate from the job side. (Direct manual
    approval is blocked once a job has estimates — approval flows from
    estimate acceptance; see JobService.update_job.)"""
    if estimate.status != Estimate.STATUS_OPEN:
        return False
    return estimate.job_id is not None and estimate.job.status == Job.STATUS_SUBMITTED


def _line_amount(li):
    return (li.qty or Decimal('0')) * (li.price or Decimal('0'))


def _current_token(estimate):
    """Token of the latest *non-draft* version for the job, for a superseded
    estimate to link forward to. Drafts are excluded — they aren't viewable in
    the portal, so we never send the customer to an unsent revision. Returns
    None when the latest non-draft is this estimate itself (e.g. the only newer
    version is an unsent draft), so no dead link is shown.
    """
    head = (Estimate.objects
            .filter(job_id=estimate.job_id)
            .exclude(status=Estimate.STATUS_DRAFT)
            .order_by('-version', '-pk')
            .first())
    return head.public_token if head and head.pk != estimate.pk else None


def build_estimate_payload(estimate):
    """Customer-safe dict for an estimate. Exposes only what a customer
    needs to decide — never the internal serializer's fields."""
    actionable = _is_actionable(estimate)
    actions = ['accept', 'request_changes', 'reject'] if actionable else []
    # An open estimate on a job that has moved on: read-only, with a message.
    closed_message = (CLOSED_MESSAGE
                      if estimate.status == Estimate.STATUS_OPEN and not actionable
                      else None)

    line_items = []
    total = Decimal('0')
    for li in estimate.estimatelineitem_set.all().order_by('line_number'):
        amount = _line_amount(li)
        total += amount
        line_items.append({
            'description': li.description,
            'qty': str(li.qty) if li.qty is not None else None,
            'units': li.units,
            'price': money(li.price),
            'amount': money(amount),
        })

    # An out-of-date estimate (superseded, or accepted-then-amended by a change
    # order) carries a frozen DeliverableSnapshot set recording the scope the
    # customer saw. Render that. A current estimate (draft/open) has no snapshot,
    # so it falls back to the job's live deliverables.
    snapshots = list(estimate.deliverable_snapshots.all())  # Meta ordering = sort_order
    if snapshots:
        deliverables = [
            {
                'description': s.description,
                'qty_ordered': str(s.qty_ordered),
                'units': s.units,
            }
            for s in snapshots
        ]
    else:
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
        'grand_total': money(total),
        'actions': actions,
        'actionable': actionable,
        'closed_message': closed_message,
    }
    if estimate.status == Estimate.STATUS_SUPERSEDED:
        payload['current_token'] = _current_token(estimate)
    return payload


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate(request, token):
    estimate = visible_document(Estimate, token)
    if estimate is None:
        return not_available()
    return Response(build_estimate_payload(estimate))


def _decide(token, target_status, decision_word, reason=None):
    # Act only when actionable (open estimate + submitted job) — the shared
    # skeleton no-ops a click racing the shop.
    def act(estimate):
        EstimateService.update_status(
            estimate.pk, target_status,
            actor=actor_for(estimate, reason))

    return decide(
        Estimate, token,
        is_actionable=_is_actionable,
        act=act,
        notify=lambda estimate: EstimateEmailService.notify_shop_of_decision(
            estimate, decision_word, reason=reason or ''),
        build_payload=build_estimate_payload,
    )


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


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate_request_changes(request, token):
    """Customer asks for changes: auto-revise the estimate and send the job back
    to draft. Only acts from 'open' — a click racing the shop is a no-op."""
    reason = (request.data.get('reason') or '').strip()

    def act(estimate):
        EstimateService.request_changes(
            estimate.pk, actor_for(estimate, reason))

    return decide(
        Estimate, token,
        is_actionable=_is_actionable,
        act=act,
        notify=lambda estimate: EstimateEmailService.notify_shop_of_decision(
            estimate, 'requested changes', reason=reason or ''),
        build_payload=build_estimate_payload,
    )
