"""
Pins down the "an accepted estimate's adjustment must not land on the invoice
twice" guarantee — the dedup that the planned **Copy from estimate** /
**Apply everything** invoice buttons will both rely on.

The whole mechanism keys on one fact: an invoice's adjustment is identified by
its ``adjustment_service`` (the percentage RateScheme). The
``agreement-adjustments`` endpoint surfaces the accepted estimate's (+ accepted
CO) adjustments and flags each ``already_added`` when the invoice already has a
line carrying that same ``adjustment_service``. So no matter how the adjustment
got onto the invoice — added manually from the panel, or copied in wholesale by
the future "Copy from estimate" button — the panel reports it as already present
and won't offer a second copy.

These tests exercise the CURRENT machinery (the panel endpoint +
``adjustment-lines``) and additionally simulate the future copy-from-estimate
path (an invoice line that already carries ``adjustment_service``) to prove the
dedup key holds regardless of origin.
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AppState, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job, RateScheme
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceAgreementAdjustmentDedupTest(TestCase):
    def setUp(self):
        # Invoice numbering needs its pattern + counter.
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-DD', name='Labor-DD', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Dee', last_name='Dup', email='dd@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-DD-0001',
        )

        # An ACCEPTED estimate with one base line ($200) and a 15% adjustment.
        # Created directly as ACCEPTED so no transition cascade / carry-over runs
        # (compose_agreement only needs the accepted estimate's lines).
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-DD-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('200.00'),
            accounting_category=self.cat,
        )
        self.rush_svc = RateScheme.objects.create(
            name='Rush-DD', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.cat,
        )
        # The estimate's adjustment line (15% of 200 = 30).
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='%', description='Rush 15%', price=Decimal('30.00'),
            adjustment_service=self.rush_svc,
            adjustment_percent=self.rush_svc.rate,
        )

        # A draft invoice for the same job.
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

        self.user = User.objects.create_user(username='fin-dd', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _agreement_adjustments(self):
        resp = self.client.get(
            f'/api/invoices/{self.invoice.pk}/agreement-adjustments/'
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data['adjustments']

    def test_panel_lists_accepted_estimate_adjustment_not_yet_added(self):
        """The accepted estimate's adjustment shows up, not-yet-added."""
        adjustments = self._agreement_adjustments()
        self.assertEqual(len(adjustments), 1)
        entry = adjustments[0]
        self.assertEqual(entry['adjustment_service_id'], self.rush_svc.pk)
        self.assertEqual(Decimal(str(entry['percent'])), Decimal('15.00'))
        self.assertFalse(entry['already_added'])

    def test_adding_from_panel_flips_already_added_and_makes_one_line(self):
        """Adding the adjustment via the panel endpoint marks it already_added
        and creates exactly one invoice adjustment line carrying that service."""
        add = self.client.post(
            f'/api/invoices/{self.invoice.pk}/adjustment-lines/',
            {'adjustment_service': self.rush_svc.pk, 'target_category_ids': []},
            format='json',
        )
        self.assertEqual(add.status_code, 201, add.data)

        # Exactly one invoice line now carries this adjustment_service.
        self.assertEqual(
            InvoiceLineItem.objects.filter(
                invoice=self.invoice, adjustment_service=self.rush_svc,
            ).count(),
            1,
        )

        # The panel now reports it as already_added (won't be offered again).
        adjustments = self._agreement_adjustments()
        self.assertEqual(len(adjustments), 1)
        self.assertTrue(adjustments[0]['already_added'])

    def test_copy_from_estimate_origin_also_dedups(self):
        """Simulate the future 'Copy from estimate' button bringing the
        adjustment in wholesale: an invoice line that already carries the
        estimate's adjustment_service. The panel must then report already_added,
        so the user is never offered a second copy regardless of origin."""
        # What copy-from-estimate would create: a faithful copy of the agreement's
        # adjustment line, carrying the same adjustment_service.
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='%', description='Rush 15%', price=Decimal('30.00'),
            adjustment_service=self.rush_svc,
            adjustment_percent=self.rush_svc.rate,
        )

        adjustments = self._agreement_adjustments()
        self.assertEqual(len(adjustments), 1)
        self.assertTrue(adjustments[0]['already_added'])
