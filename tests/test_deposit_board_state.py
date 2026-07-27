from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job
from apps.jobs.services import BoardService


class DepositBoardStateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_IN_PROGRESS)

    def _deposit_invoice(self, status):
        inv = Invoice.objects.create(job=self.job,
                                     status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='Deposit', qty=Decimal('1'),
            price=Decimal('5000.00'), accounting_category=self.dep_cat)
        Invoice.objects.filter(pk=inv.pk).update(status=status)
        return inv, li

    def test_no_deposit_none(self):
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_draft_deposit_none(self):
        self._deposit_invoice(Invoice.STATUS_DRAFT)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_sent_unpaid_is_requested(self):
        self._deposit_invoice(Invoice.STATUS_OPEN)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'requested'})

    def test_paid_unclaimed_is_paid(self):
        self._deposit_invoice(Invoice.STATUS_PAID)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'paid'})

    def test_requested_wins_over_paid(self):
        self._deposit_invoice(Invoice.STATUS_PAID)
        self._deposit_invoice(Invoice.STATUS_OPEN)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'requested'})

    def test_claimed_deposit_clears_paid(self):
        _, dep_line = self._deposit_invoice(Invoice.STATUS_PAID)
        final = Invoice.objects.create(job=self.job,
                                       status=Invoice.STATUS_DRAFT)
        ded = InvoiceLineItem.objects.create(
            invoice=final, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-5000.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep_line.pk)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_serialized_job_carries_state(self):
        self._deposit_invoice(Invoice.STATUS_OPEN)
        data = BoardService.get_board_data()
        # get_board_data's real shape: {'pipeline': [...], 'approved':
        # {'jobs': [...], ...}, 'closed': [...]}. This job is in_progress,
        # so it lives in data['approved']['jobs'].
        candidates = list(data['pipeline']) + list(data['approved']['jobs']) \
            + list(data['closed'])
        card = next(
            (j for j in candidates if j.get('job_id') == self.job.pk), None)
        self.assertIsNotNone(card)
        self.assertEqual(card['deposit_state'], 'requested')
