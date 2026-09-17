# Per-Unit Line Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estimate/CO lines can declare their claimed atoms describe ONE unit
(`per_unit`); the claim rows snapshot the per-unit values; atoms are stamped
to whole-job totals at bundle/mint time; drift between agreement and atoms is
badged with an explanatory Revert modal.

**Spec:** `docs/plans/2026-09-16-per-unit-lines.md` (read §2 for the
governing principle before any task: atoms speak operational totals; claims
carry the per-unit agreement snapshot).

**Architecture:** Two new line-item fields + three new source-row fields;
one derivation branch in `BaseWizardService`; stamping inside
`add_atoms_to_new_line_item` and the mint endpoints; serializer-computed
drift flags; SPA additions to BundleModal (minimal — the full modal
restructure is the RM-gated final phase) and a new DriftModal.

**Tech stack:** Django 5.2 / DRF, Svelte 5 runes, Vitest, Playwright.

## Global Constraints

- **Branch:** RM designates the working branch before implementation
  starts — do NOT create or choose one (global CLAUDE.md rule).
- NEVER write the dev DB (no migrate/shell/loaddata/ORM writes);
  `makemigrations` is fine; tests use the test DB.
- Django tests: FOREGROUND with a timeout, `--noinput`, one run at a time,
  judged only by the `Ran N tests` / `OK` / `FAILED` summary line. Targeted
  modules per task; full fresh-DB suite (NO `--keepdb`) once at final
  verification (this plan adds migrations).
- Vitest: `cd frontend && npm run test:run` (never watch mode).
- Error contract: services raise `ValidationError({'field': [...]})` for
  field problems, `ValidationError('sentence')` otherwise; views don't
  re-render uncaught ValidationError (central handler does).
- User-visible text: never "wizard", never "blep", never "atom" — say
  "tasks and materials"; document-surface copy says "Remove" not "delete".
- Line-item deletes only via `LineItemService.delete_line_item_with_renumber`.
- Line-item saves via `LineItemService.save_line_item` (adjustment recompute).
- The one-unit interpretation is the bundle-modal DEFAULT (spec §5).
- Invoices are OUT OF SCOPE: `InvoiceWizardService`/invoice API get no
  per-unit parameters and no fields.
- Update `docs/designs/estimates-and-prices.md` and
  `docs/designs/data-constraints.md` in the same session (Task 9).

---

### Task 1: Model fields + migrations + revision propagation

**Files:**
- Modify: `apps/estimates/models.py` (EstimateLineItem ~line 560,
  ChangeOrderLineItem ~line 669, EstimateLineItemSource ~line 629,
  ChangeOrderLineItemSource ~line 797)
