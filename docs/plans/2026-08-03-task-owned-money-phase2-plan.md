# Task-Owned Money — Phase 2 Plan (Fee re-scope + line-entry vocabulary)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement spec §3 + §8 of `docs/plans/2026-08-02-task-owned-money.md`: Fee becomes the signed pure-money atom (credits = negative Fees, `task` OneToOne dropped), and freeform document lines carry an explicit three-value kind (work | material | fee) with kind-specific entry forms — a bare hand-line no longer falls through to Fee; a Work hand-line crystallizes into a flat task.

**Architecture:** Phase 1 (complete, `8acc4d10`) gave Task its own money block, so a scheme-less flat task is now constructible — that is what unlocks the Work crystallization branch. All claims/source-row machinery is reused unchanged; the acceptance/CO discriminators gain an explicit branch on the stored kind instead of defaulting.

**Tech Stack:** unchanged (Django 5.2/DRF/MySQL; Svelte 5/Vitest; Playwright).

## Global Constraints

Identical to Phase 1's plan (`docs/plans/2026-08-02-task-owned-money-plan.md` §Global Constraints) — branch is RM-designated `feature/fees`; never write the dev DB; `--noinput`, one Django run at a time, fresh DB (no `--keepdb`) after migration changes, never judge by piped exit codes; **all subagent test runs FOREGROUND with timeout (≤600000 ms), no background runs, no monitors**; line-item deletes via `LineItemService.delete_line_item_with_renumber`; API error contract (`detail`/field-dict, DELETE→200+JSON); frontend `triageError` venues, `<tbody>`, explicit saves; converter changes run `tests.test_neals_builders`, never touch `nealsmall.json`; full suites once at final verification; e2e for changed user-reachable flows; docs updated in-phase.

## Carried-in from Phase 1 close-out

- Parked: `add_from_template` silently no-ops dict-shaped `active_modifiers` (bypasses TaskSerializer). Fix inside Task 6 (API surfaces): view-level shape check (list of strings) with a field error, mirroring `TaskSerializer.validate_active_modifiers`'s CREATE branch.

## Phase 2 — file structure

| File | Responsibility |
|---|---|
| `apps/jobs/models.py` (Fee ~:690+) | drop `task` OneToOne; signed `unit_rate` (≠ 0) |
| `apps/jobs/services.py` (`FeeService`) | drop task param; signed validation |
| `apps/estimates/models.py` | `freeform_kind` on EstimateLineItem + ChangeOrderLineItem replacing `is_material`; constants |
| `apps/estimates/acceptance.py`, `co_acceptance.py` | explicit kind branch: work→flat Task (+'task' source row), material→provisional Material (existing), fee→Fee (existing); no default fallthrough |
| `apps/estimates/services.py`, `change_order_service.py` | add-line accepts `freeform_kind`; negative price only for fee kind; AC rules per kind |
| `apps/api/jobs/{views,serializers}.py` | Fee endpoints lose task; add_from_template modifier shape check |
| `apps/api/estimates/*`, `apps/api/change_orders/*` (find real paths) | line-item serializers expose kind |
| `apps/core/management/commands/validate_data.py` | fee `unit_rate ≠ 0`; kind-consistency check (kind non-null iff bare freeform line) |
| `nealsdata/converter/build.py` | emit `freeform_kind` on line fixtures / keep fee emission valid |
| `frontend/src/components/PriceListPicker.svelte` | estimate footer → explicit Work / Material / Fee-Credit buttons (task-surface footer already has three-atom buttons; Add Fee STAYS) |
| `frontend/src/components/estimates/EstimateAddLineForm.svelte` + CO twin | kind-specific freeform forms; Work form has preset dropdown (prefill from `default_rate_scheme` via task-applicable list) that stamps rate/units/AC into editable fields; Fee/Credit form signed amount + "will appear as a credit" echo; negative rejected on work/material |
| `frontend/src/components/estimates/EstimatePanel.svelte` etc. | kind badges on lines (work/material/fee/adj) |
| `frontend/src/components/FeeModal.svelte` | task field removed (if present); signed amount + credit echo |
| e2e | new spec: estimate Work + Fee/Credit hand-lines through acceptance |
| docs | estimates-and-prices (§4.5 Fee, hand-line/crystallization sections), jobs-and-tasks §4.7, data-constraints §1.8a + line-item constraints, ui-flows Add-Line checklist |

**Canonical interfaces (all tasks + later phases):**

