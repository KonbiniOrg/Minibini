# Task-Owned Money — Phase 4 Plan (parent × per-unit subtasks + deliverables bridge, spec §9)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development, task-by-task.

**Goal:** Implement spec §9 of `docs/plans/2026-08-02-task-owned-money.md`: quantity-bearing non-startable parent tasks whose per-unit subtasks carry estimates, with batch-total actuals, the `qty_scales_with_parent` flag, the single derivation helper, parent-as-unit-of-billing, template structure-stamping, and the Deliverables bridge.

**Architecture:** Subtasks exist (one level, `parent_task`). §9 adds: a parent with subtasks becomes non-startable and delegates PM functions to children; parent qty multiplies per-unit child estimates through ONE blessed derivation helper; the parent is the only wizard-pool atom (children never bill independently); parent completion carries the billed qty; ad-hoc structure creation is primary, WorkTemplate stamping optional; Deliverable↔Task copy actions with a provenance FK.

**Global Constraints:** identical to the Phase 2/3 plans' (branch `feature/fees`; never write the dev DB; FOREGROUND-ONLY test commands with explicit 600000 ms timeout — no backgrounding, no monitors, no waiting on notifications; `--noinput`, one Django run at a time, fresh DB after migration changes, summary-line judgment only; API error contract; frontend conventions; converter rules; full suites once at final verification; e2e for changed flows; docs in-phase).

## Binding rules (from spec §9, all previously RM-approved)

