"""'Struck from agreement' badge derivation (RM decision 2026-07-20).

An accepted CO's remove/replace can target an estimate line whose atom
crystallization deliberately left live (consumed/complete/etc.). Nothing
stores that skip — ChangeOrderService.struck_atom_keys derives it from the
persisted chain (accepted CO line → target estimate line → claim rows →
atom), and the invoice wizard pool badges those atoms so the biller chooses
consciously. No hold/status lifecycle changes — see estimates-and-prices
§14.11 decision record.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
    EstimateLineItemSource,
)
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task


class StruckAtomKeysTest(TestCase):
    def setUp(self):
        from apps.core.models import AppState, Configuration
        Configuration.objects.update_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{year}-{counter:04d}'})
        AppState.objects.get_or_create(
            key='invoice_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='sb', code='SB')
        self.scheme = RateScheme.objects.create(
            name='S-sb', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.cat)
        contact = Contact.objects.create(
            first_name='S', last_name='B', email='sb@test.com')
        self.job = Job.objects.create(
            job_number='JOB-SB-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)
        self.task = Task(
            job=self.job, name='Struck work',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.other_task = Task(
            job=self.job, name='Untouched work',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('1'))
        self.other_task.stamp_from_scheme(self.scheme)
        self.other_task.save()
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SB-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        line = EstimateLineItem.objects.create(
            estimate=est, line_number=1, description='Struck line',
            qty=Decimal('2'), price=Decimal('10'),
            accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk)
        co = ChangeOrder.objects.create(
            job=self.job, estimate=est, change_order_number='CO-SB-1',
            status=ChangeOrder.STATUS_ACCEPTED)
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=line, line_number=1)

    def test_helper_returns_struck_atom_key(self):
        keys = ChangeOrderService.struck_atom_keys(self.job)
        self.assertIn(('task', self.task.pk), keys)
        self.assertNotIn(('task', self.other_task.pk), keys)

    def test_draft_co_targets_do_not_count(self):
        # Only ACCEPTED COs strike the agreement.
        ChangeOrder.objects.filter(job=self.job).update(
            status=ChangeOrder.STATUS_DRAFT)
        self.assertEqual(ChangeOrderService.struck_atom_keys(self.job), set())

    def test_pool_flags_struck_task(self):
        from apps.invoicing.models import Invoice
        invoice = Invoice.objects.create(job=self.job)
        pool = InvoiceWizardService.get_source_pool(invoice)
        atoms = {a['id']: a for g in pool['tasks'] for a in g['atoms']
                 if a['type'] == 'task'}
        self.assertTrue(atoms[self.task.pk]['struck_from_agreement'])
        self.assertFalse(atoms[self.other_task.pk]['struck_from_agreement'])

    def test_pool_suppresses_struck_on_cancelled_task(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_CANCELLED)
        from apps.invoicing.models import Invoice
        invoice = Invoice.objects.create(job=self.job)
        pool = InvoiceWizardService.get_source_pool(invoice)
        atom = next(a for g in pool['tasks'] for a in g['atoms']
                    if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertTrue(atom['task_cancelled'])
        self.assertFalse(atom['struck_from_agreement'])
