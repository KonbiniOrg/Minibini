"""
Job financial rollups — the single source of truth for the four numbers shown
in the job-detail header (Estimate / Spent / Invoiced / Profit) and the
job-board card profitability figures.

`compute_job_financials(job)` is a pure, read-only aggregation across estimates,
inventory, expenses, invoicing, and bleps. No DB writes. Like ScheduleService it
lives under ``apps/jobs/`` but reads from several apps.

See docs/plans/2026-06-11-job-financials-header-design.md.
"""
from decimal import Decimal, InvalidOperation

from django.db import models

from apps.estimates.agreement import compose_agreement

CENTS = Decimal('0.01')
SECONDS_PER_HOUR = Decimal('3600')


def _estimated(job):
    """Agreement-of-record when the job was ever approved, else best guess.

    ``job.start_date`` is the immutable "ever reached Approved / an estimate was
    once accepted" marker (set on first transition to Approved, never cleared;
    the accepted estimate keeps its accepted status even after reject/cancel). If
    that marker is set, use compose_agreement (accepted estimate + accepted-CO
    deltas). Otherwise fall back to the highest-version estimate's line total.

    NOTE: this branch keys off ``Job.start_date``. If start_date is ever made
    clearable/editable, revisit this — see the design doc and data-constraints.
    """
    from apps.estimates.models import EstimateLineItem

    if job.start_date is not None:
        return compose_agreement(job)['grand_total']

    latest = job.estimate_set.order_by('-version', '-pk').first()
    if latest is None:
        return Decimal('0')
    total = EstimateLineItem.objects.filter(estimate=latest).aggregate(
        total=models.Sum(models.F('qty') * models.F('price'))
    )['total']
    return total or Decimal('0')


def _average_labor_cost():
    """The configured average labor cost in dollars per hour.

    Returns Decimal('0') when the ``average_labor_cost`` Configuration key is
    missing or blank, so labor contributes nothing until an operator sets it.
    """
    from apps.core.models import Configuration

    try:
        raw = Configuration.objects.get(key='average_labor_cost').value
    except Configuration.DoesNotExist:
        return Decimal('0')
    raw = (raw or '').strip()
    if not raw:
        return Decimal('0')
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal('0')


def _labor_cost(job):
    """Approximate labor cost = all blep hours on the job × average_labor_cost.

    Labor cost is about hours worked, not how the task is billed, so every blep
    counts regardless of the task's RateScheme or status (cancelled-task hours
    were still worked). A running blep counts its time so far via Blep.elapsed.
    """
    from apps.jobs.models import Blep

    rate = _average_labor_cost()
    if rate == 0:
        return Decimal('0')

    total_hours = Decimal('0')
    bleps = Blep.objects.filter(task__job=job, start_time__isnull=False)
    for blep in bleps:
        elapsed = blep.elapsed
        if elapsed is None:
            continue
        total_hours += Decimal(str(elapsed.total_seconds())) / SECONDS_PER_HOUR
    return total_hours * rate


def _spent(job):
    """Cash outlay + approximate labor.

    = expenses billed to the job (excluding rejected)
    + consumed materials with no linked expense, at cost (quantity × unit_cost)
    + labor cost.

    A material acquired via an expense is represented by that expense; counting
    its cost too would double-count, so consumed materials that have any expense
    are excluded from the materials term.
    """
    from apps.expenses.models import Expense
    from apps.inventory.models import Material

    expenses_total = Expense.objects.filter(
        material__job=job,
    ).exclude(
        status=Expense.STATUS_REJECTED,
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')

    consumed_no_expense = Material.objects.filter(
        job=job, consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
    ).exclude(expenses__isnull=False)
    materials_total = sum(
        (m.quantity * m.unit_cost for m in consumed_no_expense),
        Decimal('0'),
    )

    return expenses_total + materials_total + _labor_cost(job)


def _invoiced(job):
    """Sum of (qty × price) across the job's invoice line items, excluding
    draft / cancelled / superseded invoices."""
    from apps.invoicing.models import Invoice, InvoiceLineItem

    total = InvoiceLineItem.objects.filter(
        invoice__job=job,
    ).exclude(
        invoice__status__in=[
            Invoice.STATUS_DRAFT,
            Invoice.STATUS_CANCELLED,
            Invoice.STATUS_SUPERSEDED,
        ],
    ).aggregate(
        total=models.Sum(models.F('qty') * models.F('price'))
    )['total']
    return total or Decimal('0')


def compute_job_financials(job):
    """Return the job's financial rollups, each quantized to cents.

    {'estimated', 'spent', 'invoiced', 'profit'} — all Decimal.
    Profit = invoiced − spent (intentionally negative for work done but not yet
    billed).
    """
    estimated = _estimated(job)
    spent = _spent(job)
    invoiced = _invoiced(job)
    profit = invoiced - spent
    return {
        'estimated': estimated.quantize(CENTS),
        'spent': spent.quantize(CENTS),
        'invoiced': invoiced.quantize(CENTS),
        'profit': profit.quantize(CENTS),
    }
