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
        # New object — record all non-empty fields as old=None -> new=value
        for attname in fields:
            new_val = getattr(instance, attname)
            if new_val is not None and new_val != '':
                changes[attname] = {'old': None, 'new': _serialize_value(new_val)}
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

    changes = _compute_diff(instance)
    if not changes:
        return

    ctx = get_history_context()
    entry_data = {
        'entry_type': 'audit',
        'object_type': _get_object_type(sender),
        'object_id': instance.pk,  # may be None for new objects
        'changes': changes,
        '_instance': instance,  # reference to get pk after save
        '_is_new': not bool(instance.pk),
    }

    if ctx is not None:
        ctx.pending.append(entry_data)
    else:
        # Outside a request — if updating, create immediately
        if instance.pk:
            from apps.core.models import HistoryEntry
            HistoryEntry.objects.create(
                entry_type='audit',
                object_type=entry_data['object_type'],
                object_id=instance.pk,
                changes=changes,
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
        from apps.core.models import HistoryEntry
        HistoryEntry.objects.create(
            entry_type='audit',
            object_type=pending['object_type'],
            object_id=instance.pk,
            changes=pending['changes'],
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
