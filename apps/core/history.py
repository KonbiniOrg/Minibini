import contextvars

from django.db.models.signals import post_init, pre_save, post_save


# Request-scoped context
_history_context = contextvars.ContextVar('history_context', default=None)


class HistoryContext:
    """Holds pending changes and the request user for one request."""
    def __init__(self, user=None):
        self.user = user
        self.pending = []


def get_history_context():
    return _history_context.get(None)


def set_history_context(ctx):
    _history_context.set(ctx)


# --- Domain routing: history is partitioned into per-domain tables ---------
# object_type -> concrete history model. The single write entry point
# (record_history) and every read site use this to hit the right table.
_DOMAIN_MODELS = None


def _domain_models():
    global _DOMAIN_MODELS
    if _DOMAIN_MODELS is None:
        from apps.core.models import (
            JobHistory, CrmHistory, PurchasingHistory, InventoryHistory,
            ExpensesHistory,
        )
        job, crm, pur, inv, exp = (
            JobHistory, CrmHistory, PurchasingHistory, InventoryHistory,
            ExpensesHistory,
        )
        _DOMAIN_MODELS = {
            'job': job, 'task': job, 'estimate': job, 'changeorder': job,
            'invoice': job, 'material': job, 'deliverable': job, 'shipment': job,
            'contact': crm, 'business': crm,
            'purchaseorder': pur, 'bill': pur,
            'inventoryitem': inv,
            'expense': exp, 'reimbursement': exp,
        }
    return _DOMAIN_MODELS


def history_model_for(object_type):
    """Concrete history model that owns this object_type, or None if untracked."""
    return _domain_models().get(object_type)


def record_history(object_type, entry_type='audit', object_id=None,
                   user=None, changes=None, text='', timestamp=None):
    """Create a history row in the table that owns ``object_type``.

    The single write entry point for all history (decorator + services + notes).
    ``timestamp`` is normally auto-set; pass it only to backdate (it's applied
    via update() since the column is auto_now_add).
    """
    model = history_model_for(object_type)
    if model is None:
        raise ValueError(f'No history table is configured for object_type {object_type!r}')
    obj = model.objects.create(
        entry_type=entry_type, object_type=object_type, object_id=object_id,
        user=user, changes=changes, text=text,
    )
    if timestamp is not None:
        model.objects.filter(pk=obj.pk).update(timestamp=timestamp)
        obj.timestamp = timestamp
    return obj


def current_request_user():
    """The authenticated user for the active request (from HistoryContext), or None.

    Mirrors the middleware's flush-time resolution: prefers ``_request.user``
    when it is present and authenticated, then falls back to an explicitly-set
    ``ctx.user`` (non-request callers / tests).
    """
    ctx = get_history_context()
    if ctx is None:
        return None
    request = getattr(ctx, '_request', None)
    if request is not None and getattr(request, 'user', None) is not None \
            and request.user.is_authenticated:
        return request.user
    return ctx.user


def record_action(object_type, object_id, action, user=None):
    """Record a human-readable 'action' history entry.

    Defaults the author to the current request user (``current_request_user``)
    so callers need not thread it through.  Pass ``user=`` explicitly only for
    a deliberate non-request author (e.g. a management command).
    """
    return record_history(
        entry_type='action',
        object_type=object_type,
        object_id=object_id,
        user=user if user is not None else current_request_user(),
        changes={'_action': action},
    )


def _snapshot_fields(instance):
    """Capture current field values for later diffing."""
    if not instance.pk:
        instance._history_original = None
        return
    exclude = instance.__class__._history_exclude
    deferred = instance.get_deferred_fields()
    instance._history_original = {
        f.attname: getattr(instance, f.attname)
        for f in instance.__class__._meta.concrete_fields
        if f.attname not in exclude and f.attname not in deferred
    }


def _on_post_init(sender, instance, **kwargs):
    """Signal handler: snapshot field values when instance loads from DB."""
    _snapshot_fields(instance)


def _serialize_value(val):
    """Convert value to JSON-safe representation."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    return str(val)


def _get_object_type(model_class):
    """Get the object_type string for a model class."""
    return model_class.__name__.lower()


def _compute_diff(instance):
    """Compare current field values to snapshot, return changes dict."""
    original = getattr(instance, '_history_original', None)
    exclude = instance.__class__._history_exclude
    fields = {
        f.attname: f
        for f in instance.__class__._meta.concrete_fields
        if f.attname not in exclude
    }

    changes = {}
    if original is None:
        # New object — just mark as created, no field-level diff
        return None
    else:
        for attname, old_val in original.items():
            if attname not in fields:
                continue
            new_val = getattr(instance, attname)
            if old_val != new_val:
                changes[attname] = {
                    'old': _serialize_value(old_val),
                    'new': _serialize_value(new_val),
                }
    return changes


def _on_pre_save(sender, instance, **kwargs):
    """Compute diff and either queue it or save immediately."""
    if not getattr(sender, '_history_tracked', False):
        return

    is_new = not bool(instance.pk)
    changes = _compute_diff(instance)
    if changes is None and not is_new:
        return  # no changes on an existing object
    if not changes and not is_new:
        return  # empty diff on an existing object

    ctx = get_history_context()
    entry_data = {
        'entry_type': 'audit',
        'object_type': _get_object_type(sender),
        'object_id': instance.pk,  # may be None for new objects
        'changes': {'_created': True} if is_new else changes,
        'text': '',
        '_instance': instance,  # reference to get pk after save
        '_is_new': is_new,
    }

    if ctx is not None:
        ctx.pending.append(entry_data)
    else:
        # Outside a request — if updating, create immediately
        if instance.pk:
            record_history(
                object_type=entry_data['object_type'],
                entry_type='audit',
                object_id=instance.pk,
                changes=changes,
                text=entry_data.get('text', ''),
                user=None,
            )
        else:
            # New object outside request — stash for post_save
            instance._history_pending_create = entry_data


def _on_post_save(sender, instance, created, **kwargs):
    """For new objects saved outside a request, create the history entry now that pk exists."""
    if not getattr(sender, '_history_tracked', False):
        return

    pending = getattr(instance, '_history_pending_create', None)
    if pending and created:
        record_history(
            object_type=pending['object_type'],
            entry_type='audit',
            object_id=instance.pk,
            changes=pending['changes'],
            text=pending.get('text', ''),
            user=None,
        )
        del instance._history_pending_create

    # Re-snapshot after save so subsequent changes diff correctly
    _snapshot_fields(instance)


def history(exclude=None):
    """Decorator to mark a model for automatic history tracking."""
    def decorator(cls):
        cls._history_tracked = True
        cls._history_exclude = set(exclude or [])
        post_init.connect(_on_post_init, sender=cls, weak=False)
        pre_save.connect(_on_pre_save, sender=cls, weak=False)
        post_save.connect(_on_post_save, sender=cls, weak=False)
        return cls
    return decorator
