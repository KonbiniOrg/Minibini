from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.estimates.models import Estimate, EstimateLineItem
from apps.jobs.models import Job


class EstimateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_estimates(self):
        response = self.client.get('/api/estimates/')
        self.assertEqual(response.status_code, 200)

    def test_create_rejected_when_job_already_has_estimate(self):
        """One estimate tree per job: a second create is refused (400), not a
        500 from the unique (job-derived) number collision."""
        from apps.contacts.models import Contact
        contact = Contact.objects.create(first_name='E', last_name='X', email='ex@dup.com')
        job = Job.objects.create(contact=contact, job_number='JOB-EST-DUP-1')
        first = self.client.post('/api/estimates/', {'job': job.pk}, format='json')
        self.assertIn(first.status_code, [200, 201])
        second = self.client.post('/api/estimates/', {'job': job.pk}, format='json')
        self.assertEqual(second.status_code, 400)

    def test_retrieve_estimate(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('line_items', response.data)

    def test_update_estimate(self):
        estimate = Estimate.objects.filter(status=Estimate.STATUS_DRAFT).first()
        if estimate:
            response = self.client.patch(f'/api/estimates/{estimate.pk}/', {
                'status': Estimate.STATUS_DRAFT,
            }, format='json')
            self.assertEqual(response.status_code, 200)

    def test_add_line_item(self):
        estimate = Estimate.objects.first()
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '2.00',
            'units': 'ea',
            'description': 'API test item',
            'price': '100.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_list_line_items(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/line-items/')
        self.assertEqual(response.status_code, 200)

    def test_delete_line_item(self):
        line_item = EstimateLineItem.objects.first()
        if line_item:
            estimate = line_item.estimate
            response = self.client.delete(
                f'/api/estimates/{estimate.pk}/line-items/{line_item.pk}/'
            )
            self.assertEqual(response.status_code, 200)

    def test_discard_draft_returns_200_with_message(self):
        job = Job.objects.first()
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-DISCARD-001',
            status=Estimate.STATUS_DRAFT,
        )
        pk = estimate.pk
        response = self.client.delete(f'/api/estimates/{pk}/?confirm=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Estimate.objects.filter(pk=pk).exists())

    def test_discard_non_draft_returns_400(self):
        job = Job.objects.first()
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-DISCARD-002',
            status=Estimate.STATUS_DRAFT,
        )
        Estimate.objects.filter(pk=estimate.pk).update(status=Estimate.STATUS_OPEN)
        response = self.client.delete(f'/api/estimates/{estimate.pk}/?confirm=true')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Estimate.objects.filter(pk=estimate.pk).exists())


class EstimateSendTest(BaseTestCase):
    """The new /api/estimates/{id}/send-defaults/ + /send/ endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-SEND-001',
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_number=1,
            qty='1.00', units='ea',
            description='Bracket assembly',
            price='100.00',
        )

    def test_send_defaults_returns_to_subject_body_and_attachment_preview(self):
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('to', response.data)
        self.assertIn('subject', response.data)
        self.assertIn('body', response.data)
        self.assertIn('attachments_preview', response.data)
        # Default contact email should be in the To field
        self.assertEqual(response.data['to'], self.job.contact.email)
        # Subject template default mentions the estimate number
        self.assertIn(self.estimate.estimate_number, response.data['subject'])
        # Attachment preview names the auto-attached PDF
        self.assertEqual(len(response.data['attachments_preview']), 1)
        self.assertEqual(
            response.data['attachments_preview'][0]['filename'],
            f'Estimate-{self.estimate.estimate_number}.pdf',
        )

    @patch('apps.estimates.pdf.generate_estimate_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_happy_path_persists_outbound_and_transitions_status(
        self, MockEmailMessage, mock_pdf,
    ):
        MockEmailMessage.return_value = MagicMock()
        mock_pdf.return_value = b'%PDF-estimate'

        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {
                'to': 'jane@example.com',
                'subject': 'Estimate ' + self.estimate.estimate_number,
                'body': 'Hi Jane, please review.',
                'cc': '',
                'bcc': '',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)

        # An outbound EmailRecord exists, linked to this Estimate's job.
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)
        self.assertEqual(outbound.last_send_error, '')

    @patch('apps.estimates.pdf.generate_estimate_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_smtp_failure_returns_error_and_keeps_status(
        self, MockEmailMessage, mock_pdf,
    ):
        fail_msg = MagicMock()
        fail_msg.send.side_effect = RuntimeError('SMTP unreachable')
        MockEmailMessage.return_value = fail_msg
        mock_pdf.return_value = b'%PDF-estimate'

        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {'to': 'jane@example.com', 'subject': 'Test', 'body': 'Test'},
            format='json',
        )
        self.assertEqual(response.status_code, 502)
        self.estimate.refresh_from_db()
        # Status NOT advanced because SMTP failed.
        self.assertEqual(self.estimate.status, Estimate.STATUS_DRAFT)
        # Failure persisted on the EmailRecord.
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNone(outbound.sent_at)
        self.assertIn('SMTP unreachable', outbound.last_send_error)

    def test_send_missing_to_returns_400(self):
        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_send_defaults_resolves_object_url_placeholder(self):
        """Body templates can include {object_url} — for an estimate it resolves
        to the customer portal token URL (<base>/portal/?token=<token>)."""
        from apps.core.models import Configuration
        Configuration.objects.update_or_create(
            key='our_public_url',
            defaults={'value': 'https://customer.nealscnc.com'},
        )
        Configuration.objects.update_or_create(
            key='estimate_email_body_template',
            defaults={'value': 'Hi {contact_fname}, see {object_url}'},
        )
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.estimate.refresh_from_db()
        expected_url = (
            f'https://customer.nealscnc.com/portal/?token={self.estimate.public_token}'
            '&doc=estimate'
        )
        self.assertIn(expected_url, response.data['body'])

    def test_send_defaults_object_url_defaults_to_example_com(self):
        """Without an our_public_url Config row, fall back to example.com."""
        from apps.core.models import Configuration
        Configuration.objects.filter(key='our_public_url').delete()
        Configuration.objects.update_or_create(
            key='estimate_email_body_template',
            defaults={'value': '{object_url}'},
        )
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://example.com/portal/?token=', response.data['body'])


class EstimateAdjustmentLineAPITest(BaseTestCase):
    """Tests for POST /api/estimates/{id}/adjustment-lines/ and auto-recompute."""

    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.labor = AccountingCategory.objects.get(pk=901)
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-ADJ-001',
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Line A', price=Decimal('100.00'),
            accounting_category=self.labor,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='ea', description='Line B', price=Decimal('40.00'),
            accounting_category=self.labor,
        )

    def test_adjustment_line_created_with_correct_price(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.labor,
        )
        resp = self.client.post(
            f'/api/estimates/{self.est.pk}/adjustment-lines/',
            {'adjustment_service': rush.pk, 'target_category_ids': []},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        # 15% of (100 + 40) = 21.00
        self.assertEqual(resp.json()['price'], '21.00')

    def test_recalculate_endpoint_removed(self):
        """The recalculate endpoint no longer exists (adjustments auto-recompute)."""
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        rush = RateScheme.objects.create(
            name='Rush5', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.labor,
        )
        resp = self.client.post(
            f'/api/estimates/{self.est.pk}/adjustment-lines/',
            {'adjustment_service': rush.pk, 'target_category_ids': []},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        lid = resp.json()['line_item_id']
        r2 = self.client.post(
            f'/api/estimates/{self.est.pk}/line-items/{lid}/recalculate/',
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 404)
