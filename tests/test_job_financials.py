"""
Tests for compute_job_financials(job) — the single source of truth for the
job-header financial rollups (Estimate / Spent / Invoiced / Profit) and the
job-board card profitability numbers.

See docs/plans/2026-06-11-job-financials-header-design.md.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from tests.base import FixtureTestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
)
from apps.contacts.models import Business
from apps.expenses.models import Expense
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Blep, Job, RateScheme, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService


def _job(contact, status=Job.STATUS_DRAFT, start_date=None):
    return Job.objects.create(
        job_number=f'JOB-FIN-{Job.objects.count() + 1:04d}',
        name='Fin Test Job', status=status, contact=contact,
        start_date=start_date,
    )


def _est(job, version, status, *lines):
    """Create an estimate with line items. lines = list of (qty, price)."""
    est = Estimate.objects.create(
        job=job, estimate_number=f'{job.job_number}-{version}',
        version=version, status=status,
    )
    for i, (qty, price) in enumerate(lines, start=1):
        EstimateLineItem.objects.create(
            estimate=est, line_number=i, description=f'line {i}',
            qty=Decimal(str(qty)), price=Decimal(str(price)),
        )
    return est


class EstimatedTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()

    def test_uses_compose_agreement_when_ever_approved(self):
        from apps.jobs.financials import compute_job_financials
        job = _job(self.contact, status=Job.STATUS_IN_PROGRESS,
                   start_date=timezone.now())
        # Accepted estimate: 2 lines = 1000; a later draft (ignored by agreement).
        self._accept(_est(job, 1, Estimate.STATUS_ACCEPTED,
                          (1, 600), (1, 400)))
        _est(job, 2, Estimate.STATUS_DRAFT, (1, 9999))
        self.assertEqual(compute_job_financials(job)['estimated'],
                         Decimal('1000.00'))

    def test_compose_agreement_folds_in_accepted_change_order(self):
        from apps.jobs.financials import compute_job_financials
        job = _job(self.contact, status=Job.STATUS_IN_PROGRESS,
                   start_date=timezone.now())
        est = self._accept(_est(job, 1, Estimate.STATUS_ACCEPTED, (1, 1000)))
        co = ChangeOrder.objects.create(job=job, estimate=est)
        ChangeOrder.objects.filter(pk=co.pk).update(
            status=ChangeOrder.STATUS_ACCEPTED, closed_date=timezone.now())
        ChangeOrderLineItem.objects.create(
            change_order=co, line_number=1,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='extra', qty=Decimal('1'), price=Decimal('250'),
        )
        self.assertEqual(compute_job_financials(job)['estimated'],
                         Decimal('1250.00'))

    def test_falls_back_to_highest_version_when_never_approved(self):
        from apps.jobs.financials import compute_job_financials
        job = _job(self.contact, status=Job.STATUS_SUBMITTED)  # start_date None
        _est(job, 1, Estimate.STATUS_SUPERSEDED, (1, 500))
        _est(job, 2, Estimate.STATUS_OPEN, (1, 800))
        self.assertEqual(compute_job_financials(job)['estimated'],
                         Decimal('800.00'))

    def test_zero_when_no_estimates(self):
        from apps.jobs.financials import compute_job_financials
        job = _job(self.contact, status=Job.STATUS_DRAFT)
        self.assertEqual(compute_job_financials(job)['estimated'],
                         Decimal('0.00'))

    def _accept(self, est):
        # Bypass transition guards — set status directly.
        return est


class SpentTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='fin-spent', password='x')
        self.cat = AccountingCategory.objects.create(code='FIN-S', name='fin-s')
        self.job = _job(self.contact)
        # Labor disabled by default (config 0) so material/expense tests isolate.
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '0'})

    def _material(self, qty, cost, state, with_expense=None):
        mat = Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal(str(qty)), unit_cost=Decimal(str(cost)),
            consumption_state=state,
        )
        if with_expense is not None:
            self._expense(with_expense, material=mat)
        return mat

    def _expense(self, amount, material=None, status=Expense.STATUS_SUBMITTED):
        return Expense.objects.create(
            entered_by=self.user, amount=Decimal(str(amount)),
            purchased_on=date.today(), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC',
            job=material.job if material else self.job,
            material=material, status=status,
        )

    def test_includes_material_less_job_expense(self):
        from apps.jobs.financials import compute_job_financials
        self._expense(40)  # material-less, attributed directly to self.job
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('40.00'))

    def test_excludes_overhead_expense(self):
        from apps.jobs.financials import compute_job_financials
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('99.00'),
            purchased_on=date.today(), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC', job=None, material=None,
        )
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('0.00'))

    def test_excludes_stock_receipt_expense(self):
        # A stock-receipt expense (inventoried PLI) is inventory, costed at
        # consumption — its amount is NOT in spent at purchase.
        from apps.jobs.financials import compute_job_financials
        from apps.inventory.models import InventoryItem
        pli = InventoryItem.objects.create(
            code='SR-FIN', description='p', accounting_category=self.cat)
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('100.00'),
            purchased_on=date.today(), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC', job=self.job,
            stock_pli=pli, stock_qty=Decimal('3.00'))
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('0.00'))

    def test_sums_expenses_excluding_rejected(self):
        from apps.jobs.financials import compute_job_financials
        mat = self._material(1, 0, Material.CONSUMPTION_STATE_PENDING)
        self._expense(100, material=mat)
        self._expense(50, material=mat, status=Expense.STATUS_REJECTED)
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('100.00'))

    def test_includes_consumed_nonexpense_material_at_cost(self):
        from apps.jobs.financials import compute_job_financials
        self._material(2, 10, Material.CONSUMPTION_STATE_CONSUMED)  # 20
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('20.00'))

    def test_excludes_pending_material(self):
        from apps.jobs.financials import compute_job_financials
        self._material(5, 10, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('0.00'))

    def test_no_double_count_consumed_material_with_expense(self):
        from apps.jobs.financials import compute_job_financials
        # Consumed material worth 20 at cost, but acquired via a $100 expense:
        # only the expense counts.
        self._material(2, 10, Material.CONSUMPTION_STATE_CONSUMED,
                       with_expense=100)
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('100.00'))

    def test_includes_labor_at_average_cost(self):
        from apps.jobs.financials import compute_job_financials
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '30'})
        scheme = RateScheme.objects.create(
            name='Hr-fin', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=self.cat)
        task = Task(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS)
        task.stamp_from_scheme(scheme)
        task.save()
        start = timezone.now() - timedelta(hours=2)
        Blep.objects.create(task=task, user=self.user,
                            start_time=start, end_time=start + timedelta(hours=2))
        # 2h * $30/h = $60, no materials/expenses.
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('60.00'))

    def test_missing_config_treats_labor_as_zero(self):
        from apps.jobs.financials import compute_job_financials
        Configuration.objects.filter(key='average_labor_cost').delete()
        scheme = RateScheme.objects.create(
            name='Hr-fin2', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=self.cat)
        task = Task(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS)
        task.stamp_from_scheme(scheme)
        task.save()
        start = timezone.now() - timedelta(hours=2)
        Blep.objects.create(task=task, user=self.user,
                            start_time=start, end_time=start + timedelta(hours=2))
        self.assertEqual(compute_job_financials(self.job)['spent'],
                         Decimal('0.00'))


class InvoicedAndProfitTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='fin-inv', password='x')
        self.cat = AccountingCategory.objects.create(code='FIN-I', name='fin-i')
        self.job = _job(self.contact)
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '0'})

    def _invoice(self, status, amount, number):
        inv = Invoice.objects.create(
            job=self.job, invoice_number=number, status=status)
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal(str(amount)))
        return inv

    def test_invoiced_excludes_draft_cancelled_superseded(self):
        from apps.jobs.financials import compute_job_financials
        self._invoice(Invoice.STATUS_OPEN, 1000, 'INV-FIN-1')
        self._invoice(Invoice.STATUS_PAID, 400, 'INV-FIN-2')
        self._invoice(Invoice.STATUS_DRAFT, 500, 'INV-FIN-3')
        self._invoice(Invoice.STATUS_CANCELLED, 300, 'INV-FIN-4')
        self._invoice(Invoice.STATUS_SUPERSEDED, 200, 'INV-FIN-5')
        self.assertEqual(compute_job_financials(self.job)['invoiced'],
                         Decimal('1400.00'))

    def test_profit_is_invoiced_minus_spent(self):
        from apps.jobs.financials import compute_job_financials
        self._invoice(Invoice.STATUS_OPEN, 1000, 'INV-FIN-P1')
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('200'),
            purchased_on=date.today(), accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='ACC', job=self.job,
            material=Material.objects.create(
                job=self.job, accounting_category=self.cat, description='m',
                quantity=Decimal('1'), unit_cost=Decimal('0'),
                consumption_state=Material.CONSUMPTION_STATE_PENDING),
        )
        fin = compute_job_financials(self.job)
        self.assertEqual(fin['spent'], Decimal('200.00'))
        self.assertEqual(fin['profit'], Decimal('800.00'))

    def test_profit_negative_when_spent_without_invoice(self):
        from apps.jobs.financials import compute_job_financials
        Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal('5'), unit_cost=Decimal('10'),
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED)  # 50
        fin = compute_job_financials(self.job)
        self.assertEqual(fin['invoiced'], Decimal('0.00'))
        self.assertEqual(fin['profit'], Decimal('-50.00'))


class LinkedPOVarianceTests(FixtureTestCase):
    """Tests for `linked_po_variances` (task-owned-money Phase 5 Task 4,
    spec §7 rule 7): a job-level rollup of POs linked (via a task on this
    job, or a Material owned by this job) to at least one line, at
    PO-level granularity — no proration. A PO linked to more than one job
    carries the whole PO's numbers on every job it touches, flagged
    `multi_job=True`."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.vendor_contact = Contact.objects.create(
            first_name='PO', last_name='Vendor',
            email='po-vendor@test.com', work_number='555-9999',
        )
        self.vendor = Business.objects.create(
            business_name='PO Vendor Co', business_phone='555-9999',
            default_contact=self.vendor_contact,
        )
        self.cat = AccountingCategory.objects.create(code='FIN-PO', name='fin-po')
        self.job = _job(self.contact)
        self.other_job = _job(self.contact)
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '0'})

    def _issued_po(self):
        return PurchaseOrder.objects.create(
            business=self.vendor, status=PurchaseOrder.STATUS_ISSUED)

    def test_no_linked_pos_is_empty_list(self):
        from apps.jobs.financials import compute_job_financials
        self.assertEqual(
            compute_job_financials(self.job)['linked_po_variances'], [])

    def test_po_linked_via_task_appears_with_ordered_and_bill_totals(self):
        from apps.jobs.financials import compute_job_financials
        task = Task.objects.create(job=self.job, name='Outsourced')
        po = self._issued_po()
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, task=task, accounting_category=self.cat,
            qty=Decimal('2'), price=Decimal('50.00'))
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('120.00'))

        result = compute_job_financials(self.job)['linked_po_variances']
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry['po_id'], po.pk)
        self.assertEqual(entry['po_number'], po.po_number)
        self.assertEqual(entry['ordered_total'], Decimal('100.00'))
        self.assertEqual(entry['bill_total'], Decimal('120.00'))
        self.assertEqual(entry['variance'], Decimal('20.00'))
        self.assertFalse(entry['multi_job'])

    def test_po_linked_via_material_appears(self):
        from apps.jobs.financials import compute_job_financials
        po = self._issued_po()
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po, accounting_category=self.cat,
            qty=Decimal('1'), price=Decimal('30.00'))
        Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal('1'), unit_cost=Decimal('30'),
            consumption_state=Material.CONSUMPTION_STATE_PENDING,
            po_line_item=li,
        )
        result = compute_job_financials(self.job)['linked_po_variances']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['po_id'], po.pk)
        self.assertIsNone(result[0]['bill_total'])
        self.assertIsNone(result[0]['variance'])

    def test_unreconciled_po_variance_is_none(self):
        from apps.jobs.financials import compute_job_financials
        task = Task.objects.create(job=self.job, name='Outsourced')
        po = self._issued_po()
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, task=task, accounting_category=self.cat,
            qty=Decimal('1'), price=Decimal('10.00'))
        result = compute_job_financials(self.job)['linked_po_variances']
        self.assertEqual(result[0]['bill_total'], None)
        self.assertEqual(result[0]['variance'], None)
        self.assertEqual(result[0]['reconciled'], False)

    def test_multi_job_po_appears_on_both_jobs_with_whole_numbers(self):
        from apps.jobs.financials import compute_job_financials
        task_a = Task.objects.create(job=self.job, name='Job A work')
        task_b = Task.objects.create(job=self.other_job, name='Job B work')
        po = self._issued_po()
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, task=task_a, accounting_category=self.cat,
            qty=Decimal('1'), price=Decimal('10.00'))
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, task=task_b, accounting_category=self.cat,
            qty=Decimal('1'), price=Decimal('40.00'))

        result_a = compute_job_financials(self.job)['linked_po_variances']
        result_b = compute_job_financials(self.other_job)['linked_po_variances']
        self.assertEqual(len(result_a), 1)
        self.assertEqual(len(result_b), 1)
        # Whole-PO numbers (both lines), not a per-job slice.
        self.assertEqual(result_a[0]['ordered_total'], Decimal('50.00'))
        self.assertEqual(result_b[0]['ordered_total'], Decimal('50.00'))
        self.assertTrue(result_a[0]['multi_job'])
        self.assertTrue(result_b[0]['multi_job'])

    def test_cancelled_and_invoice_only_lines_ignored_by_task_link(self):
        """invoice_only lines are appended at reconcile time and excluded
        from ordered_total (see PurchaseOrder.ordered_total); the rollup
        just reuses that property, so no separate handling is needed
        here — this pins that behavior at the job-costing surface too."""
        from apps.jobs.financials import compute_job_financials
        task = Task.objects.create(job=self.job, name='Outsourced')
        po = self._issued_po()
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, task=task, accounting_category=self.cat,
            qty=Decimal('1'), price=Decimal('100.00'))
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('150.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1'),
                'price': Decimal('50.00'), 'accounting_category': self.cat.pk,
            }],
        )
        result = compute_job_financials(self.job)['linked_po_variances']
        self.assertEqual(result[0]['ordered_total'], Decimal('100.00'))
        self.assertEqual(result[0]['bill_total'], Decimal('150.00'))
        self.assertEqual(result[0]['variance'], Decimal('50.00'))


class SerializerLinkedPOVarianceTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.job = _job(self.contact)
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '0'})

    def _serialize(self, action):
        from apps.api.jobs.serializers import JobSerializer
        view = type('V', (), {'action': action})()
        return JobSerializer(self.job, context={'view': view}).data

    def test_detail_includes_linked_po_variances(self):
        data = self._serialize('retrieve')
        self.assertIn('linked_po_variances', data)
        self.assertEqual(data['linked_po_variances'], [])

    def test_list_nulls_linked_po_variances(self):
        data = self._serialize('list')
        self.assertIsNone(data['linked_po_variances'])


class SerializerExposureTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.job = _job(self.contact)
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '0'})

    def _serialize(self, action):
        from apps.api.jobs.serializers import JobSerializer
        view = type('V', (), {'action': action})()
        return JobSerializer(self.job, context={'view': view}).data

    def test_detail_includes_financial_fields(self):
        data = self._serialize('retrieve')
        for f in ('estimated_amount', 'spent_amount', 'invoiced_amount',
                  'profit_amount'):
            self.assertIn(f, data)
            self.assertIsInstance(data[f], str)

    def test_list_nulls_financial_fields(self):
        data = self._serialize('list')
        for f in ('estimated_amount', 'spent_amount', 'invoiced_amount',
                  'profit_amount'):
            self.assertIsNone(data[f])