```python
# apps/estimates/models.py — both line-item models
KIND_WORK = 'work'; KIND_MATERIAL = 'material'; KIND_FEE = 'fee'
FREEFORM_KIND_CHOICES = [(KIND_WORK,'Work'),(KIND_MATERIAL,'Material'),(KIND_FEE,'Fee / credit')]
freeform_kind = models.CharField(max_length=10, choices=FREEFORM_KIND_CHOICES,
                                 null=True, blank=True)   # non-null IFF bare freeform line
# is_material is REMOVED (data migration: bare lines map true→'material', false→'fee';
# catalog/service/adjustment lines → NULL)

# apps/estimates/acceptance.py — the work branch creates:
Task(job=..., name=li.description[:100] or 'Work', description=li.description,
     qty_source=Task.QTY_ENTERED, est_qty=li.qty, rate=li.price,
     unit_label=li.units, accounting_category=li.accounting_category,
     source_scheme=None)          # + EstimateLineItemSource(source_type='task')
# Fee branch/creation: unit_rate may be negative, never zero.
```

---

### Task 1: Fee model re-scope — drop `task`, allow signed amounts

**Files:** `apps/jobs/models.py` (Fee), `apps/jobs/services.py` (FeeService), migration (RemoveField task; no schema change needed for sign), `apps/api/jobs/serializers.py` (FeeSerializer drops task), `apps/api/jobs/views.py` (create_fee/fee_detail drop task handling), `apps/core/management/commands/validate_data.py` (`check_fees`: `unit_rate != 0`, negative allowed), tests: `tests/test_fee_model.py`, `tests/test_api_fees.py`, `tests/test_validate_data.py` (fee class).
**Produces:** Fee without `task`; `FeeService.create_on_job/update` accept negative `unit_rate`, reject 0 (`ValidationError({'unit_rate': ...})`); API mirrors.
- [ ] TDD: failing tests — negative fee creates and computes negative amount; zero rejected 400; `task` absent from payloads; POST with `task` key → 400 (unknown/removed, match existing unknown-field convention or explicit message). Then implement + migration; run the three modules + `tests.test_deletion_guards tests.test_line_item_sources` (claims unaffected). Commit.

### Task 2: `freeform_kind` on line models + data migration

**Files:** `apps/estimates/models.py` (both models: add field + constants, remove `is_material`, update help_texts), migrations (Add, RunPython map, Remove `is_material`), grep sweep of `is_material` consumers in apps/ (services, acceptance — leave the acceptance rewrite itself for Task 3 but keep it compiling by mapping `is_material` reads to `freeform_kind == KIND_MATERIAL` with behavior identical), tests: `tests/test_line_kind_migration.py` (new, RunPython-helper-direct style).
**Mapping rule:** rows with `inventory_item` or `service_item` or (estimate-side) `adjustment_service` → NULL; else `is_material=True`→'material', False→'fee' (preserves the historical bare→Fee default for already-existing lines).
- [ ] TDD on the mapping helper; implement; fresh-DB run of the new module + `tests.test_acceptance_fees tests.test_hand_line_ac_validation`; commit.

### Task 3: Acceptance + CO discriminators — explicit branch, Work→flat Task

**Files:** `apps/estimates/acceptance.py`, `apps/estimates/co_acceptance.py`, tests: `tests/test_acceptance_work_lines.py` (new), update `tests/test_acceptance_fees.py`, `tests/test_change_order_acceptance.py`.
**Branch:** kind NULL → existing catalog/service/material/atom paths untouched; 'material' → provisional Material (existing path); 'fee' → Fee (existing path); 'work' → flat Task per the canonical block above + `'task'` source row claim (mirror how deferred-service crystallization claims — read that path first). CO twin incl. `_mirror_of`/`_retire`: an un-invoiced crystallized work-task retires like the CO fee path retires fees (delete task via TaskService rules — a crystallized flat task has no bleps yet; if bleps exist, refuse as task-delete rules already do). Counts: `work_tasks_created` joins `fees_created`.
- [ ] TDD: work line → Task with exact money block + claim; negative-price work line impossible (Task 4 guards entry, but acceptance asserts too — defensive ValidationError); fee lines unchanged; CO add/replace/remove for work lines. Run the four modules + `tests.test_deferred_service_crystallization`. Commit.

### Task 4: Line-entry validation + API exposure

