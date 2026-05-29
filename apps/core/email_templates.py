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
