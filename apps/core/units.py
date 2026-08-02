# apps/core/units.py
import json
from rest_framework import serializers as drf_serializers
from django.core.exceptions import ValidationError
from apps.core.models import Configuration


DEFAULT_UNITS = [
    "none", "ea", "hour", "min", "sheet", "sq ft", "ft", "yd", "m",
    "lb", "kg", "gal", "qt", "L", "bd ft", "ln ft",
]

# The unit time-based billing and scheduling are denominated in. Present in
# every units_list (the settings endpoint refuses to remove it); elapsed_time
# RateSchemes are pinned to it.
HOUR_UNIT = "hour"


def get_units_list():
    """Load the allowed units list from Configuration.

    Returns a list of strings. Falls back to DEFAULT_UNITS if the
    units_list key has not been set up yet.
    """
    try:
        config = Configuration.objects.get(key='units_list')
        return json.loads(config.value)
    except Configuration.DoesNotExist:
        return list(DEFAULT_UNITS)


def validate_unit(value):
    """Validate that a units value is in the configured list."""
    allowed = get_units_list()
    if value not in allowed:
        raise ValidationError(
            f'"{value}" is not a configured unit.',
            code='invalid_unit',
        )


def units_choices():
    """Return units as Django form choices: list of (value, label) tuples."""
    return [(u, u) for u in get_units_list()]


class UnitsField(drf_serializers.ChoiceField):
    """DRF field that validates units against the configured list.

    Refreshes choices from the database on every validation call so that
    changes to the configured units list take effect without restarting.
    """
    def __init__(self, **kwargs):
        kwargs.setdefault('default', 'none')
        super().__init__(choices=[], **kwargs)

    def _refresh_choices(self):
        """Reload choices from the DB and rebuild internal mappings."""
        try:
            self.choices = [(u, u) for u in get_units_list()]
        except Configuration.DoesNotExist:
            self.choices = []

    def run_validation(self, data=drf_serializers.empty):
        self._refresh_choices()
        return super().run_validation(data)
