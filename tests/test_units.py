# tests/test_units.py
import json
from tests.base import BaseTestCase
from apps.core.models import Configuration
from apps.core.units import get_units_list, validate_unit


class GetUnitsListTest(BaseTestCase):

    def test_returns_list_from_config(self):
        result = get_units_list()
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], 'none')

    def test_falls_back_to_defaults_if_config_missing(self):
        Configuration.objects.filter(key='units_list').delete()
        result = get_units_list()
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], 'none')
        self.assertIn('hour', result)


class ValidateUnitTest(BaseTestCase):

    def test_valid_unit_passes(self):
        validate_unit('hour')  # should not raise

    def test_invalid_unit_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            validate_unit('invalid_unit_xyz')

    def test_none_is_valid(self):
        validate_unit('none')  # should not raise
