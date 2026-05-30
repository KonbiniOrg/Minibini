"""Email body / subject template rendering for outbound documents.

`str.format_map`-style substitution with safe handling of unknown
placeholders (they pass through literally rather than raising
KeyError), so user-edited templates can't crash the send.
"""


class _SafeFormatDict(dict):
    """dict that returns ``{key}`` for missing keys instead of raising,
    and converts None values to empty strings."""

    def __missing__(self, key):
        return '{' + key + '}'


def render_email_template(template: str, **values) -> str:
    """Render an email template by substituting `{name}`-style placeholders.

    Unknown placeholders render as their literal `{name}` form; ``None`` values
    render as empty strings. Doubled braces ``{{`` / ``}}`` are escape
    sequences and render as single braces, per ``str.format`` convention.
    """
    if not template:
        return ''
    safe = _SafeFormatDict({
        key: ('' if value is None else str(value))
        for key, value in values.items()
    })
    return template.format_map(safe)


# Defaults the customer-facing URL stub against. Real public URLs will use
# signed tokens; this is a placeholder that lets templates author against a
# sensible URL shape now. See LATER.md "Customer-facing public URLs".
DEFAULT_OUR_PUBLIC_URL = 'https://example.com'

_OBJECT_URL_PATHS = {
    'estimate': 'estimates',
    'purchase_order': 'purchase-orders',
    'invoice': 'invoices',
    'bill': 'bills',
}


def build_object_url(kind, obj_id):
    """Resolve the ``{object_url}`` template placeholder for a given doc.

    Reads the `our_public_url` Configuration key (default
    `https://example.com`) and appends `/<entity-path>/<id>`. The URLs
    don't actually work for unauthenticated customers today; this is the
    placeholder shape that lets templates author against something real.
    """
    from apps.core.models import Configuration
    try:
        base = Configuration.objects.get(key='our_public_url').value
    except Configuration.DoesNotExist:
        base = DEFAULT_OUR_PUBLIC_URL
    path = _OBJECT_URL_PATHS.get(kind, kind)
    return f'{base.rstrip("/")}/{path}/{obj_id}'
