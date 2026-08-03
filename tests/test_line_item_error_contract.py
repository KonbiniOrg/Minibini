"""TDD tests for Task 4b: LineItemMixin must not flatten dict-shaped Django
ValidationErrors into {'detail': str(e)}.

The central handler (apps/api/exceptions.py) already renders an uncaught
Django ValidationError in contract shape: dict-keyed errors (message_dict)
become field-keyed bodies ({'accounting_category': [...]}), plain-message
errors become {'detail': '<sentence>'}. LineItemMixin's line-item action
catches were re-rendering every ValidationError as {'detail': str(e)}
before it could reach that handler, which for dict-keyed errors (e.g. the
deposit coaching error) produced a garbled Python-repr string under
'detail' instead of a real field-keyed body — so the SPA's field-error
slots (FieldError) never fire for these.
"""
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import Configuration, User
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.jobs.models import Job


class LineItemErrorContractTest(BaseTestCase):
    """POST .../line-items/ with a dict-shaped ValidationError must render a
    field-keyed 400 body, not a flattened {'detail': "<stringified dict>"}."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.get(pk=1)
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def test_deposit_line_missing_config_renders_field_keyed_400(self):
        """InvoiceService.add_line_item(deposit=True) raises
        ValidationError({'accounting_category': [...]}) when
        default_deposit_accounting_category isn't configured — the API
        response must expose that as a real 'accounting_category' key, not
        stringify the dict into 'detail'."""
        Configuration.objects.filter(
            key='default_deposit_accounting_category').delete()

        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/',
            {'deposit': True, 'description': 'Deposit', 'qty': '1',
             'price': '100.00', 'units': 'none'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn('detail', response.data)
        self.assertIn('accounting_category', response.data)
        self.assertTrue(
            any('default_deposit_accounting_category' in msg
                for msg in response.data['accounting_category']),
            response.data,
        )

    def test_hand_line_missing_accounting_category_renders_field_keyed_400(self):
        """EstimateService.add_line_item() raises
        ValidationError({'accounting_category': [...]}) for a hand-line with
        no atom source and no AC — same contract requirement, a different
        service/dict-shaped error."""
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-9001',
            status=Estimate.STATUS_DRAFT,
        )

        response = self.client.post(
            f'/api/estimates/{estimate.pk}/line-items/',
            {'description': 'Rush handling', 'qty': '1', 'price': '25.00',
             'freeform_kind': 'fee'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn('detail', response.data)
        self.assertIn('accounting_category', response.data)
