"""The API error-response contract (2026-07-04).

Two shapes, enforced centrally by apps.api.exceptions.api_exception_handler:

- Operation errors: {'detail': '<sentence>'} with the appropriate status.
- Field validation errors: {'<field>': ['msg', ...]} (DRF serializer shape);
  Django's '__all__' bucket is renamed to DRF's 'non_field_errors'.
- {'message': ...} is success-only, never an error body.
- The 'error' key is retired.

The handler is the safety net: a service/model DjangoValidationError (or a
PROTECT cascade) that no view translates renders as a clean 400/409 instead
of a 500.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from tests.base import grant_atoms
from apps.api.exceptions import api_exception_handler
from apps.core.models import AccountingCategory, User
from apps.jobs.models import RateScheme


class ExceptionHandlerUnitTest(TestCase):
    """Direct unit coverage of the handler's rendering rules."""

    def test_single_message_renders_as_detail(self):
        resp = api_exception_handler(
            DjangoValidationError('Job is on hold.'), context={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {'detail': 'Job is on hold.'})

    def test_multiple_messages_join_into_one_detail(self):
        resp = api_exception_handler(
            DjangoValidationError(['First problem.', 'Second problem.']),
            context={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data,
                         {'detail': 'First problem. Second problem.'})

    def test_field_dict_passes_through_field_keyed(self):
        resp = api_exception_handler(
            DjangoValidationError({'name': ['Required.'],
                                   'qty': ['Must be positive.']}),
            context={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {'name': ['Required.'],
                                     'qty': ['Must be positive.']})

    def test_all_bucket_renamed_to_non_field_errors(self):
        resp = api_exception_handler(
            DjangoValidationError({'__all__': ['Dates overlap.']}),
            context={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {'non_field_errors': ['Dates overlap.']})

    def test_protected_error_renders_as_409(self):
        resp = api_exception_handler(
            ProtectedError('protected', set()), context={})
        self.assertEqual(resp.status_code, 409)
        self.assertIn('detail', resp.data)

    def test_unknown_exception_still_escapes(self):
        # Programming errors must stay 500s — the handler only owns the
        # two domain-exception types.
        self.assertIsNone(api_exception_handler(RuntimeError('boom'), {}))


class ExceptionHandlerIntegrationTest(TestCase):
    """An endpoint with NO view-level translation renders through the
    handler, end to end (proves the settings registration)."""

    def setUp(self):
        self.client_ = APIClient()
        self.client_.force_authenticate(user=grant_atoms(
            User.objects.create_user(username='errc_u', password='x'),
            'can_manage_config'))

    def test_uncaught_service_validation_error_is_json_400(self):
        # The negative-rate rule lives ONLY in RateScheme.clean() — the
        # serializer accepts any Decimal, so the field-keyed
        # DjangoValidationError escapes ConfigurationService.create_rate_scheme
        # with no view-level translation. The handler must render it.
        cat = AccountingCategory.objects.create(name='errc', code='ERRC')
        resp = self.client_.post('/api/rate-schemes/', {
            'name': 'ERRC scheme', 'algorithm': RateScheme.ENTERED_QTY,
            'rate': '-5', 'unit_label': 'ea', 'accounting_category': cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('rate', resp.data)
