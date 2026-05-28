# Plan 2 — Change Orders + `on_hold` + Deliverable Versioning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. TDD throughout. Checkbox (`- [ ]`) steps.

**Goal:** Post-acceptance amendments to the agreed estimate, customer-approved like an estimate, plus the `on_hold` Job pause they require and the deliverable snapshot/anchoring/editability model that lets a CO amend deliverables safely.

**Architecture:** A new `ChangeOrder` model mirrors `Estimate` (status machine, dates, per-estimate-derived number, parent-seed lineage) with `ChangeOrderLineItem(BaseLineItem)` carrying add/remove/replace deltas against `EstimateLineItem`s. A new `on_hold` Job status freezes work purely as a status query-filter (no task mutation). A new `DeliverableSnapshot` captures the agreed deliverable scope per document; the live `Deliverable` list is edited in place during a CO draft, anchored once shipped. CO acceptance auto-advances the Job `on_hold → approved`; rejection changes nothing. A `mark_change_orders_expired` command mirrors `mark_estimates_expired` and reuses the `est_expire_days` config.

**Authoritative specs:** `docs/plans/2026-05-25-change-orders-spec.md` (CO + on_hold) and `docs/plans/2026-05-25-deliverables-spec.md` (snapshots/anchoring/editability).

**Repo:** `/Users/drshiny/Documents/konbini/Minibini`, branch `feature/change-orders`. Commit per task.

**DB safety (CLAUDE.md):** `makemigrations` is allowed (writes migration files, no DB touch). NEVER `migrate`/`shell`/`loaddata`/ORM-writes against the dev DB. `python manage.py test` is fine (separate test DB). One test run at a time across all agents (the subagent-driven flow dispatches one implementer at a time — keep it that way). Add any new Configuration keys to `fixtures/unit_test_data.json` and test `setUp` where needed.

**App placement decision:** put `ChangeOrder`/`ChangeOrderLineItem` in **`apps/estimates/`** (next to `Estimate`/`EstimateLineItem`, reusing the history decorator, `BaseLineItem`, and proximity to estimate code). `DeliverableSnapshot` goes in **`apps/deliverables/`**.

---

## Phase A — Models & migrations

### Task A1: `ChangeOrder` model

**Files:**
- Modify: `apps/estimates/models.py` (add `ChangeOrder` after `Estimate`, before `EstWorksheet`)
- Test: `tests/test_change_order_model.py` (new)

The model mirrors `Estimate` (see `apps/estimates/models.py:9-217`). Status machine and transitions from the CO spec §3.2 (rejected is terminal; superseded = withdrawn open offer; no in-place revision). Number is `{estimate.estimate_number}-CO{n}` assigned at create, `unique`.

- [ ] **Step 1: Write the failing test** `tests/test_change_order_model.py`:

```python
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.estimates.models import Estimate, EstimateLineItem, ChangeOrder
from apps.jobs.models import Job


class ChangeOrderModelTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_create_defaults_to_draft(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertEqual(co.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(co.version, 1)

    def test_number_derives_from_estimate_with_co_ordinal(self):
        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        co2 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertEqual(co1.change_order_number, 'EST-CO-1-CO1')
        self.assertEqual(co2.change_order_number, 'EST-CO-1-CO2')

    def test_draft_to_open_requires_line_item(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        co.status = ChangeOrder.STATUS_OPEN
        with self.assertRaises(ValidationError):
            co.save()

    def test_open_sets_sent_and_expiration(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        EstimateLineItem.objects.create(estimate=self.est, description='x', qty=1, price=1, line_number=1)
        ChangeOrderLineItemFactory(co)  # helper defined below
        co.status = ChangeOrder.STATUS_OPEN
        co.save()
        self.assertIsNotNone(co.sent_date)
        self.assertIsNotNone(co.expiration_date)

    def test_rejected_is_terminal(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est, status=ChangeOrder.STATUS_DRAFT)
        ChangeOrderLineItemFactory(co)
        co.status = ChangeOrder.STATUS_OPEN; co.save()
        co.status = ChangeOrder.STATUS_REJECTED; co.save()
        co.status = ChangeOrder.STATUS_DRAFT
        with self.assertRaises(ValidationError):
            co.save()


def ChangeOrderLineItemFactory(co):
    from apps.estimates.models import ChangeOrderLineItem
    return ChangeOrderLineItem.objects.create(
        change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        description='Added scope', qty=1, price=100, line_number=1,
    )
```

