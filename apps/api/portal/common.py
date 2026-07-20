"""Helpers shared by the estimate and change-order portal views.

Both portals authorize by an opaque ``public_token``, hide drafts, and run
the same decide skeleton (lock by token → no-op unless actionable → notify
the shop → return the fresh payload). What genuinely differs between the
siblings — the actionability rule, the act performed, the payload shape —
stays in each module and is passed in as callables.
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response


def money(value):
    return str((value or Decimal('0')).quantize(Decimal('0.01')))


def not_available():
    return Response({'detail': 'Not available.'},
                    status=status.HTTP_404_NOT_FOUND)


def visible_document(model, token):
    """The document for a portal GET, or None when it doesn't exist or is
    still a draft (drafts are never portal-visible)."""
    doc = model.objects.filter(public_token=token).first()
    if doc is None or doc.status == model.STATUS_DRAFT:
        return None
    return doc


def actor_for(doc, reason=None):
    """Customer-actor dict (contact id/email + optional reason) attributed to
    a portal decision, resolved from the document's job contact."""
    contact = doc.job.contact if doc.job_id else None
    return {
        'contact_id': contact.pk if contact else None,
        'email': (contact.email if contact else '') or '',
        'reason': reason,
    }


def decide(model, token, *, is_actionable, act, notify, build_payload):
    """Shared portal decision skeleton.

    Locks the document by token inside a transaction and acts only when
    ``is_actionable(doc)`` still holds — a click racing the shop (whether the
    shop closed the document or moved the job) is a no-op. Drafts are never
    portal-visible. The shop notification runs after the transaction commits;
    the response always carries the fresh payload.
    """
    with transaction.atomic():
        doc = (model.objects
               .select_for_update()
               .filter(public_token=token)
               .first())
        if doc is None or doc.status == model.STATUS_DRAFT:
            return not_available()
        if is_actionable(doc):
            act(doc)
            acted = True
        else:
            acted = False
        doc.refresh_from_db()
    if acted:
        notify(doc)
    return Response(build_payload(doc))
