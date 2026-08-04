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
from apps.core.timeutils import timedelta_to_hours

CENTS = Decimal('0.01')


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


def _blep_hours(job):
    """Total worked hours across all bleps on the job.

    Every blep counts regardless of the task's RateScheme or status
    (cancelled-task hours were still worked). A running blep counts its time
    so far via Blep.elapsed. `spend_breakdown` uses this single hours figure
    for both its `labor` ($) and `labor_hours` terms, so the two can never
    disagree.
    """
    from apps.jobs.models import Blep

    total_hours = Decimal('0')
    bleps = Blep.objects.filter(task__job=job, start_time__isnull=False)
    for blep in bleps:
        elapsed = blep.elapsed
        if elapsed is None:
            continue
        total_hours += timedelta_to_hours(elapsed)
    return total_hours


def spend_breakdown(job):
    """The job's spend, split into labor vs. cash-outlay materials.

    Returns {'labor', 'labor_hours', 'materials_bought', 'total'}, all Decimal,
    money terms quantized to cents.

    - materials_bought = non-rejected, non-stock-receipt expenses attributed to
      the job (Expense.job), by amount — covers material-bearing and
      material-less cost expenses (e.g. a shipping fee); overhead (Expense.job
      null) is excluded, and **stock-receipt expenses are excluded** (an
      inventoried-PLI purchase is inventory, costed at consumption, not at
      purchase) + consumed materials with no linked expense, at cost (quantity
      × unit_cost) — this is where inventoried stock cost lands. A material
      acquired via a cost-expense is represented by that expense; counting its
      cost too would double-count, so consumed materials that have any expense
      are excluded from this term.
    - labor = all blep hours on the job × average_labor_cost (0 when the
      Configuration key is missing/blank).
    - labor_hours = the raw hours figure `labor` rates, unquantized.
    - total = materials_bought + labor — this IS `_spent(job)`, by
      construction, so the two can never drift apart.
    """
    from apps.expenses.models import Expense
    from apps.inventory.models import Material

    expenses_total = Expense.objects.filter(
        job=job,
    ).exclude(
        status=Expense.STATUS_REJECTED,
    ).exclude(
        stock_pli__isnull=False,   # stock receipts cost at consumption, not here
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')

    consumed_no_expense = Material.objects.filter(
        job=job, consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
    ).exclude(expenses__isnull=False)
    materials_total = sum(
        (m.quantity * m.unit_cost for m in consumed_no_expense),
        Decimal('0'),
    )
    materials_bought = expenses_total + materials_total

    labor_hours = _blep_hours(job)
    labor = labor_hours * _average_labor_cost()

    # Quantize parts first, then derive total as their sum.
    # This ensures the displayed parts always sum to the displayed total,
    # avoiding round-then-sum vs sum-then-round discrepancies (common with
    # fractional-hour bleps and material calculations that produce sub-cent values).
    labor_q = labor.quantize(CENTS)
    materials_bought_q = materials_bought.quantize(CENTS)

    return {
        'labor': labor_q,
        'labor_hours': labor_hours,
        'materials_bought': materials_bought_q,
        'total': materials_bought_q + labor_q,
    }


def _spent(job):
    """Cash outlay + approximate labor — see `spend_breakdown` for the terms."""
    return spend_breakdown(job)['total']


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


def _linked_po_variances(job):
    """Job-level rollup of PO cost variance (task-owned-money Phase 5 Task 4,
    spec §7 rule 7): every PO with at least one line linked to this job —
    either directly via `PurchaseOrderLineItem.task` on one of the job's
    tasks, or indirectly via a `Material` this job owns that references the
    PO line item — reported at PO GRANULARITY. No proration: a PO whose
    lines also serve other jobs (through other lines/materials) appears with
    its WHOLE ordered/bill numbers on every job it touches, flagged
    `multi_job=True` so the UI can signal "this isn't fully yours".

    Returns a list of
    {'po_id', 'po_number', 'status', 'reconciled', 'ordered_total',
     'bill_total', 'variance', 'multi_job'}, money fields quantized to
    cents (None where the PO has no `bill_total` yet — nothing to vary
    against, mirroring `PurchaseOrder.variance`).
    """
    from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
    from apps.inventory.models import Material

    po_ids = set(
        PurchaseOrderLineItem.objects.filter(task__job=job)
        .values_list('purchase_order_id', flat=True)
    )
    po_ids |= set(
        Material.objects.filter(job=job, po_line_item__isnull=False)
        .values_list('po_line_item__purchase_order_id', flat=True)
    )
    if not po_ids:
        return []

    results = []
    for po in PurchaseOrder.objects.filter(pk__in=po_ids).order_by('po_number'):
        linked_job_ids = set(
            PurchaseOrderLineItem.objects
            .filter(purchase_order=po, task__isnull=False)
            .values_list('task__job_id', flat=True)
        )
        linked_job_ids |= set(
            Material.objects.filter(po_line_item__purchase_order=po)
            .values_list('job_id', flat=True)
        )
        multi_job = bool(linked_job_ids - {job.pk})

        variance = po.variance
        results.append({
            'po_id': po.pk,
            'po_number': po.po_number,
            'status': po.status,
            'reconciled': po.reconciled,
            'ordered_total': po.ordered_total.quantize(CENTS),
            'bill_total': (
                None if po.bill_total is None else po.bill_total.quantize(CENTS)
            ),
            'variance': None if variance is None else variance.quantize(CENTS),
            'multi_job': multi_job,
        })
    return results


def compute_job_financials(job):
    """Return the job's financial rollups, each quantized to cents.

    {'estimated', 'spent', 'invoiced', 'profit', 'linked_po_variances'}.
    The first four are Decimal. Profit = invoiced − spent (intentionally
    negative for work done but not yet billed). `linked_po_variances` is a
    list — see `_linked_po_variances` — of the job's linked-PO cost variance
    at PO granularity (task-owned-money Phase 5 Task 4, spec §7 rule 7).
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
        'linked_po_variances': _linked_po_variances(job),
    }