- Modify: `apps/estimates/services.py` (revise_estimate line copy ~line 290)
- Create: migration `apps/estimates/migrations/0049_per_unit_fields.py`
  (via `makemigrations` — verify the number is next-free first; main's
  PR #478 holds 0044, this branch holds 0048)
- Test: `tests/test_per_unit_fields.py`

**Interfaces (produces):**
- `EstimateLineItem.per_unit` / `ChangeOrderLineItem.per_unit` —
  `models.BooleanField(default=False)`
- `EstimateLineItemSource.per_unit_qty` /
  `ChangeOrderLineItemSource.per_unit_qty` —
  `models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)`
- `EstimateLineItemSource.per_unit_worker_time` /
  `ChangeOrderLineItemSource.per_unit_worker_time` —
  `models.DurationField(null=True, blank=True)` (task claims only; needed so
  est_worker_time drift/Revert has a stored expectation — spec §8)

- [ ] **Step 1: failing tests** — new file `tests/test_per_unit_fields.py`:
  - `test_line_item_per_unit_defaults_false` (both models)
  - `test_source_per_unit_fields_default_null` (both source models)
  - `test_revise_estimate_copies_per_unit_flag`: build an estimate with a
    `per_unit=True` line (direct ORM in test), `revise_estimate`, assert the
    revision's copied line has `per_unit=True`
  - `test_revise_estimate_moves_per_unit_qty_with_source_rows`: source row
    with `per_unit_qty=Decimal('0.75')` still carries it after revision
    (rows are MOVED, so this passes for free — the test pins the invariant)
- [ ] **Step 2: run, verify failure** —
  `timeout 300 python manage.py test tests.test_per_unit_fields --noinput`
  → FAIL (no such field)
- [ ] **Step 3: add the six fields** with a comment on each source-row field:
  `# Per-unit agreement snapshot (per-unit-lines spec §2/§3): populated only`
  `# for claims on per_unit lines; atoms themselves always store totals.`
  Add `per_unit=li.per_unit` to the `EstimateLineItem.objects.create(...)`
  copy block in `revise_estimate` (services.py ~291).
- [ ] **Step 4: makemigrations** — `python manage.py makemigrations estimates`
  (never `migrate`)
- [ ] **Step 5: run tests** → PASS. Also run
  `timeout 600 python manage.py test tests.test_estimate_wizard_service tests.test_co_authoring_claims --noinput` (no regressions)
- [ ] **Step 6: commit** `feat: per_unit fields on estimate/CO lines + claim snapshot columns`

---

### Task 2: Derivation & sync branch in BaseWizardService

**Files:**
- Modify: `apps/core/wizard.py` (`_is_in_sync` ~line 173,
  `_resync_in_sync_line_item` ~line 229; new `_sum_per_unit_sources`)
- Modify: `apps/api/estimates/serializers.py`,
  `apps/api/change_orders/serializers.py` (expose `per_unit` on the
  line-item serializers' `fields`; `derive_estimate_backing` /
  `derive_co_line_backing` need NO enum change — the in-sync branch lives
  inside `_is_in_sync`, and the sum they pass must come from the right
  summer, see step 3)
- Test: `tests/test_per_unit_derivation.py`

**Interfaces (produces):**
- `BaseWizardService._sum_per_unit_sources(line_item) -> Decimal` — Σ over
  resolvable source rows of `per_unit_qty × atom-rate`, where atom-rate is
  `task.effective_rate()` for tasks and `sell_price` (quantized to cents)
  for materials; rows with `per_unit_qty=None` or a dangling atom are
  skipped (mirror `_resolve_sources`' dangling tolerance).
- `BaseWizardService._line_sum(line_item) -> Decimal` — dispatcher:
  `_sum_per_unit_sources` when `line_item.per_unit` else `_sum_sources`.
- `_is_in_sync(line_item, sum_value)` branch:
  per_unit → `price == sum_value.quantize(Decimal('0.01'))` (no division);
  else today's `price == round(sum/qty, 2)`.

- [ ] **Step 1: failing tests** — `tests/test_per_unit_derivation.py`:
  - `test_per_unit_sum_tasks_and_materials`: line per_unit=True, qty=10;
    task claim per_unit_qty=0.75 on a $60/h task (+$45.00), material claim
    per_unit_qty=4 at sell 2.50 (+$10.00) → `_line_sum == Decimal('55.00')`
  - `test_per_unit_in_sync_is_price_equals_sum`: price=55.00 → in sync;
    price=550.00 → NOT in sync (the whole-line reading must not pass)
  - `test_whole_line_sync_rule_unchanged`: per_unit=False regression pin
  - `test_per_unit_backing_chip_in_sync`: serializer backing =
    'planned_work' when in sync per the per-unit rule (proves the
    serializers call the dispatcher, not `_sum_sources` directly)
  - `test_resync_per_unit_recomputes_price_as_per_unit_sum`
- [ ] **Step 2: verify failure**
- [ ] **Step 3: implement** — add the two methods; change every caller that
  computes a sum for sync purposes (`derive_estimate_backing`,
  `derive_co_line_backing`, `_resync_in_sync_line_item`, and any
  `_sum_sources` call feeding `_is_in_sync` — grep `_sum_sources` and
  `_is_in_sync` across apps/) to use `_line_sum`. Invoice paths keep
  `_sum_sources` (InvoiceLineItem has no `per_unit`; `getattr(line,
  'per_unit', False)` in the dispatcher keeps the base class safe).
- [ ] **Step 4: run** `tests.test_per_unit_derivation`,
  `tests.test_estimate_wizard_service`, `tests.test_invoice_wizard_service`
  → all OK
- [ ] **Step 5: commit**

---

### Task 3: Bundle-time stamping (service layer)

**Files:**
- Modify: `apps/core/wizard.py` `add_atoms_to_new_line_item` (~line 265)
- Modify: `apps/estimates/services.py` / CO service only if class-level
  config is needed (per-unit allowed: estimate + CO wizards; invoice: no)
- Test: `tests/test_per_unit_bundle.py`

**Interfaces (produces):**
- `add_atoms_to_new_line_item(container, atoms, *, overrides=None,
  per_unit=False)`.
  `atoms` entries may carry an optional `'per_unit_worker_time'` (ISO 8601
  duration string; task atoms only) — the modal's input for tasks lacking
  an `est_worker_time`.
- Per-unit behavior, inside the existing `transaction.atomic()`:
  1. Requires `overrides` with a qty > 0 (`ValidationError({'qty': ['A
     quantity is required for per-unit lines.']})` otherwise). Class flag
     `allows_per_unit = True` on estimate/CO wizard services, `False` on
     the base → `ValidationError('This document does not support per-unit
     lines.')`.
  2. For each atom, snapshot pre-stamp per-unit values onto its source row:
     task → `per_unit_qty = task.est_qty`,
     `per_unit_worker_time = task.est_worker_time` (after applying an
     atom-supplied `per_unit_worker_time`, which SETS the task's field
     first); material → `per_unit_qty = material.quantity`.
  3. Stamp the atom to totals and `.save()` it directly (never
     `QuerySet.update()`): `task.est_qty = per_unit_qty * qty`;
     `task.est_worker_time = per_unit_worker_time * float(qty)` when
     non-null (timedelta × float; leave None when None);
     `material.quantity = per_unit_qty * qty`.
     Direct field-set + save deliberately bypasses
     `hours_pair_fill` (that helper only runs in TaskService/api paths) —
     both fields are set explicitly so no pair-fill is wanted.
  4. Line saved with `per_unit=True`. Price/qty/units/description still come
     from overrides (WYSIWYG — the modal always sends all four).
- Non-per-unit calls: byte-for-byte today's behavior (regression tests pin).

- [ ] **Step 1: failing tests** — `tests/test_per_unit_bundle.py`:
  - `test_per_unit_bundle_stamps_task_and_material`: task est_qty 0.75 /
    est_worker_time 45min, material qty 4; bundle per_unit with
    overrides qty=10 → task est_qty 7.50, est_worker_time 7h30m, material
    quantity 40.00; claims carry 0.75/45min and 4.00; line.per_unit True
  - `test_per_unit_bundle_without_worker_time_leaves_null`
  - `test_per_unit_bundle_atom_supplied_worker_time`: atoms entry
    `{'type':'task','id':N,'per_unit_worker_time':'PT20M'}` on a task with
    est_worker_time=None → task ends at 3h20m (20min × 10), claim snapshot
    20min
  - `test_per_unit_bundle_requires_qty` (400-shape ValidationError)
  - `test_invoice_wizard_rejects_per_unit`
  - `test_whole_line_bundle_unchanged` (regression: no stamps, no snapshots)
- [ ] **Step 2: verify failure**
- [ ] **Step 3: implement per the interface above**
- [ ] **Step 4: run** `tests.test_per_unit_bundle`,
  `tests.test_wizard_bundle_summary`, `tests.test_estimate_wizard_api` → OK
- [ ] **Step 5: commit**

---

### Task 4: Bundle API + BundleModal (minimal additions)

**Files:**
- Modify: `apps/api/estimates/views.py` `line_items_from_atoms` (~line 195),
  `apps/api/change_orders/views.py` (~line 148): pass
  `per_unit=bool(request.data.get('per_unit'))` through; atoms pass through
  unmodified (service reads the optional `per_unit_worker_time` keys).
  Invoice view untouched.
- Modify: `frontend/src/components/docsurface/BundleModal.svelte`
- Test: `frontend/tests/BundleModal.test.js` (extend existing if present,
  else create), plus `tests/test_estimate_wizard_api.py` additions

**Modal behavior (minimal — full restructure is Task 10):**
- New state `perUnit = $state(true)` (DEFAULT one-unit, spec §5), rendered
  as a two-option choice above qty:
  "The values on these tasks and materials are for:
  (•) one unit — multiply by quantity   ( ) the whole line".
- One-unit mode: `keepTotal` control hidden (whole-line only); price seeds
  to `total.toFixed(2)` (the summed CURRENT atom amounts ARE the per-unit
  sum under this interpretation); qty seeds EMPTY (user must type it);
  displayed line total = `qty × price`, updating live.
- Preview table (one-unit mode, once qty is valid): one row per atom,
  "cut chair parts — 0.75 h → 7.50 h · schedule 45 m → 7 h 30 m",
  "oak — 4 BF → 40 BF". This is the §12-Q1 mitigation: the
  reinterpretation and the stamps must be unmissable before Create.
- Tasks with no schedule time get an optional per-unit duration input in
  their preview row (sent as `per_unit_worker_time` on that atom entry).
- Whole-line mode: exactly today's UI (keepTotal etc.), sends
  `per_unit: false`.
- Request body: `{atoms: [{type, id, per_unit_worker_time?}], overrides,
  per_unit}`.

- [ ] **Step 1: failing Vitest** — mode default is one-unit; switching modes
  re-seeds price/qty correctly; preview rows compute ×qty; create() posts
  `per_unit` and per-atom worker times; whole-line mode posts
  `per_unit:false` with today's payload
- [ ] **Step 2: verify failure** (`npm run test:run`)
- [ ] **Step 3: implement modal + view passthrough**
- [ ] **Step 4: API tests** — `line-items-from-atoms` with `per_unit:true`
  returns the line with `per_unit` serialized true; stamps visible on
  re-fetched atoms
- [ ] **Step 5: run Vitest + `tests.test_estimate_wizard_api` → OK; commit**

---

### Task 5: Mint flow (post-acceptance checklist)

**Files:**
- Modify: `apps/estimates/mint.py` (`claim_atom_for_line` signature)
- Modify: `apps/api/jobs/views.py` (`_resolve_claim_line` ~line 24, task
  create ~line 418, `create_material` ~line 344, add-from-template ~line 420s)
- Modify: mint modal component (the "Generate work…" flow in
  `frontend/src/components/estimates/EstimateEditView.svelte` and the modal
  it opens — locate via the `Generate work` string)
- Test: `tests/test_per_unit_mint.py`, extend `tests/test_mint_api.py`

**Interfaces (produces):**
- `MintService.claim_atom_for_line(line_item, source_type, source_pk,
  per_unit_qty=None, per_unit_worker_time=None, set_line_per_unit=None)`:
  - `set_line_per_unit` (True/False/None): only honored when the line has
    NO existing sources (the ask-once rule, spec §6);
    `ValidationError('This line's one-unit-or-whole-line choice is already
    set.')` if sources exist and the value differs from `line.per_unit`.
    Sets `line_item.per_unit` via `LineItemService.save_line_item`.
    (This is a service-level accepted-line write — deliberate second
    carve-out beside `work_declined`; document it in the docstring.)
  - When the line is per-unit: `per_unit_qty` REQUIRED
    (`ValidationError('A per-unit quantity is required for this line.')`),
    stored on the source row with `per_unit_worker_time`.
- API: task-create / add-from-template / create_material accept
  `claim_line_per_unit` (bool, first mint only) and, on per-unit lines,
  treat the submitted `est_qty` / `quantity` / `est_worker_time` as
  PER-UNIT values: the view multiplies by `claim_line.qty` before creating
  the atom, and passes the raw per-unit values to `claim_atom_for_line`.
  (Atoms are born with totals — no post-create restamp.)
- Mint modal: when the target line has no sources yet, show the same
  two-option interpretation choice (default one-unit); when sources exist,
  show a static caption ("Values here are per unit — quantities multiply
  by 10." / nothing for whole-line lines).

- [ ] **Step 1: failing tests** — `tests/test_per_unit_mint.py`:
  - `test_first_mint_sets_line_per_unit`
  - `test_second_mint_cannot_flip_choice`
  - `test_per_unit_mint_task_born_with_totals`: per-unit est_qty 0.75 +
    PT45M on a qty-10 line → task 7.50 / 7h30m, claim 0.75 / 45min
  - `test_per_unit_mint_material_born_with_totals`
  - `test_per_unit_mint_requires_per_unit_qty`
  - `test_whole_line_mint_unchanged` (regression)
- [ ] **Step 2: verify failure**
- [ ] **Step 3: implement service, then views, then modal**
- [ ] **Step 4: run** `tests.test_per_unit_mint`, `tests.test_mint_service`,
  `tests.test_mint_api` → OK; Vitest → OK
- [ ] **Step 5: commit**

---

### Task 6: Drift detection + Revert endpoint (backend)

**Files:**
- Modify: `apps/estimates/services.py` (pool) + `apps/api/estimates/serializers.py`,
  `apps/api/change_orders/serializers.py`
- Modify: `apps/api/estimates/views.py` (+ CO views): new action
- Test: `tests/test_per_unit_drift.py`

**Interfaces (produces):**
- Source-pool atom dicts and line-item serializer source entries gain,
  for claims on per-unit lines with `per_unit_qty` set:
  `'per_unit_qty'`, `'expected_total'` (= per_unit_qty × line.qty, and for
  tasks also `'expected_worker_time'` when `per_unit_worker_time` set),
  `'drift': bool` — task drift when `est_qty != expected_total` OR
  (`per_unit_worker_time` set AND `est_worker_time != expected_worker_time`);
  material drift when `quantity != expected_total`. Absent (not False) on
  non-per-unit claims.
- `POST /api/estimates/{id}/restamp-atom/` (and CO analog)
  body `{'source_id': N}`: permission `CanManageJobOrPM` presence-gate
  (mirror the mint endpoints); resets the atom to the expectation
  (task: est_qty + est_worker_time where snapshotted; material: quantity)
  via direct `.save()`; 200 `{'message': '...'}`. Guards: source must
  belong to this document, must have `per_unit_qty`, atom must resolve.

- [ ] **Step 1: failing tests** — drift flags appear only when values
  diverge; CO qty-change scenario (replace line accepted with new qty)
  produces drift on the moved claims; restamp endpoint restores both task
  fields and clears drift; permission denied for plain worker; restamp on
  a whole-line claim → 400
- [ ] **Step 2: verify failure** → **Step 3: implement** → **Step 4: run**
  `tests.test_per_unit_drift`, `tests.test_co_authoring_claims` → OK
- [ ] **Step 5: commit**

---

### Task 7: Frontend drift badge + explanatory Revert modal

**Files:**
- Modify: `frontend/src/components/docsurface/AtomChildRow.svelte` (badge),
  `frontend/src/components/estimates/EstimateEditView.svelte` +
  `frontend/src/components/changeorders/COEditView.svelte` (wiring)
- Create: `frontend/src/components/docsurface/DriftModal.svelte`
- Test: `frontend/tests/DriftModal.test.js`

**Behavior (spec §8 — RM 2026-09-16):**
- A small badge on drifted atom rows ("≠ agreement"). Clicking it opens
  DriftModal — it NEVER mutates directly.
- DriftModal spells out, with the actual numbers: the agreement expectation
  (`0.75 h per unit × 10 units = 7.50 h`), the atom's current value, and
  one sentence on where each comes from. Buttons: **Revert to agreement**
  (calls restamp endpoint, refreshes, closes) and **Cancel**. For material
  atoms, add the physical-reality sentence: "This is a physical material —
  reverting changes the planned quantity but does not undo purchasing or
  stock decisions."
- Errors through `triageError` (FormMessage in-modal).

- [ ] **Step 1: failing Vitest** — badge renders only with `drift`; modal
  shows expectation and current values; Revert posts source_id; material
  copy present for material atoms
- [ ] **Step 2: verify failure** → **Step 3: implement** → **Step 4:
  `npm run test:run` → OK** → **Step 5: commit**

---

### Task 8: Split-materials + CO sibling reminder

**Files:**
- Modify: `apps/core/wizard.py` (or estimate/CO service): split emission
- Modify: bundle views (accept `split_materials: true`), BundleModal
  (checkbox, visible only when the selection has ≥1 task AND ≥1 material)
- Modify: CO edit surface (reminder)
- Test: `tests/test_per_unit_split.py`, Vitest additions

**Interfaces:**
- `add_atoms_to_new_line_item(..., split_materials=False)`: when True (only
  valid with `per_unit=True`), atomically create TWO lines — labor line
  from the task atoms (description/qty/units/price overrides apply to it)
  and a materials line (description `overrides['description'] + ' — materials'`,
  same qty, units `'each'`→ same units as labor line, price = Σ material
  per-unit amounts), both `per_unit=True`. Returns the labor line (API
  responds with both: `{'line_item': ..., 'materials_line_item': ...}`).
  `ValidationError` when the selection lacks either kind.
- CO sibling reminder (spec §9, reminder only): when the CO surface shows a
  replace line targeting a per-unit line, the serializer exposes
  `sibling_per_unit_lines` — other per-unit lines on the same source
  document sharing the target's qty — and the SPA renders one info line:
  "Also qty 10: Materials for dining chairs — update it too?"

- [ ] **Step 1: failing tests** (service split shapes; both-kinds guard;
  serializer sibling list; Vitest checkbox visibility + double payload)
- [ ] **Step 2: verify failure** → **Step 3: implement** → **Step 4: run
  targeted + Vitest → OK** → **Step 5: commit**

---

### Task 9: e2e + docs

**Files:**
- Create: `e2e/specs/per-unit-lines/plan-first.spec.js`,
  `e2e/specs/per-unit-lines/mint-first.spec.js`
- Modify: `docs/designs/estimates-and-prices.md` (per-unit section: fields,
  derivation rule, stamping moments, drift/Revert),
  `docs/designs/data-constraints.md` (new columns + invariants: per_unit_qty
  only on per-unit lines' claims; atoms store totals)

**e2e journeys (run `npx playwright test` from `e2e/`, own ports):**
- plan-first: create job → add 2 tasks + 1 material with per-unit values →
  bundle one-unit qty 10 → assert line price = per-unit sum and total ×10 →
  assert task pane shows stamped totals → accept → job releases
- mint-first: hand line qty 10 → accept → Generate work with one-unit
  choice → task born with totals → checklist completes → auto-release

- [ ] **Step 1: write specs, run e2e → green**
- [ ] **Step 2: update the two design docs**
- [ ] **Step 3: full fresh-DB suite** (migrations on branch):
  `timeout 600 python manage.py test --noinput` WITHOUT `--keepdb`, read the
  summary line; plus full Vitest
- [ ] **Step 4: commit**

---

### Task 10 (FINAL PHASE — RM-gated): Bundle modal restructure

**Do not start without checking in with RM.** Spec §12 phasing + LATER.md
entry "keep-total is confusing; the whole modal probably needs work". Scope:
restructure the modal so the interpretation choice, preview, split, and
schedule-time inputs have a coherent home and the derivation direction is
self-explanatory; rewrite the keep-total copy. This lands after RM has used
Tasks 1–9's functionality in the browser and the real friction points are
known. No steps authored here — it gets its own design pass with RM first.

---

## Self-review notes

- Migration numbers: verify next-free at Task 1 time (branch tip holds
  estimates 0048; main's unmerged PR #478 holds a colliding 0044 — the
  eventual main merge renumbers/merges regardless; do not pre-solve here).
- `getattr(line, 'per_unit', False)` in `_line_sum` keeps InvoiceLineItem
  (no field) on the base path — pinned by
  `test_invoice_wizard_rejects_per_unit` + invoice service regression runs.
- Stamps always direct `.save()` on the atom (CLAUDE.md: no
  QuerySet.update; Shift/Blep normalize in save — Task/Material stamping
  respects the same rule).
- `timedelta * Decimal` is a TypeError — always `* float(qty)` for
  durations, and quantize Decimal money/qty results to `'0.01'`.
