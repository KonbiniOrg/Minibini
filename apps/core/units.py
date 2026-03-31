# apps/core/units.py
import json
from django.core.exceptions import ValidationError
from apps.core.models import Configuration


def get_units_list():
    """Load the allowed units list from Configuration.

    Returns a list of strings. Raises Configuration.DoesNotExist
    if the units_list key has not been set up.
    """
    config = Configuration.objects.get(key='units_list')
    return json.loads(config.value)


def validate_unit(value):
    """Validate that a units value is in the configured list."""
    allowed = get_units_list()
    if value not in allowed:
        raise ValidationError(
            f'"{value}" is not a configured unit.',
            code='invalid_unit',
        )
