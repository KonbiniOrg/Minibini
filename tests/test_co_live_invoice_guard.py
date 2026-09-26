"""ChangeOrderService blocks remove/replace on an agreement (estimate) line
already referenced by a live (non-cancelled) invoice line item. Covers
add_line_item, update_line_item (including retargeting an existing line onto
a billed target), and the cancelled-invoice carve-out.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.jobs.services import JobService


class COLiveInvoiceGuardTests(FixtureTestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        super().setUp()
        self.cat = AccountingCategory.objects.create(
            code='LAB-GUARD', name='Labor-Guard', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Guard', last_name='Test', email='guard@t.com',
            work_number='555-9999',
        )
        self.job = JobService.create_job(name='Guard Job', contact=self.contact)
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()

        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-GUARD-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.target = EstimateLineItem.objects.create(
            estimate=self.est, description='orig', qty=1, price=50,
            line_number=1, accounting_category=self.cat,
        )
        self.other_target = EstimateLineItem.objects.create(
            estimate=self.est, description='other', qty=1, price=20,
            line_number=2, accounting_category=self.cat,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def _bill(self, target, status=Invoice.STATUS_DRAFT):
        """Create an invoice whose line item claims `target` as its
        agreement_estimate_line, at the given invoice status."""
        invoice = Invoice.objects.create(job=self.job, status=status)
        InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, qty=Decimal('1'), units='ea',
            description=target.description, price=target.price,
            accounting_category=self.cat, agreement_estimate_line=target,
        )
        return invoice

    # ── add_line_item ────────────────────────────────────────────────

    def test_add_remove_blocked_by_draft_invoice(self):
        invoice = self._bill(self.target, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
                target_line_item=self.target, description='', qty=1,
                price=0, line_number=1,
            )
        self.assertIn('target_line_item', ctx.exception.message_dict)
        msg = ctx.exception.message_dict['target_line_item'][0]
        self.assertIn(invoice.display_number, msg)
        self.assertIn('remove it from', msg)

    def test_add_replace_blocked_by_draft_invoice(self):
        invoice = self._bill(self.target, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.add_line_item(
                self.co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
                target_line_item=self.target, description='new', qty=2,
                price=75, line_number=1,
            )
        self.assertIn('target_line_item', ctx.exception.message_dict)
        msg = ctx.exception.message_dict['target_line_item'][0]
        self.assertIn(invoice.display_number, msg)

    def test_add_remove_not_blocked_by_cancelled_invoice(self):
        self._bill(self.target, status=Invoice.STATUS_CANCELLED)
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.target, description='', qty=1,
            price=0, line_number=1,
        )
        self.assertEqual(li.action, ChangeOrderLineItem.ACTION_REMOVE)
        self.assertEqual(li.target_line_item_id, self.target.pk)

    def test_add_line_item_untargeted_line_not_blocked(self):
        """A remove/replace against a line with no invoice reference at all
        must not be blocked — sanity check the guard is scoped to the
        target, not the whole job."""
        self._bill(self.other_target, status=Invoice.STATUS_DRAFT)
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.target, description='', qty=1,
            price=0, line_number=1,
        )
        self.assertEqual(li.target_line_item_id, self.target.pk)

    # ── update_line_item (including retarget) ───────────────────────

    def test_update_retarget_onto_billed_line_blocked(self):
        invoice = self._bill(self.target, status=Invoice.STATUS_DRAFT)
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.other_target, description='', qty=1,
            price=0, line_number=1,
        )
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.update_line_item(
                li.pk, target_line_item=self.target,
            )
        self.assertIn('target_line_item', ctx.exception.message_dict)
        msg = ctx.exception.message_dict['target_line_item'][0]
        self.assertIn(invoice.display_number, msg)
        # the line was not mutated
        li.refresh_from_db()
        self.assertEqual(li.target_line_item_id, self.other_target.pk)

    def test_update_existing_replace_line_blocked_when_target_becomes_billed(self):
        li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target, description='new', qty=2,
            price=75, line_number=1,
        )
        invoice = self._bill(self.target, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.update_line_item(li.pk, price=80)
        self.assertIn('target_line_item', ctx.exception.message_dict)
        msg = ctx.exception.message_dict['target_line_item'][0]
        self.assertIn(invoice.display_number, msg)
