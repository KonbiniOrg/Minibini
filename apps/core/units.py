# apps/core/units.py
import json
from django import forms
from rest_framework import serializers as drf_serializers
from django.core.exceptions import ValidationError
from apps.core.models import Configuration


DEFAULT_UNITS = [
    "none", "ea", "hours", "min", "sheets", "sq ft", "ft", "yd", "m",
    "lbs", "kg", "gal", "qt", "L", "bd ft", "ln ft",
]


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


class UnitsFieldMixin:
    """Mixin for ModelForms that have a 'units' field.
    Replaces the default CharField widget with a Select dropdown
    populated from the configured units list.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'units' in self.fields:
            self.fields['units'] = forms.ChoiceField(
                choices=units_choices(),
                initial='none',
            )
