"""Token-authorized, login-not-required customer portal API for ChangeOrders.

The CO sibling of ``views.py`` (the estimate portal). Every endpoint authorizes
by the change order's opaque ``public_token``; a CO is presented as a
before/after diff (it amends an accepted agreement) rather than a flat document.
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.deliverables.models import DeliverableSnapshot
from apps.estimates.agreement import compose_change_order_diff
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder
from apps.estimates.services import ChangeOrderEmailService
from apps.jobs.models import Job

# Shown when a CO is still `open` but its job has moved off on_hold out from
# under it — the customer can no longer respond.
CLOSED_MESSAGE = (
    'This change order is not open for response.  Please contact us for '
    'further information.'
)


def _is_actionable(co):
    """Customer may act only on an OPEN CO whose job is still awaiting them.
    An open CO is authored and sent while the job is on_hold and stays on_hold
    until the customer accepts (then it goes approved); so "awaiting customer"
    maps to job on_hold. Gate on both so a shop action that races the click
    no-ops."""
    if co.status != ChangeOrder.STATUS_OPEN:
        return False
    return co.job_id is not None and co.job.status == Job.STATUS_ON_HOLD


def _money(value):
    return str((value or Decimal('0')).quantize(Decimal('0.01')))


def _current_token(co):
    """Token of the latest non-draft CO for the job, for a superseded CO to link
    forward to. Drafts are excluded (not portal-viewable). Returns None when the
    latest non-draft is this CO itself (the only newer revision is an unsent
    draft), so no dead link is shown."""
    head = (ChangeOrder.objects
            .filter(job_id=co.job_id)
            .exclude(status=ChangeOrder.STATUS_DRAFT)
            .order_by('-change_order_id')
            .first())
    return head.public_token if head and head.pk != co.pk else None


def _deliverable_diff(co):
    """Merged baseline-vs-live deliverable diff, mirroring the shop page's
    delivMergedRows. Baseline = DeliverableSnapshot rows of the document this CO
    amends (latest accepted CO before it, else the estimate); live = the job's
    current deliverables. Rows: {kind, description, qty, units}."""
    baseline_doc = ChangeOrderService.baseline_document(co=co)
    if isinstance(baseline_doc, ChangeOrder):
        base = list(DeliverableSnapshot.objects.filter(
            change_order=baseline_doc).order_by('sort_order'))
    else:
        base = list(DeliverableSnapshot.objects.filter(
            estimate=baseline_doc).order_by('sort_order'))
    live = list(co.job.deliverables.all()) if co.job_id else []  # Meta order = sort_order

    live_by_id = {d.pk: d for d in live}
    baselined_live_ids = {s.source_deliverable_id for s in base
                          if s.source_deliverable_id}

    rows = []
    for snap in base:
        live_row = (live_by_id.get(snap.source_deliverable_id)
                    if snap.source_deliverable_id else None)
        if live_row is None:
            rows.append({'kind': 'removed', 'description': snap.description,
                         'qty': str(snap.qty_ordered), 'units': snap.units})
            continue
        changed = (live_row.description != snap.description
                   or live_row.qty_ordered != snap.qty_ordered
                   or live_row.units != snap.units)
        if changed:
            rows.append({'kind': 'changed', 'description': live_row.description,
                         'qty': str(live_row.qty_ordered), 'units': live_row.units})
            rows.append({'kind': 'changed-orig', 'description': snap.description,
                         'qty': str(snap.qty_ordered), 'units': snap.units})
        else:
            rows.append({'kind': 'unchanged', 'description': live_row.description,
                         'qty': str(live_row.qty_ordered), 'units': live_row.units})

    for d in live:
        if d.pk not in baselined_live_ids:
            rows.append({'kind': 'added', 'description': d.description,
                         'qty': str(d.qty_ordered), 'units': d.units})
    return rows


def build_change_order_payload(co):
    """Customer-safe dict for a change order. Exposes only what a customer needs
    to decide — a before/after diff of line items and deliverables."""
    actionable = _is_actionable(co)
    actions = ['accept', 'request_changes', 'reject'] if actionable else []
    closed_message = (CLOSED_MESSAGE
                      if co.status == ChangeOrder.STATUS_OPEN and not actionable
                      else None)

    diff = compose_change_order_diff(co)
    line_rows = [
        {
            'kind': r['kind'],
            'line_number': r['line_number'],
            'description': r['description'],
            'qty': str(r['qty']) if r['qty'] is not None else None,
            'units': r['units'],
            'price': _money(r['price']),
            'amount': _money(r['amount']),
        }
        for r in diff['line_rows']
    ]

    payload = {
        'change_order_number': co.change_order_number,
        'estimate_number': co.estimate.estimate_number if co.estimate_id else '',
        'status': co.status,
        'sent_date': co.sent_date,
        'expiration_date': co.expiration_date,
        'closed_date': co.closed_date,
        'deliverables': _deliverable_diff(co),
        'line_rows': line_rows,
        'prior_total': _money(diff['prior_total']),
        'proposed_total': _money(diff['proposed_total']),
        'diff_total': _money(diff['diff_total']),
        'actions': actions,
        'actionable': actionable,
        'closed_message': closed_message,
    }
    if co.status == ChangeOrder.STATUS_SUPERSEDED:
        payload['current_token'] = _current_token(co)
    return payload


def _not_available():
    return Response({'detail': 'Not available.'},
                    status=status.HTTP_404_NOT_FOUND)


def _actor_for(co, reason=None):
    contact = co.job.contact if co.job_id else None
    return {
        'contact_id': contact.pk if contact else None,
        'email': (contact.email if contact else '') or '',
        'reason': reason,
    }


def _record_customer_action(co, action_label, actor):
    """Record a customer-attributed HistoryEntry for a portal decision (the CO
    service's update_status only writes a system entry for accept and none for
    reject, so the portal records the customer's action itself — parity with the
    estimate portal's update_status(actor=…))."""
    from apps.core.models import HistoryEntry
    HistoryEntry.objects.create(
        entry_type='action',
        object_type='change_order',
        object_id=co.pk,
        user=None,
        changes={
            '_action': action_label,
            'contact_id': actor.get('contact_id'),
            'customer_email': actor.get('email'),
        },
        text=actor.get('reason') or '',
    )


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_change_order(request, token):
    co = ChangeOrder.objects.filter(public_token=token).first()
    if co is None or co.status == ChangeOrder.STATUS_DRAFT:
        return _not_available()
    return Response(build_change_order_payload(co))


def _decide(token, target_status, decision_word, action_label, reason=None):
    with transaction.atomic():
        co = (ChangeOrder.objects
              .select_for_update()
              .filter(public_token=token)
              .first())
        if co is None or co.status == ChangeOrder.STATUS_DRAFT:
            return _not_available()
        if _is_actionable(co):
            actor = _actor_for(co, reason)
            _record_customer_action(co, action_label, actor)
            ChangeOrderService.update_status(co.pk, target_status)
            acted = True
        else:
            acted = False
        co.refresh_from_db()
    if acted:
        ChangeOrderEmailService.notify_shop_of_decision(
            co, decision_word, reason=reason or '')
    return Response(build_change_order_payload(co))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_change_order_accept(request, token):
    return _decide(token, ChangeOrder.STATUS_ACCEPTED, 'accepted',
                   'Accepted via customer link')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_change_order_reject(request, token):
    reason = (request.data.get('reason') or '').strip()
    return _decide(token, ChangeOrder.STATUS_REJECTED, 'declined',
                   'Declined via customer link', reason=reason)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_change_order_request_changes(request, token):
    """Customer asks for changes: supersede the open CO and seed a fresh draft
    for the shop to revise. Only acts from 'open' — a click racing the shop is a
    no-op."""
    reason = (request.data.get('reason') or '').strip()
    with transaction.atomic():
        co = (ChangeOrder.objects
              .select_for_update()
              .filter(public_token=token)
              .first())
        if co is None or co.status == ChangeOrder.STATUS_DRAFT:
            return _not_available()
        if _is_actionable(co):
            ChangeOrderService.request_changes(co.pk, _actor_for(co, reason))
            acted = True
        else:
            acted = False
        co.refresh_from_db()
    if acted:
        ChangeOrderEmailService.notify_shop_of_decision(
            co, 'requested changes', reason=reason or '')
    return Response(build_change_order_payload(co))
