# apps/core/units.py
import json
from django import forms
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


def units_choices():
    """Return units as Django form choices: list of (value, label) tuples."""
    return [(u, u) for u in get_units_list()]


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
