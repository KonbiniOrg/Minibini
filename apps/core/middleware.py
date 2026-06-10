from apps.core.history import HistoryContext, set_history_context


class HistoryMiddleware:
    """Middleware that collects field changes during a request and creates
    HistoryEntry records after the view completes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx = HistoryContext()
        ctx._request = request  # resolve user at flush time
        set_history_context(ctx)

        try:
            response = self.get_response(request)
            self._flush_pending(ctx)
            return response
        except Exception:
            # Discard pending entries on error (transaction will roll back)
            raise
        finally:
            set_history_context(None)

    def _flush_pending(self, ctx):
        from apps.core.history import record_history

        # Resolve user at flush time (after DRF auth has run)
        user = None
        request = getattr(ctx, '_request', None)
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user

        for entry_data in ctx.pending:
            instance = entry_data.pop('_instance', None)
            is_new = entry_data.pop('_is_new', False)
            object_id = entry_data.get('object_id')

            # For new objects, get pk from instance (it now has one after save)
            if is_new and instance is not None:
                object_id = instance.pk

            if not object_id:
                continue

            record_history(
                object_type=entry_data['object_type'],
                entry_type=entry_data['entry_type'],
                object_id=object_id,
                changes=entry_data['changes'],
                text=entry_data.get('text', ''),
                user=user,
            )