1. **Non-startable parent**: a task with ≥1 subtask cannot start/blep/assign; PM functions live on children. Becoming a parent while in_progress: the first-subtask creation is REJECTED unless the task is pending/blocked (a started task's time is its own — decompose before starting; error explains). Parent completion is OFFERED (not automatic) when all children are terminal (complete/cancelled), keeps the entered-qty gate ("quantity made?" — that actual is what's billed). Parent cancel cascades? NO — cancel requires children individually handled first (error listing open children).
2. **Multiplier**: expected(child est field) = child_est × (parent.qty if `qty_scales_with_parent` else 1); parent.qty comes from `est_qty` (the parent is entered-qty; its unit is whatever it is — multiplier is unit-agnostic, NO 'ea' requirement). `qty_scales_with_parent` BooleanField on Task, functional only with a parent, inert on top-level rows, rendered only on subtask forms. DEFAULT: keyed to the parent's unit at subtask creation — true when parent `unit_label` == 'ea', else false — freely overridable (per RM 2026-08-02, "let users complain" accepted).
3. **One derivation helper**: `Task.expected_qty()` (and `expected_worker_time()`) on the child — multiplier applied there and ONLY there; schedule bars, expected-vs-logged displays, estimate composition all read through it. Raw `est_qty` on a subtask means per-unit (flag true) or per-batch (flag false); ACTUALS are always raw batch totals. The subtask form ALWAYS shows the derived expectation inline ("20 min/bf × 500 bf = 10,000 min expected").
4. **Parent is the unit of billing**: children NEVER appear in wizard source pools (estimate + invoice) nor bill independently; a child's per-unit money (if any) aggregates into the parent's effective per-unit price: parent effective rate = parent.rate if set, else Σ over children of (child effective_rate × child per-unit qty [flag-true children] — flag-false children contribute their total/parent.qty? NO: flag-false children contribute (child_est × child rate) / parent.qty per unit... SIMPLIFY per spec: parent per-unit price = Σ flag-true children (est × rate) + (Σ flag-false children (est × rate)) / parent.qty, quantized at the end; expose as `Task.derived_unit_price()`; used when parent.rate is NULL; parent.rate set explicitly overrides (line-level override still applies as ever). A subtask that must bill independently gets DETACHED (existing parent_task=null edit) — full stop.
5. **Claims**: claiming a parent claims the structure (children get no source rows — they're simply invisible to pools); a child of a claimed parent cannot be detached while the parent is claimed by a non-draft document (guard with clear error).
6. **Templates**: WorkTemplate application gains an optional quantity N: creates the parent (name from template/product, est_qty=N) + per-unit subtasks from the template's items — ONLY when the template opts in (new `is_product_structure` boolean on WorkTemplate; default false keeps today's flat generation). Convenience only; ad-hoc build (Add Task then Add Subtask) is primary and must need NO template.
7. **Deliverables bridge**: `Deliverable.source_task` nullable SET_NULL provenance FK (same invariant family: nothing computes through it). Task → "Add as deliverable" copies (description=name, qty_ordered=est_qty, units=unit_label); Deliverable → "Create work structure" mints a top-level task (same three fields back). Copy actions hide when a link exists; passive mismatch badge (task est qty vs qty_ordered — est, deliberately NOT actuals). NO sync. Shipment machinery untouched.
8. **Schedule**: parent (non-startable) draws no bar once it has children; children draw bars from `expected_worker_time()` (derived). Check ScheduleService for how bars source est_worker_time and route through the helper.

## Tasks

### Task 1: Schema + derivation helper + non-startable core
`qty_scales_with_parent` (default True at DB — the unit-keyed default is APPLICATION-time at subtask creation, not a DB default), `Deliverable.source_task` (apps/deliverables), `WorkTemplate.is_product_structure`; migrations. `Task.expected_qty()`/`expected_worker_time()`/`derived_unit_price()` helpers + `is_parent` property. Non-startable enforcement in lifecycle service (start/blep/assign/complete rules; first-subtask rejection on started parents; parent completion offered-not-auto with entered-qty gate; cancel requires children handled). TDD heavy; fresh-DB run of covering modules.

### Task 2: Billing — pools exclude children; parent aggregation
Wizard source pools (estimate + invoice) exclude tasks with `parent_task_id` set; parent uses `derived_unit_price()` when rate NULL (compute paths: `effective_rate` fallback or wizard-side? put it in `Task.effective_rate()` — rate NULL + is_parent → derived; document that a money-less childless task still prices 0); detach-while-claimed guard; claims unchanged otherwise. Tests incl. bundle behavior with a parent atom.

### Task 3: API + serializers
Subtask create gains `qty_scales_with_parent` (unit-keyed default applied service-side; money-gated? NO — the flag shapes estimates not price rate; it's est-shaping like est_qty: open to authenticated per existing est_qty rules — confirm est_qty's gating and match it); expose `is_parent`, `expected_qty`, `expected_worker_time`, `derived_unit_price`, flag on task payloads; deliverable serializer + the two copy-action endpoints (`POST /api/tasks/{id}/add-as-deliverable/`, `POST /api/jobs/{id}/deliverables/{id}/create-work-structure/` — follow existing deliverable routing); template-apply N param. Permission-matrix tests.

### Task 4: Frontend — structure UI
WorkItemForm subtask mode: flag checkbox (unit-keyed default; only on subtask forms) + ALWAYS-inline derived expectation ("X/unit × N unit = Y expected"); TaskDetailPage parent view (children table with expected-vs-logged columns, completion offer when children terminal, non-startable affordances hidden); TaskTree/board render structures (children indented under parent; parent shows derived price); schedule reads derived worker time (verify frontend consumes API-provided bars — likely backend-only via ScheduleService). Vitest throughout.

### Task 5: Frontend — deliverables bridge + template N
"Add as deliverable" on qty-bearing tasks (hide when linked); Deliverable list "Create work structure" (hide when linked); mismatch badge (est vs ordered); template-apply dialog gains quantity when template `is_product_structure`; ServiceItem/WorkTemplate manager exposes the new boolean. Vitest.

### Task 6: Converter + validate_data
Converter: no structural change expected (it emits flat tasks) — verify and state; validate_data: subtask-depth check exists (keep); add: non-startable violations (parent with bleps on itself after children existed — tolerate historical, WARN), flag-on-parentless rows inert (no check needed — document why), children with source rows = ERROR (billing invariant). Tests.

### Task 7: Full verification (fresh DB) + repairs
Full Django + full Vitest, triage per standing rules.

### Task 8: E2E
New spec: build a widget structure ad hoc (parent 10 ea + per-unit subtask + per-batch subtask; inline derived expectations assert 10× vs 1×); blep the child (parent unbleppable); complete children → parent completion offer with qty-made prompt; estimate wizard offers ONLY the parent at derived price; deliverable copy both directions + mismatch badge. Seed conformance. Full pass.

### Task 9: Docs
jobs-and-tasks (§ new: quantity structures — the big one), estimates-and-prices (billing aggregation), schedule.md (derived bars), data-constraints (flag, provenance FKs, guards), ui-flows + README. Current behavior only.

## Self-review notes
- §9 bullets each land in a task: non-startable/multiplier/helper/flag → 1; billing/claims → 2; API → 3; UI → 4/5; templates → 3+5; deliverables → 3+5; validate → 6; schedule → 1(helper)+4.
- Phase 5 dependency: none (outsourced POs touch purchasing/tasks independently).
- Deliberately NOT here: multi-level nesting (one level stays law), auto-complete parents, deliverable sync, per-widget actual logging.
