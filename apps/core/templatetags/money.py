from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name='money')
def money(value):
    """Format a number as US currency with the sign before the '$' for a
    negative amount ("-$500.00"), never after it.

    I2 review finding: the PDF templates hand-rolled `${{ x|floatformat:2
    }}`, which puts the literal `$` before floatformat's own sign and
    renders a credit/decrease line as the nonsensical "$-500.00". This
    filter owns the `$` placement instead, mirroring the SPA's
    `formatMoney` (frontend/src/lib/format.js) so a negative amount reads
    the same way everywhere the customer sees it. An unparseable value is
    returned unchanged (matches floatformat's own fail-open behavior)."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = '-' if amount < 0 else ''
    return f'{sign}${abs(amount):,.2f}'
