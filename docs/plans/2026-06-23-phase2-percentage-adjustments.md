# Phase 2 — Percentage Adjustments (rush fees / discounts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `percentage` algorithm to `ServicePrice` so a named, AC-tagged adjustment (rush fee, discount) can be applied to an estimate or invoice as a line whose amount = `percent × Σ(targeted lines)`, scoped by a multi-select of accounting categories, recomputed on demand while the document is a draft and frozen on finalize, and surfaced from the agreement-of-record in the invoice wizard so it's never missed.

**Architecture:** `percentage` is document-only (never backs a Task). Adjustment data lives on the line-item subclasses (`EstimateLineItem` / `InvoiceLineItem`) as a nullable `adjustment_service` FK + `adjustment_target_categories` M2M (spec §5.4 option A). A shared `compute_adjustment_amount` helper does the math. Thin service methods + DRF actions create and recalculate adjustment lines; `compose_agreement` surfaces estimate-origin adjustments for the invoice wizard's "Agreement adjustments" panel. **Depends on Phase 1.**

**Tech Stack:** Django 5.2 / DRF / MySQL; Svelte 5 + Vitest; Django `TestCase` suite.

## Global Constraints

- **NEVER write to the dev DB.** Verify migrations via the test DB + `makemigrations --check --dry-run`. **`makemigrations` (generating) is allowed**; these are additive fields (no interactive rename prompts). (`CLAUDE.md`)
- **One agent runs the Django suite at a time.**
- **macOS `sed`** uses `sed -i ''`.
- Assumes Phase 1 merged: `ServicePrice.rate` is the price for all algorithms; `active_modifiers` is a pure list.
- **Deferred (do NOT build):** live recompute on accepted/sent documents (freeze on finalize only); adjustment-on-adjustment stacking (adjustments never sum other adjustments); CO-borne adjustments (only estimate-origin adjustments are surfaced); AC grouping.
- A line is an **adjustment** iff `adjustment_service_id` is set (and that service's `algorithm == 'percentage'`). The percent value is `adjustment_service.rate` (negative = discount). Empty `adjustment_target_categories` = "all non-adjustment lines".

---

## File Structure

- `apps/jobs/models.py` — `ServicePrice.PERCENTAGE` constant + choice; `clean()` negative-rate rule; defensive guard in `get_actual_qty`/`effective_rate`.
- `apps/core/adjustments.py` — **create**: `compute_adjustment_amount(adjustment_line, sibling_lines) -> Decimal`.
- `apps/estimates/models.py`, `apps/invoicing/models.py` — `adjustment_service` FK + `adjustment_target_categories` M2M on `EstimateLineItem` / `InvoiceLineItem`.
- `apps/estimates/migrations/0027_*`, `apps/invoicing/migrations/0xxx_*` — generated.
- `apps/estimates/services.py`, `apps/invoicing/services.py` — `add_adjustment_line` + `recalculate_adjustment_line`.
- `apps/estimates/agreement.py` — surface `is_adjustment` / `adjustment_service_id` / `percent` / `target_category_ids` on estimate-origin agreement lines.
- `apps/api/estimates/views.py`, `apps/api/invoices/views.py` — `adjustment_lines` (POST), `recalculate` (POST) actions; `agreement_adjustments` (GET) on the invoice viewset.
- `apps/api/{tasks,plan_tasks,templates_config}/serializers.py` — reject a `percentage` service on Task/PlanTask/TaskTemplate.
- `apps/api/service_prices/views.py` — `?task_applicable=true` list filter.
- `apps/core/management/commands/validate_data.py` — percentage-rate-sign rule.
- Frontend: `ServicePriceManager.svelte` (percentage type), estimate + invoice detail pages (Add adjustment + Recalculate), invoice wizard "Agreement adjustments" panel.
- `docs/designs/estimates-and-prices.md`, `invoicing-and-expenses.md`, `data-constraints.md`.

---

## Task 1: Branch

- [ ] **Step 1**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git checkout main && git pull --ff-only
git checkout -b feature/percentage-adjustments
grep -n "def effective_rate" apps/jobs/models.py   # confirm Phase 1 merged (flat-fee returns rate)
```

---

## Task 2: `percentage` algorithm on `ServicePrice`

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_service_price.py`

**Interfaces:**
- Produces: `ServicePrice.PERCENTAGE = 'percentage'`; negative `rate` allowed only for percentage; `get_actual_qty`/`effective_rate` raise if called on a percentage service.

- [ ] **Step 1: Write the failing tests**

```python
def test_percentage_allows_negative_rate(self):
    from apps.jobs.models import ServicePrice
    svc = ServicePrice(
        name='Discount', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('-10.00'), unit_label='%', accounting_category=self.ac,
    )
    svc.full_clean()  # must not raise

def test_non_percentage_rejects_negative_rate(self):
    from django.core.exceptions import ValidationError
    from apps.jobs.models import ServicePrice
    svc = ServicePrice(
        name='Bad', algorithm=ServicePrice.ELAPSED_TIME,
        rate=Decimal('-5.00'), unit_label='hour', accounting_category=self.ac,
    )
    with self.assertRaises(ValidationError):
        svc.full_clean()

def test_get_actual_qty_rejects_percentage(self):
    from apps.jobs.models import ServicePrice
    svc = ServicePrice.objects.create(
        name='Rush', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('15.00'), unit_label='%', accounting_category=self.ac,
    )
    with self.assertRaises(ValueError):
        svc.get_actual_qty(object())
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_service_price -v 2`
Expected: FAIL (`PERCENTAGE` undefined).

- [ ] **Step 3: Implement**

Add the constant and choice:

```python
    ELAPSED_TIME = 'elapsed_time'
    ENTERED_QTY = 'entered_qty'
    FLAT_FEE = 'flat_fee'
    PERCENTAGE = 'percentage'

    ALGORITHM_CHOICES = [
        (ELAPSED_TIME, 'Based on time worked'),
        (ENTERED_QTY, 'Worker enters quantity'),
        (FLAT_FEE, 'Fixed charge'),
        (PERCENTAGE, 'Percentage of other lines'),
    ]
```

In `clean()`, after the AC check, add:

```python
        if self.algorithm != self.PERCENTAGE and self.rate is not None and self.rate < 0:
            from django.core.exceptions import ValidationError
            raise ValidationError({'rate': 'Only percentage services may have a negative rate.'})
```

Guard `get_actual_qty` (top of method) and `effective_rate` (top):

```python
    def get_actual_qty(self, task):
        if self.algorithm == self.PERCENTAGE:
            raise ValueError('percentage services are document adjustments, not task billing')
        ...
```
```python
    def effective_rate(self, active_modifiers=None):
        if self.algorithm == self.PERCENTAGE:
            raise ValueError('percentage services compute at the document layer, not per-unit')
        if self.algorithm == self.FLAT_FEE:
            return self.rate
        ...
```

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_service_price -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/models.py tests/test_service_price.py
git commit -m "feat: add percentage algorithm to ServicePrice (negative rate, guards)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Algorithm applicability — exclude percentage from task surfaces

**Files:**
- Modify: `apps/api/tasks/serializers.py`, `apps/api/plan_tasks/serializers.py`, `apps/api/templates_config/serializers.py`, `apps/api/service_prices/views.py`
- Test: `tests/test_api_tasks.py`, `tests/test_service_price_api.py`

**Interfaces:**
- Produces: assigning a `percentage` service to a Task/PlanTask/TaskTemplate is rejected (400); `GET /api/service-prices/?task_applicable=true` excludes percentage services.

- [ ] **Step 1: Write the failing tests**

In `tests/test_api_tasks.py` (and mirror for plan-tasks/templates):

```python
def test_cannot_assign_percentage_service_to_task(self):
    rush = ServicePrice.objects.create(
        name='Rush', algorithm=ServicePrice.PERCENTAGE, rate=Decimal('15'),
        unit_label='%', accounting_category=self.ac,
    )
    resp = self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {
        'name': 'x', 'service_price': rush.pk, 'est_qty': '1',
    }, content_type='application/json')
    self.assertEqual(resp.status_code, 400)
```

In `tests/test_service_price_api.py`:

```python
def test_task_applicable_filter_excludes_percentage(self):
    ServicePrice.objects.create(name='Rush', algorithm=ServicePrice.PERCENTAGE,
                                rate=Decimal('15'), unit_label='%', accounting_category=self.ac)
    resp = self.client.get('/api/service-prices/?task_applicable=true')
    algos = {r['algorithm'] for r in resp.json()}
    self.assertNotIn('percentage', algos)
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_api_tasks tests.test_service_price_api -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement serializer validation**

In each of the task/plan-task/template serializers, add:

```python
    def validate_service_price(self, value):
        from apps.jobs.models import ServicePrice
        if value and value.algorithm == ServicePrice.PERCENTAGE:
            raise serializers.ValidationError(
                'Percentage services are document adjustments and cannot bill a task.'
            )
        return value
```

In `apps/api/service_prices/views.py` `get_queryset`, honor the filter:

```python
        if self.request.query_params.get('task_applicable') == 'true':
            qs = qs.exclude(algorithm=ServicePrice.PERCENTAGE)
```

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_api_tasks tests.test_service_price_api -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/
git commit -m "feat: percentage services are document-only (excluded from task surfaces)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Adjustment fields on the line-item models

**Files:**
- Modify: `apps/estimates/models.py` (`EstimateLineItem`), `apps/invoicing/models.py` (`InvoiceLineItem`)
- Migrations: generated
- Test: `tests/test_estimate_charge.py` (or a new `tests/test_adjustment_lines.py`)

**Interfaces:**
- Produces: `EstimateLineItem.adjustment_service` / `.adjustment_target_categories`, same on `InvoiceLineItem`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_adjustment_lines.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import ServicePrice


class AdjustmentFieldsTest(TestCase):
    def test_estimate_line_can_hold_adjustment_service(self):
        from apps.estimates.models import EstimateLineItem
        # field presence is the assertion; construction covered in later tasks
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_target_categories'))
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_adjustment_lines -v 2`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Add the fields (identical block on both models)**

On `EstimateLineItem` and `InvoiceLineItem`:

```python
    adjustment_service = models.ForeignKey(
        'jobs.ServicePrice', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+',
        help_text='Set when this line is a percentage adjustment (rush/discount).',
    )
    adjustment_target_categories = models.ManyToManyField(
        'core.AccountingCategory', blank=True, related_name='+',
        help_text='Categories the adjustment applies to; empty = all non-adjustment lines.',
    )
```

- [ ] **Step 4: Generate migrations (allowed; additive, non-interactive)**

```bash
python manage.py makemigrations estimates invoicing
python manage.py makemigrations --check --dry-run   # expect: No changes detected
```

- [ ] **Step 5: Run; expect pass**

Run: `python manage.py test tests.test_adjustment_lines -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/ apps/invoicing/ tests/test_adjustment_lines.py
git commit -m "feat: adjustment_service + target_categories on estimate/invoice line items

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `compute_adjustment_amount` helper

**Files:**
- Create: `apps/core/adjustments.py`
- Test: `tests/test_adjustment_lines.py`

**Interfaces:**
- Produces: `compute_adjustment_amount(adjustment_line, sibling_lines) -> Decimal`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_adjustment_lines.py` (build a minimal estimate with two base lines + an adjustment):

```python
def test_compute_adjustment_all_lines(self):
    from apps.core.adjustments import compute_adjustment_amount
    from apps.estimates.models import Estimate, EstimateLineItem
    # ... create job + draft estimate `est`, AC `labor`, AC `materials`
    EstimateLineItem.objects.create(estimate=est, line_number=1, qty=Decimal('2'),
        price=Decimal('50.00'), accounting_category=self.labor)   # 100
    EstimateLineItem.objects.create(estimate=est, line_number=2, qty=Decimal('1'),
        price=Decimal('40.00'), accounting_category=self.materials)  # 40
    rush = ServicePrice.objects.create(name='Rush', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('15.00'), unit_label='%', accounting_category=self.labor)
    adj = EstimateLineItem.objects.create(estimate=est, line_number=3, qty=Decimal('1'),
        price=Decimal('0.00'), accounting_category=self.labor, adjustment_service=rush)
    siblings = EstimateLineItem.objects.filter(estimate=est).exclude(pk=adj.pk)
    self.assertEqual(compute_adjustment_amount(adj, siblings), Decimal('21.00'))  # 15% of 140

def test_compute_adjustment_category_filtered(self):
    from apps.core.adjustments import compute_adjustment_amount
    # same setup; target only `labor` -> 15% of 100 = 15.00
    adj.adjustment_target_categories.set([self.labor.pk])
    siblings = EstimateLineItem.objects.filter(estimate=est).exclude(pk=adj.pk)
    self.assertEqual(compute_adjustment_amount(adj, siblings), Decimal('15.00'))
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_adjustment_lines -v 2`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# apps/core/adjustments.py
from decimal import Decimal


def compute_adjustment_amount(adjustment_line, sibling_lines):
    """Dollar amount for a percentage adjustment line.

    amount = (service.rate / 100) * sum(total_amount of non-adjustment siblings
    whose accounting_category is in the target set; empty target set = all).
    """
    svc = adjustment_line.adjustment_service
    percent = svc.rate
    target_ids = set(
        adjustment_line.adjustment_target_categories.values_list('pk', flat=True)
    )
    total = Decimal('0.00')
    for line in sibling_lines:
        if getattr(line, 'adjustment_service_id', None):
            continue  # never sum other adjustments (no stacking)
        if target_ids and line.accounting_category_id not in target_ids:
            continue
        total += line.total_amount  # BaseLineItem.total_amount == qty * price
    return (percent / Decimal('100') * total).quantize(Decimal('0.01'))
```

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_adjustment_lines -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/adjustments.py tests/test_adjustment_lines.py
git commit -m "feat: compute_adjustment_amount helper (percent x targeted subtotal)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Estimate service methods + endpoints

**Files:**
- Modify: `apps/estimates/services.py` (`EstimateService`), `apps/api/estimates/views.py`
- Test: `tests/test_estimates_services.py`, `tests/test_api_estimates.py`

**Interfaces:**
- Produces: `EstimateService.add_adjustment_line(estimate, *, adjustment_service_id, target_category_ids=None)`, `EstimateService.recalculate_adjustment_line(line)`; `POST /api/estimates/{id}/adjustment-lines/`, `POST /api/estimates/{id}/line-items/{lid}/recalculate/`.

- [ ] **Step 1: Write the failing service test**

```python
def test_add_and_recalculate_adjustment(self):
    from apps.estimates.services import EstimateService
    # draft estimate `est` with two base lines totaling 140 (as Task 5)
    rush = ServicePrice.objects.create(name='Rush', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('15.00'), unit_label='%', accounting_category=self.labor)
    line = EstimateService.add_adjustment_line(
        est, adjustment_service_id=rush.pk, target_category_ids=[])
    self.assertEqual(line.price, Decimal('21.00'))
    self.assertEqual(line.description, 'Rush')
    self.assertEqual(line.adjustment_service_id, rush.pk)
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_estimates_services -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement service methods**

```python
    @staticmethod
    def add_adjustment_line(estimate, *, adjustment_service_id, target_category_ids=None):
        from django.db.models import Max
        from apps.jobs.models import ServicePrice
        from apps.estimates.models import EstimateLineItem
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Adjustments can only be added to a draft estimate.')
        svc = ServicePrice.objects.get(pk=adjustment_service_id)
        if svc.algorithm != ServicePrice.PERCENTAGE:
            raise ValidationError('Adjustment line requires a percentage service.')
        max_ln = (EstimateLineItem.objects.filter(estimate=estimate)
                  .aggregate(Max('line_number'))['line_number__max'] or 0)
        line = EstimateLineItem.objects.create(
            estimate=estimate, line_number=max_ln + 1, qty=Decimal('1'),
            units=svc.unit_label or 'none', description=svc.name,
            price=Decimal('0.00'), accounting_category=svc.accounting_category,
            adjustment_service=svc,
        )
        if target_category_ids:
            line.adjustment_target_categories.set(target_category_ids)
        return EstimateService.recalculate_adjustment_line(line)

    @staticmethod
    def recalculate_adjustment_line(line):
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem
        estimate = line.estimate
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Cannot recalculate on a non-draft estimate.')
        siblings = EstimateLineItem.objects.filter(estimate=estimate).exclude(pk=line.pk)
        line.price = compute_adjustment_amount(line, siblings)
        line.save()
        return line
```

- [ ] **Step 4: Write the failing API test**

```python
def test_adjustment_line_endpoints(self):
    rush = ServicePrice.objects.create(name='Rush', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('15.00'), unit_label='%', accounting_category=self.labor)
    resp = self.client.post(f'/api/estimates/{self.est.pk}/adjustment-lines/',
        {'adjustment_service': rush.pk, 'target_category_ids': []},
        content_type='application/json')
    self.assertEqual(resp.status_code, 201)
    lid = resp.json()['line_item_id']
    r2 = self.client.post(
        f'/api/estimates/{self.est.pk}/line-items/{lid}/recalculate/',
        content_type='application/json')
    self.assertEqual(r2.status_code, 200)
```

- [ ] **Step 5: Run; expect failure**

Run: `python manage.py test tests.test_api_estimates -v 2`
Expected: FAIL (no such routes).

- [ ] **Step 6: Implement the DRF actions**

On `EstimateViewSet` (mirror the existing line-item action style; permissions `IsAuthenticated, CanManageJobs`):

```python
    @action(detail=True, methods=['post'], url_path='adjustment-lines')
    def adjustment_lines(self, request, pk=None):
        estimate = self.get_object()
        line = EstimateService.add_adjustment_line(
            estimate,
            adjustment_service_id=request.data['adjustment_service'],
            target_category_ids=request.data.get('target_category_ids') or [],
        )
        return Response(EstimateLineItemSerializer(line).data, status=201)

    @action(detail=True, methods=['post'],
            url_path=r'line-items/(?P<lid>[^/.]+)/recalculate')
    def recalculate(self, request, pk=None, lid=None):
        estimate = self.get_object()
        line = EstimateLineItem.objects.get(pk=lid, estimate=estimate)
        EstimateService.recalculate_adjustment_line(line)
        return Response(EstimateLineItemSerializer(line).data, status=200)
```

Ensure `EstimateLineItemSerializer` exposes `adjustment_service`, `adjustment_target_categories`, and the existing `line_item_id`.

- [ ] **Step 7: Run; expect pass**

Run: `python manage.py test tests.test_estimates_services tests.test_api_estimates -v 2`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/estimates/ apps/api/estimates/ tests/
git commit -m "feat: estimate adjustment-line add + recalculate (draft-only)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Invoice service methods + endpoints + agreement surfacing

**Files:**
- Modify: `apps/invoicing/services.py` (`InvoiceService`), `apps/api/invoices/views.py`, `apps/estimates/agreement.py`
- Test: `tests/test_invoicing_models.py` / `tests/test_invoice_wizard_api.py`, `tests/test_api_invoicing.py`

**Interfaces:**
- Produces: `InvoiceService.add_adjustment_line` / `.recalculate_adjustment_line` (Invoice-draft-gated); `POST /api/invoices/{id}/adjustment-lines/`, `POST /api/invoices/{id}/line-items/{lid}/recalculate/`, `GET /api/invoices/{id}/agreement-adjustments/`. `compose_agreement` lines gain `is_adjustment`, `adjustment_service_id`, `percent`, `target_category_ids`.

- [ ] **Step 1: Surface adjustments on agreement lines — failing test**

In `tests/test_api_invoicing.py` (or an agreement test):

```python
def test_compose_agreement_marks_adjustment_lines(self):
    from apps.estimates.agreement import compose_agreement
    # accepted estimate with one base line + one adjustment line
    result = compose_agreement(self.job)
    adj = [l for l in result['lines'] if l.get('is_adjustment')]
    self.assertEqual(len(adj), 1)
    self.assertIn('adjustment_service_id', adj[0])
    self.assertIn('percent', adj[0])
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_api_invoicing -v 2`
Expected: FAIL.

- [ ] **Step 3: Extend `compose_agreement`**

Where the estimate `EstimateLineItem` is turned into a line dict, add:

```python
        'is_adjustment': li.adjustment_service_id is not None,
        'adjustment_service_id': li.adjustment_service_id,
        'percent': (li.adjustment_service.rate if li.adjustment_service_id else None),
        'target_category_ids': (
            list(li.adjustment_target_categories.values_list('pk', flat=True))
            if li.adjustment_service_id else []
        ),
```

(CO-origin lines keep `is_adjustment` falsey — CO adjustments are out of scope.)

- [ ] **Step 4: Implement Invoice service methods (mirror Task 6, gating on Invoice draft)**

```python
    @staticmethod
    def add_adjustment_line(invoice, *, adjustment_service_id, target_category_ids=None):
        from django.db.models import Max
        from apps.jobs.models import ServicePrice
        from apps.invoicing.models import InvoiceLineItem
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Adjustments can only be added to a draft invoice.')
        svc = ServicePrice.objects.get(pk=adjustment_service_id)
        if svc.algorithm != ServicePrice.PERCENTAGE:
            raise ValidationError('Adjustment line requires a percentage service.')
        max_ln = (InvoiceLineItem.objects.filter(invoice=invoice)
                  .aggregate(Max('line_number'))['line_number__max'] or 0)
        line = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=max_ln + 1, qty=Decimal('1'),
            units=svc.unit_label or 'none', description=svc.name,
            price=Decimal('0.00'), accounting_category=svc.accounting_category,
            adjustment_service=svc,
        )
        if target_category_ids:
            line.adjustment_target_categories.set(target_category_ids)
        return InvoiceService.recalculate_adjustment_line(line)

    @staticmethod
    def recalculate_adjustment_line(line):
        from apps.core.adjustments import compute_adjustment_amount
        from apps.invoicing.models import InvoiceLineItem
        invoice = line.invoice
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Cannot recalculate on a non-draft invoice.')
        siblings = InvoiceLineItem.objects.filter(invoice=invoice).exclude(pk=line.pk)
        line.price = compute_adjustment_amount(line, siblings)
        line.save()
        return line
```

- [ ] **Step 5: Implement Invoice DRF actions (permissions `IsAuthenticated, CanManageFinancials`)**

`adjustment_lines` (POST) and `recalculate` (POST) mirror Task 6 Step 6, plus:

```python
    @action(detail=True, methods=['get'], url_path='agreement-adjustments')
    def agreement_adjustments(self, request, pk=None):
        from apps.estimates.agreement import compose_agreement
        from apps.invoicing.models import InvoiceLineItem
        invoice = self.get_object()
        agreement = compose_agreement(invoice.job)
        existing = set(
            InvoiceLineItem.objects
            .filter(invoice=invoice, adjustment_service__isnull=False)
            .values_list('adjustment_service_id', flat=True)
        )
        out = [
            {
                'adjustment_service_id': l['adjustment_service_id'],
                'description': l['description'],
                'percent': l['percent'],
                'target_category_ids': l['target_category_ids'],
                'already_added': l['adjustment_service_id'] in existing,
            }
            for l in agreement['lines'] if l.get('is_adjustment')
        ]
        return Response({'adjustments': out})
```

- [ ] **Step 6: Write + run the invoice API tests**

Add tests mirroring Task 6 Step 4 for `/api/invoices/...` plus an `agreement-adjustments` test asserting `already_added` flips after adding. Run:
`python manage.py test tests.test_api_invoicing tests.test_invoice_wizard_api -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/ apps/api/invoices/ apps/estimates/agreement.py tests/
git commit -m "feat: invoice adjustment lines + agreement-adjustments surfacing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `validate_data` percentage rule

**Files:**
- Modify: `apps/core/management/commands/validate_data.py`
- Test: `tests/test_validate_data.py`

- [ ] **Step 1: Failing test** — a non-percentage service with negative rate is flagged; a percentage service with negative rate is not.

```python
def test_negative_rate_only_allowed_for_percentage(self):
    ac = AccountingCategory.objects.create(name='S', code='S2')
    ServicePrice.objects.create(name='disc', algorithm=ServicePrice.PERCENTAGE,
        rate=Decimal('-10'), unit_label='%', accounting_category=ac)  # OK
    out = StringIO(); call_command('validate_data', stdout=out, stderr=out)
    self.assertNotIn('disc', out.getvalue())
```

- [ ] **Step 2: Run; expect** the test passes only if the check correctly skips percentage. If `check_service_prices` has no rate-sign rule yet, add:

```python
            if rs.algorithm != ServicePrice.PERCENTAGE and rs.rate is not None and rs.rate < 0:
                self.errors.append(f'ServicePrice {rs.pk} ({rs.name}): negative rate not allowed for {rs.algorithm}')
```

- [ ] **Step 3: Run; expect pass.** `python manage.py test tests.test_validate_data -v 2`

- [ ] **Step 4: Commit**

```bash
git add apps/core/management/commands/validate_data.py tests/test_validate_data.py
git commit -m "feat: validate_data enforces negative-rate-only-for-percentage

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Frontend — percentage type in the Services manager

**Files:**
- Modify: `frontend/src/components/ServicePriceManager.svelte`
- Test: `frontend/tests/components/ServicePriceManager.test.js`

- [ ] **Step 1: Failing test** — selecting algorithm "Percentage of other lines" shows a single percent field (negative allowed), an AC selector, and **no** modifier menu.

- [ ] **Step 2: Run; expect failure.** `cd frontend && npm run test:run`

- [ ] **Step 3: Implement** — add the `percentage` option to the algorithm select; when chosen, render only the percent (`rate`) input (allow negatives) + AC; hide the modifier editor and unit/qty fields not relevant to percentage.

- [ ] **Step 4: Run + build; expect pass.** `npm run test:run && npm run build`

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: Services manager supports percentage adjustments

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Frontend — Add adjustment + Recalculate on estimate & invoice detail

**Files:**
- Modify: estimate detail (`frontend/src/routes/estimates/EstimateDetailPage.svelte` + `LineItemTable.svelte`), invoice detail page, shared adjustment modal (new `frontend/src/components/AdjustmentModal.svelte`)
- Test: matching component tests

- [ ] **Step 1: Failing tests** — on a draft estimate/invoice, an "Add adjustment" control opens a modal that picks a `percentage` service (`GET /api/service-prices/` filtered to percentage) and multi-selects target accounting categories (empty allowed); submitting POSTs to `…/adjustment-lines/`. An adjustment row renders a **Recalculate** button only while the document is a draft; clicking POSTs `…/recalculate/`. On a non-draft document neither control renders.

- [ ] **Step 2: Run; expect failure.** `cd frontend && npm run test:run`

- [ ] **Step 3: Implement**

- New `AdjustmentModal.svelte`: percentage-service picker + AC multi-select (reuse the AccountingCategory options source) + submit.
- In `LineItemTable.svelte` (or the detail pages): render adjustment rows distinctly (e.g. badge "+15% rush on Labor" using the service percent + target categories), with a Recalculate button gated on `canEdit` (draft + permission).
- Wire the two POSTs through `lib/api.js`.

- [ ] **Step 4: Run + build; expect pass.**

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add/recalculate percentage adjustments on estimate & invoice

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Frontend — invoice wizard "Agreement adjustments" panel

**Files:**
- Modify: invoice wizard page (`frontend/src/routes/invoices/` wizard) + a new `frontend/src/components/invoices/AgreementAdjustmentsPanel.svelte`
- Test: component test

- [ ] **Step 1: Failing test** — the wizard renders an "Agreement adjustments" panel populated from `GET /api/invoices/{id}/agreement-adjustments/`; each entry shows description + percent and an **Add** button; entries with `already_added: true` render as added/disabled; clicking Add POSTs `…/adjustment-lines/` with the entry's `adjustment_service_id` + `target_category_ids`, then refreshes so the entry flips to added.

- [ ] **Step 2: Run; expect failure.** `cd frontend && npm run test:run`

- [ ] **Step 3: Implement** the panel + wire it into the invoice wizard page near the line-items column. Reuse the adjustment-line POST from Task 10.

- [ ] **Step 4: Run + build; expect pass.**

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: invoice wizard surfaces agreement percentage adjustments

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Docs + final gate

**Files:**
- Modify: `docs/designs/estimates-and-prices.md`, `docs/designs/invoicing-and-expenses.md`, `docs/designs/data-constraints.md`

- [ ] **Step 1: Document** the `percentage` algorithm, document-only applicability (§3.3 of the spec), adjustment line fields, the `compute_adjustment_amount` rule, the add/recalculate endpoints + freeze, and the invoice-wizard agreement-adjustments panel. In `data-constraints.md` add the negative-rate-only-for-percentage rule and the adjustment-line fields.

- [ ] **Step 2: Full gate**

```bash
cd /Users/drshiny/Documents/konbini/Minibini && python manage.py test
cd frontend && npm run test:run && npm run build
```
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: percentage adjustments (model, endpoints, wizard panel)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (parent §4, §5.1/§5.4, §6, §7, §3.3):**
- `percentage` algorithm + negative rate + guards → Task 2. ✓
- document-only applicability → Task 3. ✓
- adjustment fields (option A) → Task 4. ✓
- `compute_adjustment_amount` (category filter, empty=all, no stacking) → Task 5. ✓
- estimate add/recalculate + freeze (draft-gate) → Task 6. ✓
- invoice add/recalculate + agreement surfacing (path-independent via `compose_agreement`) → Task 7. ✓
- validator rule → Task 8. ✓
- Services-manager percentage type → Task 9. ✓
- add/recalculate UI → Task 10. ✓
- wizard agreement-adjustments panel (not atom pool) → Task 11. ✓
- docs → Task 12. ✓
- deferred items (live recompute on finalized, stacking, CO adjustments, AC grouping) honored: recalculate gated on draft; adjustments excluded from sums; only estimate-origin agreement lines surfaced. ✓

**Placeholder scan:** backend logic (model, helper, services, actions, agreement) is shown in full. Frontend tasks (9–11) specify exact files, the API calls, and the rendered behavior but defer to existing component patterns for markup — acceptable per the skill's "follow established patterns" guidance for an existing SPA.

**Type/name consistency:** `adjustment_service`, `adjustment_target_categories`, `compute_adjustment_amount`, `add_adjustment_line`, `recalculate_adjustment_line`, `agreement_adjustments`, `is_adjustment`, `already_added`, `task_applicable` used consistently across backend and frontend tasks.

---

## Execution Handoff

Plan saved to `docs/plans/2026-06-23-phase2-percentage-adjustments.md`. This is the final phase. Execution options: subagent-driven (recommended) or inline.
</content>