**Files:** `apps/estimates/services.py` (~add_line_item region), `apps/estimates/change_order_service.py`, line-item serializers (find under apps/api/), tests: `tests/test_hand_line_ac_validation.py` + api line-item tests.
**Rules:** `freeform_kind` required on bare freeform lines (no silent default — API 400 without it; the old bare→fee default is GONE at entry); negative `price` only when kind='fee' (or percentage adjustment lines — untouched); AC: fee+work require AC (existing fee rule extends to work), material defaults from config (existing); serializers expose `freeform_kind` read/write on create only (immutable after — matches line immutability conventions).
- [ ] TDD; implement; run modules; commit.

### Task 5: Converter

**Files:** `nealsdata/converter/build.py` (+ tests `tests/test_neals_builders.py`).
Line fixtures gain `freeform_kind` (its fee-shaped hand lines → 'fee'; material freeform → 'material'; drop is_material key); fee emission stays valid (signed rule: converter never emits 0-rate fees — verify skip logic). Run `tests.test_neals_builders tests.test_neals_parsing`. Commit.

### Task 6: API surfaces cleanup + parked item

**Files:** `apps/api/jobs/views.py` (`add_from_template`: reject non-list-of-strings `active_modifiers` with field error mirroring TaskSerializer CREATE branch), line-item viewset glue found in Task 4 not already covered, tests.
- [ ] TDD (dict-shaped payload → 400 with field error; strings → 201); run `tests.test_api_jobs tests.test_api_tasks`; commit.

### Task 7: Frontend — picker + kind forms (estimate & CO)

**Files:** `PriceListPicker.svelte` (estimate footer: Work / Material / Fee-Credit buttons replace checkbox; task-surface footer unchanged), `EstimateAddLineForm.svelte` + CO add-line twin (kind-specific forms: Work = preset dropdown [task-applicable list, default preselected when present] stamping rate/units/AC into editable fields + qty/units; Fee-Credit = qty(default 1) × signed amount + AC + "will appear as a credit" echo when negative; Material = existing), line list badges (work/material/fee/adj) in the estimate/CO line tables, Vitest for each.
**Conventions:** buttons act; negative input on Work/Material shows field error pointing at Fee/Credit; payload includes `freeform_kind`.
- [ ] TDD Vitest red→green; full `npm run test:run`; commit.

### Task 8: Frontend — FeeModal + invoice surface

**Files:** `FeeModal.svelte` (drop task remnants; signed amount + credit echo; zero rejected client-side mirror), invoice add-money surface (find where invoice wizard/panel adds fee atoms — relabel to "Fee / credit", signed support), Vitest.
- [ ] TDD; full `npm run test:run`; commit.

### Task 9: validate_data + full verification (fresh DB)

**Files:** `validate_data.py` (kind-consistency: non-null iff bare freeform; fee `unit_rate != 0` landed in Task 1 — verify), then FULL fresh-DB Django run (output to file, read summary) repairing fallout per Phase 1 Task-13 conversion rules (no weakened assertions; real bugs escalate), full Vitest. Commit(s).

### Task 10: E2E

**Files:** new `e2e/specs/add-line-and-work-authoring/hand-line-kinds.spec.js`: estimator adds a Work hand-line (preset prefill visible) + a negative Fee/Credit line; accepts; job shows the crystallized flat task (money block, no scheme) and the credit fee; invoice wizard offers both (credit shows negative). Fix any seed/spec fallout. Full e2e pass. Commit.

### Task 11: Docs

**Files:** `docs/designs/estimates-and-prices.md` (hand-line entry §, crystallization §, Fee §4.5 re-scope: signed, no task FK), `docs/designs/jobs-and-tasks.md` (§4.7 Fee), `docs/designs/data-constraints.md` (§1.8a fee sign; line freeform_kind constraints), `docs/ui-flows/Add-Line-and-Work-Authoring.md` (+README map). Current behavior only; verify against code. Commit.

## Self-review notes (write time)

- Spec §3 → Tasks 1, 3, 8; §8 → Tasks 2, 4, 7; converter/validate continuity → 5, 9; carried parked item → 6.
- Phase 3 dependency: nothing here blocks nullable-AC (Task 4 keeps AC required on fee+work lines; Phase 3 relaxes in one place).
- Phase 4 dependency: crystallized flat tasks are ordinary tasks — the §9 parent/subtask work builds on them without rework.
- Deliberately NOT in Phase 2: post-invoice credits (QBO credit memos), invoice-time behavior changes beyond labeling/sign, "Add Fee" button removal (it stays per spec §8).
