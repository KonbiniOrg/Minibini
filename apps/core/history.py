from django.db.models.signals import post_init


def _snapshot_fields(instance):
    """Capture current field values for later diffing."""
    if not instance.pk:
        instance._history_original = None
        return
    exclude = instance.__class__._history_exclude
    instance._history_original = {
        f.attname: getattr(instance, f.attname)
        for f in instance.__class__._meta.concrete_fields
        if f.attname not in exclude
    }


def _on_post_init(sender, instance, **kwargs):
    """Signal handler: snapshot field values when instance loads from DB."""
    _snapshot_fields(instance)


def history(exclude=None):
    """Decorator to mark a model for automatic history tracking."""
    def decorator(cls):
        cls._history_tracked = True
        cls._history_exclude = set(exclude or [])
        post_init.connect(_on_post_init, sender=cls, weak=False)
        return cls
    return decorator