- [ ] **Step 2: Run, expect ImportError/AttributeError** (`ChangeOrder` undefined).
  `python manage.py test tests.test_change_order_model`

- [ ] **Step 3: Implement `ChangeOrder`** in `apps/estimates/models.py`:

```python
@history(exclude=['change_order_id'])
class ChangeOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_OPEN = 'open'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_EXPIRED = 'expired'
    STATUS_SUPERSEDED = 'superseded'

    CO_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_OPEN, 'Open'), (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_REJECTED, 'Rejected'), (STATUS_EXPIRED, 'Expired'), (STATUS_SUPERSEDED, 'Superseded'),
    ]

    change_order_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='change_orders')
    estimate = models.ForeignKey(Estimate, on_delete=models.PROTECT, related_name='change_orders')
    change_order_number = models.CharField(max_length=80, unique=True, blank=True)
    version = models.IntegerField(default=1)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    status = models.CharField(max_length=20, choices=CO_STATUS_CHOICES, default=STATUS_DRAFT)
    created_date = models.DateTimeField(default=timezone.now)
    sent_date = models.DateTimeField(null=True, blank=True)
    closed_date = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    VALID_TRANSITIONS = {
        STATUS_DRAFT: [STATUS_OPEN, STATUS_REJECTED],
        STATUS_OPEN: [STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SUPERSEDED, STATUS_EXPIRED],
        STATUS_ACCEPTED: [], STATUS_REJECTED: [], STATUS_EXPIRED: [], STATUS_SUPERSEDED: [],
    }

    class Meta:
        db_table = 'change_orders'

    def clean(self):
        super().clean()
        if self.pk:
            old = ChangeOrder.objects.get(pk=self.pk)
            for f in ('created_date', 'sent_date', 'closed_date'):
                if getattr(old, f) and getattr(self, f) != getattr(old, f):
                    setattr(self, f, getattr(old, f))
            if old.status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old.status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        f'Cannot transition ChangeOrder from {old.status} to {self.status}.'
                    )
                if old.status == self.STATUS_DRAFT:
                    if not ChangeOrderLineItem.objects.filter(change_order=self).exists():
                        raise ValidationError('Cannot send a change order with no line items.')

    def save(self, *args, **kwargs):
        from apps.core.models import Configuration
        from datetime import timedelta
        old_status = None
        if self.pk:
            old_status = ChangeOrder.objects.get(pk=self.pk).status
            if old_status != self.status:
                if self.status == self.STATUS_OPEN and not self.sent_date:
                    self.sent_date = timezone.now()
                    if not self.expiration_date:
                        try:
                            days = int(Configuration.objects.get(key='est_expire_days').value)
                        except (Configuration.DoesNotExist, ValueError):
                            days = 30
                        self.expiration_date = timezone.now() + timedelta(days=days)
                if self.status in (self.STATUS_ACCEPTED, self.STATUS_REJECTED,
                                   self.STATUS_SUPERSEDED, self.STATUS_EXPIRED) and not self.closed_date:
                    self.closed_date = timezone.now()
        if not self.change_order_number:
            n = ChangeOrder.objects.filter(estimate=self.estimate).count() + 1
            self.change_order_number = f'{self.estimate.estimate_number}-CO{n}'
        self.full_clean()
        super().save(*args, **kwargs)
        if old_status and old_status != self.status:
            self._maybe_signal(old_status)

    def _maybe_signal(self, old_status):
        from apps.estimates.signals import change_order_accepted
        if self.status == self.STATUS_ACCEPTED and old_status != self.STATUS_ACCEPTED:
            change_order_accepted.send(sender=self.__class__, change_order=self)

    def __str__(self):
        return self.change_order_number or f'ChangeOrder {self.pk}'
```

