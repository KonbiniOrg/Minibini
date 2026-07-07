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
from apps.expenses.models import Expense
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Blep, Job, RateScheme, Task


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
            rate=Decimal('50'), unit_label='hours', accounting_category=self.cat)
        task = Task.objects.create(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS,
            rate_scheme=scheme)
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
            rate=Decimal('50'), unit_label='hours', accounting_category=self.cat)
        task = Task.objects.create(
            job=self.job, name='t', status=Task.STATUS_IN_PROGRESS,
            rate_scheme=scheme)
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
