# Plan 1 — Deliverables Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a job's deliverables on the Estimate, and add the `all_deliverables_shipped(job)` fulfillment primitive the later completion gate (Plan 3) needs.

**Architecture:** Backend is a thin addition to the existing `DeliverableService` (no model/migration changes). Frontend adds a read-only Deliverables section to the Estimate detail page, reusing the existing deliverables presentation and the existing `GET /api/jobs/{id}/deliverables/` endpoint. This plan is independent of Change Orders (Plan 2) and Billable Cancellation (Plan 3); `DeliverableSnapshot`, anchoring, and the CO-state editability changes live in Plan 2.

**Tech Stack:** Django 5.2 / DRF, Svelte 5 SPA, MySQL (tests use a throwaway test DB).

**Repo:** Primary checkout `/Users/drshiny/Documents/konbini/Minibini`, branch `feature/change-orders`. Commit as you go.

**DB safety (CLAUDE.md):** Never write to the dev DB — no `migrate`, `shell`, `loaddata`, or ORM writes against it. `python manage.py test` is fine (separate test DB). Only **one** test run at a time across all agents.

---

### Task 1: `DeliverableService.all_deliverables_shipped(job)` helper

A pure read helper: `True` iff every `Deliverable` on the job is fully picked up (delivered). Prepared-but-not-picked-up does **not** count. A job with zero deliverables returns `True` (nothing outstanding). Plan 3's completion gate calls this.

**Files:**
- Modify: `apps/deliverables/services.py` (add a method to `DeliverableService`, near `compute_fulfillment` at lines 122-139)
- Test: `tests/test_deliverable_service.py` (add a new test class; mirrors the existing `ComputeFulfillmentTests` setup at lines 141-178)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_deliverable_service.py`:

```python
class AllDeliverablesShippedTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Estimate.objects.create(
            job=self.job, estimate_number='EST-AS-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('10'), units='ea',
        )

    def test_false_when_nothing_shipped(self):
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_partially_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('6'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_prepared_but_not_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PREPARED)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_fully_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_multiple_deliverables_all_picked_up(self):
        d2 = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea',
        )
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        ShipmentItem.objects.create(shipment=s, deliverable=d2, qty=Decimal('2'))
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_one_of_several_unshipped(self):
        Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea',
        )
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_no_deliverables(self):
        Deliverable.objects.filter(job=self.job).delete()
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_deliverable_service.AllDeliverablesShippedTests`
Expected: FAIL — `AttributeError: type object 'DeliverableService' has no attribute 'all_deliverables_shipped'`.

- [ ] **Step 3: Implement the helper**

In `apps/deliverables/services.py`, add this method to `DeliverableService` (right after `compute_fulfillment`):

```python
    @staticmethod
    def all_deliverables_shipped(job):
        """True iff every Deliverable on the job is fully picked up.

        Prepared-but-not-picked-up does not count as delivered. A job with no
        deliverables returns True (nothing outstanding). Used by the job
        completion gate.
        """
        for d in Deliverable.objects.filter(job=job):
            fulfillment = DeliverableService.compute_fulfillment(d)
            if fulfillment['qty_picked_up'] < d.qty_ordered:
                return False
        return True
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_deliverable_service.AllDeliverablesShippedTests`
Expected: PASS (6 tests, OK).

- [ ] **Step 5: Run the full deliverables service test module (no regressions)**

Run: `python manage.py test tests.test_deliverable_service`
Expected: PASS (all existing classes + the new one).

- [ ] **Step 6: Commit**

```bash
git add apps/deliverables/services.py tests/test_deliverable_service.py
git commit -m "$(cat <<'EOF'
Add DeliverableService.all_deliverables_shipped helper

True iff every deliverable on the job is fully picked up; powers the job
completion gate (Plan 3). Prepared-but-not-picked-up doesn't count; a job with
no deliverables is vacuously shipped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Show the deliverables section on the Estimate detail page

Read-only display of the job's deliverables (agreed scope: `qty units description`) on the Estimate detail page, beside/above the line items — the customer's full picture. No fulfillment columns (the estimate is a pre-work document). Reuses the existing endpoint `GET /api/jobs/{id}/deliverables/` and the existing read-only deliverables presentation.

**Files:**
- Read first (to match patterns, no guessing):
  - `frontend/src/routes/estimates/EstimateDetailPage.svelte` — where to mount the section + how it loads the job/line items.
  - `frontend/src/components/jobs/DeliverablesSection.svelte` (or wherever the Job-detail deliverables panel lives) — reuse its read-only row rendering.
  - `frontend/src/lib/api.js` — the fetch helper convention.
- Modify: `frontend/src/routes/estimates/EstimateDetailPage.svelte` (add the section).
- Possibly create: a small read-only `EstimateDeliverablesSection.svelte` if the existing panel isn't cleanly reusable read-only.

- [ ] **Step 1: Read the components above** to learn the estimate page's data-loading pattern, the deliverables endpoint shape, and the existing read-only row markup. Do not write code until you've read them.

- [ ] **Step 2: Add the section.** On mount, fetch `GET /api/jobs/{estimate.job_id}/deliverables/` and render a read-only list of `qty units — description` rows under a "Deliverables" heading, placed adjacent to the line-items table. Follow the SPA conventions in `frontend/README.md` (semantic HTML, per-component `<style>`, error-overlay via `lib/api.js`). No edit affordances here (editing stays on the Job detail page / Plan 2's CO flow).

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds, no Svelte errors.

- [ ] **Step 4: Verify visually** using the `run` or `verify` skill (or ask the user to load an estimate that has deliverables) — the section renders the job's deliverables read-only on the estimate page.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/estimates/EstimateDetailPage.svelte frontend/src/components/
git commit -m "$(cat <<'EOF'
Show deliverables on the estimate detail page

Read-only agreed-scope list (qty/units/description) beside the line items, so the
estimate shows the full picture: what we're building and what it costs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (run before execution)

- **Spec coverage:** deliverables spec §1 goal #1 (show deliverables on estimate) → Task 2; §6/§8 fulfillment source for the completion gate → Task 1. Snapshot model, anchoring, editability-by-CO-state are deliberately deferred to Plan 2 (they need `ChangeOrder` to exist and only matter once editing reopens). ✓
- **Placeholders:** Task 1 has full test + impl code. Task 2 is a frontend task whose exact code depends on unread components, so step 1 is an explicit read-first (honest, not a placeholder). ✓
- **Type consistency:** `all_deliverables_shipped(job)` signature used identically in test and impl; relies on existing `compute_fulfillment` keys (`qty_picked_up`) verified in `services.py:134`. ✓