Note: `full_clean()` in `save()` runs `clean()`; the number is assigned before `full_clean` so `unique` validates. The `change_order_accepted` signal is defined in Task D2.

- [ ] **Step 4: Run the test, expect PASS** (the `test_open_sets_...` test also needs `ChangeOrderLineItem` from Task A2; if A2 isn't done yet, split: run only `test_create_defaults_to_draft`, `test_number_derives_...`, `test_draft_to_open_requires_line_item` now; the rest after A2). Run `makemigrations estimates` first if the test DB complains about a missing table:
  `python manage.py makemigrations estimates`
  `python manage.py test tests.test_change_order_model`

- [ ] **Step 5: Commit** (`git add apps/estimates/models.py apps/estimates/migrations/ tests/test_change_order_model.py` + message "Add ChangeOrder model" with the Co-Authored-By trailer).

### Task A2: `ChangeOrderLineItem`

**Files:** Modify `apps/estimates/models.py`; Test: extend `tests/test_change_order_model.py`.

Inherits `BaseLineItem` (read `apps/core/models.py:200+` for its fields — description, qty, units, price, line_number, accounting_category, taxable_override, tax_rate_override). Adds `change_order` FK (CASCADE), `action` (`add`/`remove`/`replace`), `target_line_item` FK→`EstimateLineItem` (PROTECT, null), `source_template` FK→`TaskTemplate` (SET_NULL, null), `price_list_item` FK→`PriceListItem` (SET_NULL, null). Implement `get_parent_field_name()` returning `'change_order'`.

- [ ] Step 1: failing test — `clean()` rejects `remove`/`replace` with no `target_line_item`, and `add` with a `target_line_item`.
- [ ] Step 2: run, fail.
- [ ] Step 3: implement model + `clean()` rule (action vs target consistency). `db_table='co_li'`.
- [ ] Step 4: `makemigrations estimates`; run tests; PASS.
- [ ] Step 5: commit.

### Task A3: `DeliverableSnapshot` model

**Files:** Modify `apps/deliverables/models.py`; Test: `tests/test_deliverable_snapshot_model.py` (new).

Per deliverables spec §3.2: write-once frozen rows. Fields: `estimate` FK (CASCADE, null), `change_order` FK→`estimates.ChangeOrder` (CASCADE, null), `version` PositiveInteger, `description`/`qty_ordered`/`units`/`sort_order` (mirror `Deliverable`), `source_deliverable` FK→`Deliverable` (SET_NULL, null). `clean()` enforces exactly one of `estimate`/`change_order` set. `db_table='deliverable_snapshots'`.

- [ ] Steps: failing test (exactly-one-of constraint) → fail → implement → `makemigrations deliverables` → PASS → commit.

---

## Phase B — `on_hold` Job status

### Task B1: Add `on_hold` to the Job status machine

**Files:** Modify `apps/jobs/models.py` (Job: lines 51-103 status constants/choices/`VALID_TRANSITIONS`; add `hold_reason` field near `status`); Test: `tests/test_job_on_hold.py` (new).

Per CO spec §2.1-2.2: add `STATUS_ON_HOLD = 'on_hold'` + choice; transitions `approved→on_hold`, `in_progress→on_hold`, `on_hold→approved`, `on_hold→in_progress`, `on_hold→cancelled`; add `hold_reason = models.TextField(blank=True, default='')`. Clear `hold_reason` when leaving `on_hold` for an active status (in `save()`).

- [ ] TDD: test the new transitions are valid and others still rejected; test `hold_reason` clears on resume. `makemigrations jobs`. Commit.

### Task B2: Schedule excludes `on_hold` jobs

**Files:** Modify `apps/schedule/services.py` (the two task queries ~lines 142, 374 — add `.exclude(job__status=Job.STATUS_ON_HOLD)`); Test: `tests/test_schedule_*` (find the existing schedule test module; add a case).

- [ ] TDD: a task on an `on_hold` job does not appear in the schedule. Commit.

### Task B3: Board shows `on_hold` jobs in the Pipeline lane

**Files:** Modify `apps/jobs/services.py` (`BoardService` — pipeline status filter + `compute_sub_status` to emit an `on-hold` sub-status); Test: existing board test module.

- [ ] TDD: an `on_hold` job appears in `pipeline`, with sub-status `on-hold`, and no worker task columns. Commit.

### Task B4: Block new bleps and shipment creation on `on_hold`

**Files:** Modify `apps/jobs/services.py` (`BlepService` job-status guard — `on_hold` already excluded since it's not in the allowed set; add a test to lock the behavior in). Modify `apps/deliverables/services.py` (`ShipmentService.create` → reject when `job.status == Job.STATUS_ON_HOLD`). Tests in the respective modules.

- [ ] TDD: `start_work` on an `on_hold` job's task is rejected; `ShipmentService.create` raises on an `on_hold` job. Commit.

---

## Phase C — Deliverable anchoring, editability, snapshot/restore

### Task C1: Anchor shipped deliverables (immutable)

**Files:** Modify `apps/deliverables/services.py` (`DeliverableService.update`/`delete` — reject if the deliverable has any `ShipmentItem`); Test: `tests/test_deliverable_service.py`.

- [ ] TDD: editing/deleting a deliverable that has a `ShipmentItem` raises `ValidationError`; an unshipped one still works. Commit.

### Task C2: Editability keyed on CO state

**Files:** Modify `apps/deliverables/services.py` (`is_editable`/`editability_reason` — also editable while a CO on the job is `draft`; read CO spec §5.4 table); Test: `tests/test_deliverable_service.py`.

- [ ] TDD: with an accepted estimate + a `draft` CO on the job → editable; with the CO `open` → not editable; non-CO states unchanged. Commit.

### Task C3: Snapshot + restore service methods

**Files:** Modify `apps/deliverables/services.py` (add `snapshot_document(*, estimate=None, change_order=None)` writing a `DeliverableSnapshot` per live `Deliverable`; and `restore_live_to_snapshot(snapshot_owner)` reconciling unanchored live rows back to a prior snapshot — deliverables spec §5.2/§9); Test: `tests/test_deliverable_snapshot_service.py` (new).

- [ ] TDD: `snapshot_document` copies the live list verbatim and is write-once; `restore_live_to_snapshot` re-adds removed rows, restores edited qty, deletes added rows, leaves anchored rows alone. Commit.

---

## Phase D — ChangeOrderService, lifecycle, expiry

### Task D1: `ChangeOrderService`

**Files:** Create `apps/estimates/change_order_service.py` (keep `services.py` focused; mirror `EstimateService` patterns — read `apps/estimates/services.py`); Test: `tests/test_change_order_service.py` (new).

Methods: `create(*, job_id)` (guard: job must be `on_hold`; **Trigger 1** — snapshot the prior agreement onto the latest accepted agreement document via `DeliverableService.snapshot_document`); `update_status(pk, new_status)` (mirror `EstimateService.update_status`); `mark_open(pk)`; `seed_new(pk)` (create a new CO copying the prior's line items, `parent=prior`); `discard_draft(pk)`.

- [ ] TDD: create refuses when job not `on_hold`; create on an `on_hold` job snapshots the estimate's deliverables (Trigger 1) and returns a draft CO; `seed_new` copies line items and sets parent. Commit.

### Task D2: Signals — CO acceptance auto-advances the Job; rejection snapshots the proposal

**Files:** Modify `apps/estimates/signals.py` (define `change_order_accepted` signal + receiver advancing Job `on_hold → approved` via `JobService.update_job`, with a system `HistoryEntry`); add rejection handling (in `ChangeOrderService.update_status` or a receiver) that calls `DeliverableService.snapshot_document(change_order=co)` — **Trigger 2** — when a CO goes to `rejected`; Test: `tests/test_change_order_lifecycle.py` (new).

- [ ] TDD: accepting a CO on an `on_hold` job moves the Job to `approved` and writes history; no Task/Material is created or mutated (assert task/material counts unchanged); rejecting a CO snapshots its proposal and leaves Job status unchanged. Commit.

### Task D3: `mark_change_orders_expired` command

**Files:** Create `apps/estimates/management/commands/mark_change_orders_expired.py` (mirror `mark_estimates_expired.py` verbatim, swapping `Estimate`→`ChangeOrder`, `EstimateService`→`ChangeOrderService`, `process_name='mark_change_orders_expired'`, `object_type='change_order'`); Test: `tests/test_mark_change_orders_expired.py` (new). Also add the cron line to `deploy/cron/crontab` (e.g. `45 1 * * *`, offset from the estimate sweep).

- [ ] TDD: an open CO past `expiration_date` is expired with a system history row; one with null expiration is skipped; a non-open CO is untouched. Commit (include the crontab line).

---

## Phase E — Agreement of record

### Task E1: Composed agreement endpoint data

**Files:** Create `apps/estimates/agreement.py` with `compose_agreement(job)` (start from the accepted estimate's line items; apply each `accepted` CO in acceptance-date order: `remove` drops the target, `replace` swaps it, `add` appends; return the effective line set + grand total — CO spec §4); Test: `tests/test_agreement_composition.py` (new).

- [ ] TDD: estimate with 3 lines + an accepted CO that removes line 2, replaces line 3, adds a line → correct effective set and total. Commit.

---

## Phase F — API

### Task F1: `ChangeOrderViewSet` + serializer + line-item endpoints

**Files:** Create `apps/api/change_orders/` (serializers.py, views.py) mirroring `apps/api/estimates/`; register the router in `apps/api/urls.py`; reuse `LineItemMixin` (read `apps/api/mixins.py:153+`) and `StatusTransitionMixin`. Endpoints per CO spec §8 (list/retrieve `IsAuthenticated`; create/patch/mark-open/seed-new/discard `CanManageJobs`; line-item endpoints; `GET /api/jobs/{id}/agreement/`). DELETE returns 200+JSON.

- [ ] TDD (API tests in `tests/test_change_order_api.py`): create guarded by job `on_hold` + `CanManageJobs`; mark-open; accept transitions; agreement endpoint returns the composed set. Commit.

---

## Phase G — SPA UI

### Task G1: Change Order detail page + on_hold pill + CO deliverables section

**Files:** Frontend under `frontend/src/routes/` + `frontend/src/components/`. Read the estimate detail page + `LineItemTable` + the Job status pill + `DeliverablesSection` first to match patterns. Add: a CO detail route (line items with add/remove/replace, status pill, agreement view), the `on_hold` option on the Job status pill (gated `can_manage_jobs`), and the CO deliverables section editing the live list while the CO is `draft` (deliverables spec §8). Verify with `npm run build` + the `run`/`verify` skill.

- [ ] Steps: read components → implement → `cd frontend && npm run build` → visual verify → commit.

---

## Self-review checklist (run before execution)

- **Spec coverage:** CO model/lifecycle/number/expiry (A1, D1-D3); `on_hold` + guards (B1-B4); deliverable anchoring/editability/snapshots (A3, C1-C3); agreement (E1); API (F1); UI (G1). All CO-spec §§ and deliverables-spec §§ map to a task. ✓
- **Placeholders:** core models/command have full code; service/API/UI tasks give exact files + behavior + test intent and instruct reading the named existing patterns (honest for integration/UI work, not hand-wavy "add logic"). Where a later task depends on an earlier symbol (e.g. `change_order_accepted` in A1 referenced, defined in D2), that's called out inline.
- **Type consistency:** `ChangeOrder.STATUS_*`, `ChangeOrderLineItem.ACTION_*`, `DeliverableService.snapshot_document`/`restore_live_to_snapshot`, `compose_agreement(job)` used consistently across tasks. ✓
- **Ordering:** A (models) → B (on_hold) → C (deliverable services) → D (CO services/signals/expiry, depends on A+C) → E (agreement) → F (API, depends on D+E) → G (UI, depends on F). Execute in this order.
