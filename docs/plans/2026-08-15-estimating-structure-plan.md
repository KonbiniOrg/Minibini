# Claims-by-Construction Estimating Structure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `docs/plans/2026-08-15-estimating-structure.md`: the
mint/decline gestures on frozen hand lines, the acceptance checklist,
auto-release replacing release-to-floor, the bundle modal, and the
removal of freeform claim attachment.

**Architecture:** One new model field (`EstimateLineItem.work_declined` —
this branch HAS a migration). Mint machinery is salvaged from the
abandoned `feature/planning-surface` branch (final head `c231c8de`) with
a narrower status gate — implementers COPY-ADAPT via `git show
c231c8de:<path>` (never cherry-pick; the deltas below are deliberate).
Answeredness + auto-release are a small new service layer over existing
transitions. The bundle modal wraps the existing
`add_atoms_to_new_line_item` wizard path with authoring overrides.

**Tech Stack:** Django 5.2 + DRF, Svelte 5 + Vitest, Playwright.
**Branch:** `feature/estimating` (RM-created; commit everything here).

**Scoping decisions CONFIRMED by RM at plan review (2026-08-15):**
(1) "Add selected here" is removed from the ESTIMATE and CO surfaces
only; the INVOICE keeps its version (invoice claims mean "billed on this
line," not "the work behind this line") — invoice-side rework comes
after estimating settles. (2) Leanest first pass: **mint and decline are
available ONLY on ACCEPTED estimates** — open estimates are frozen and
inert; early catalog crystallization (old Task 4) is CUT. The checklist
is the single home of work decisions.

## Global Constraints

- **Never write the dev DB** (no migrate/shell/loaddata/ORM writes
  outside `manage.py test`). `makemigrations` is allowed and required.
- Django tests: ALWAYS `--noinput`, FOREGROUND with explicit timeout
  (≤600000ms per call), ONE run at a time, judged ONLY by the
  `Ran N tests`/`OK`/`FAILED` summary line. **This branch adds a
  migration → the final full-suite gate runs WITHOUT `--keepdb` (fresh
  DB).** Targeted modules during tasks.
- Vitest: `npm run test:run` from `frontend/` (never watch). TDD
  everywhere; RED/GREEN evidence in reports.
- Mint gate (exact): `MINT_STATUSES = (Estimate.STATUS_ACCEPTED,)` —
  a one-element tuple; draft AND open are refused (frozen-source rule
  plus RM's leanest-pass trim: work decisions live on the acceptance
  checklist only).
- Claims arise ONLY by construction: no endpoint or gesture may attach a
  pre-existing atom to a pre-existing line. (`add-atoms` on estimates/COs
  is removed from the UI; the draft-only wizard endpoints stay for the
  bundle modal + projected-line mechanics.)
- Errors: operation errors `{'detail': ...}`; field-shape only for real
  user inputs; central handler renders uncaught ValidationError.
- User-visible: "timeslip" never "blep"; "Remove" not "delete";
  buttons act/links navigate; confirms only for irreversible actions.
  Gesture labels (RM: "actual word tbd" — use these until RM renames in
  browser review): **"Generate work…"**, **"No work needed"**,
  **"Bundle into line…"**.
- e2e is DoD (Task 10); docs in Task 11.

---

### Task 1: `work_declined` on EstimateLineItem (migration + PATCH)

**Files:**
- Modify: `apps/estimates/models.py` (EstimateLineItem)
- Create: migration (via `makemigrations estimates`)
- Modify: `apps/api/estimates/serializers.py` (expose field),
  `apps/api/estimates/views.py` (PATCH handling in the line-item update
  path — find where line-item PATCH lands; it flows through
  `LineItemMixin`/`EstimateService.update_line_item`)
- Test: `tests/test_work_declined.py`

**Interfaces (produces):** `EstimateLineItem.work_declined:
BooleanField(default=False)`; PATCH `{'work_declined': true|false}` on
`/api/estimates/{id}/line-items/{item_id}/` allowed — uniquely among
line fields — while the estimate is `accepted` (all other field
edits stay draft-only; draft AND open refuse the flag), gated
`CanManageJobOrPM`, refused with
`{'detail': ...}` when: the line has sources, is an adjustment, is a
deposit line, or carries a catalog identity (`service_item_id` /
`inventory_item_id` / `is_material` — those crystallize; decline is for
plain hand lines only). Reversible (false → back to unanswered).

- [ ] **Step 1: failing tests** — field default False; PATCH true on an
  ACCEPTED estimate's plain hand line → 200 + persisted; PATCH on draft
  AND on open → refused (draft lines are still editable/removable;
  open is inert — decisions wait for the checklist); PATCH on a line
  with sources / adjustment / catalog identity → 400 detail; un-decline
  works; non-manager → 403.
  Build the object graph the way `tests/test_hand_line_ac_validation.py`
  does. Run `tests.test_work_declined` — expect field/PATCH failures.
- [ ] **Step 2: implement** — model field + migration; serializer
  read+write; update-path carve-out (the frozen-line guard currently
  refuses ALL non-draft edits — add the narrow exception for a
  work_declined-only PATCH body). Wire the refusals in
  `EstimateService` (service-level, not view-level).
- [ ] **Step 3: GREEN**, then run the estimate line-item modules you
  touched (grep tests/ for the update-path suite) — no regressions.
- [ ] **Step 4: fresh-DB spot check** — `python manage.py test
  tests.test_work_declined --noinput` WITHOUT --keepdb once (migration
  sanity).
- [ ] **Step 5: commit** (`feat: work_declined mark on estimate lines`).

### Task 2: MintService (salvage, re-gated)

**Files:**
- Create: `apps/estimates/mint.py`  — start from
  `git show c231c8de:apps/estimates/plan_work.py`
- Test: `tests/test_mint_service.py` — start from
  `git show c231c8de:tests/test_plan_work_service.py`

**Deltas from the salvage source (apply exactly):**
1. Rename module/class: `MintService.claim_atom_for_line`, constant
   `MINT_STATUSES = (Estimate.STATUS_ACCEPTED,)` — **draft AND open are
   refused** (the salvage allowed both; the frozen-source rule forbids
   draft, and RM's leanest-pass trim keeps open inert).
2. New guard: refuse lines with catalog identity (`service_item_id` /
   `inventory_item_id` / `is_material`) — mint-by-modal is for plain
   hand lines; catalog lines crystallize (Task 4/acceptance). Refuse
   `work_declined` lines ("This line is marked as needing no work —
   un-mark it first.").
3. Keep the salvage's FINAL error shapes (plain-sentence/detail — the
   c231c8de head, not earlier field-keyed versions) and the CO-lens
   docstring caveat.
4. Tests: statuses-pin test asserts the new tuple `('accepted',)`;
   add draft-refused, OPEN-refused, declined-refused,
   catalog-identity-refused cases; keep dead-status/adjustment/
   cross-job/already-claimed/missing cases.
- [ ] TDD (RED on missing module → GREEN); run
  `tests.test_mint_service`; commit.

### Task 3: `claim_estimate_line` on task creation (salvage, tasks only)

**Files:**
- Modify: `apps/api/mixins.py` (JobTaskMixin.tasks POST) and
  `apps/api/jobs/views.py` (`add_from_template` + a module-level
  `_resolve_claim_line` helper) — start from
  `git show c231c8de:apps/api/mixins.py` /
  `git show c231c8de:apps/api/jobs/views.py` (diff those against the
  current files to isolate the claim-param hunks)
- Test: `tests/test_mint_api.py` — start from
  `git show c231c8de:tests/test_plan_work_api.py`

**Deltas:** import from `apps.estimates.mint`; **material create gets NO
param** (v1 mints tasks only — drop the create_material hunk and its
tests); the salvage's gate-first ordering, atomicity, int-guard, and
detail-shape errors carry over verbatim; status expectations in tests
flip (draft AND open → refused, accepted → succeed). Presence-gate stays
`CanManageJobOrPM`.
- [ ] TDD; run `tests.test_mint_api` + the job-task regression modules
  (`tests.test_api_tasks`, `tests.test_job_direct_tasks`); commit.

### Task 4: CUT (RM 2026-08-15 — leanest first pass)

Early catalog crystallization (per-line `crystallize_line` extraction +
post-send crystallize endpoint) was cut at plan review: catalog lines
crystallize only at acceptance, exactly as today. Nothing to implement;
this stub keeps task numbering stable for briefs/ledger. If pre-approval
earmarking pressure returns, the cut design is recorded in this plan's
git history.

### Task 5: answeredness + auto-release (replaces release-to-floor)

**Files:**
- Modify: `apps/estimates/services.py` (answeredness helper),
  `apps/jobs/services.py` (auto-release), `apps/estimates/signals.py`
  or the acceptance call site (trigger wiring)
- Test: `tests/test_auto_release.py`

**Interfaces (produces):**

```python
# apps/estimates/services.py
@staticmethod
def unanswered_lines(estimate):
    """Lines still owing a work decision on an ACCEPTED estimate:
    non-adjustment, non-deposit lines with no sources and
    work_declined=False. (Catalog-identity lines crystallize at accept
    and therefore carry sources by the time this is consulted.)"""

# apps/jobs/services.py
@staticmethod
def maybe_auto_release(job):
    """approved → in_progress (system transition) when the job's
    accepted estimate exists and unanswered_lines() is empty. Fires
    after acceptance, after each mint claim on an accepted estimate,
    and after each work_declined flip. Idempotent; does nothing for
    any other job status (on_hold, already in_progress, ...)."""
```

Wire the three triggers: end of `EstimateAcceptanceService.on_accept`
(covers all-catalog → releases at accept); `MintService.
claim_atom_for_line` when the estimate is accepted; the `work_declined`
PATCH path. Find deposit-line detection the way the existing pool/
serializer code does (`is_deposit` derivation) — do not invent a new
rule.

Tests (drive REAL transitions, then assert `job.status`):
all-catalog estimate → accept → job lands `in_progress` directly;
mixed estimate → accept → stays `approved` → mint one line → still
`approved` → decline the last → `in_progress`; all-declined (taskless)
→ releases; on_hold job: checklist completion does NOT release (hold
wins; release happens via the existing hold-release path — read
`hold_job`/`release_job` and assert the interaction you find, don't
assume). Also pin: `mark_work_started` unchanged.
- [ ] TDD; run `tests.test_auto_release` + the job-lifecycle modules
  (grep for approved→in_progress tests — they may assert the manual
  edge; update only genuinely-stale assertions); commit.

### Task 6: retire the manual release + remove agreement-side attach (frontend+backend trim)

**Files:**
- Modify: `frontend/src/components/jobs/JobHeader.svelte` — drop the
  `approved → in_progress` option from the status pill's offered
  transitions (the model edge stays for system/timeslip-start use);
  remove the now-dead `'Release to floor'` label branch.
- Modify: `frontend/src/components/estimates/EstimateEditView.svelte`
  and `frontend/src/components/changeorders/COEditView.svelte` — remove
  the "Add selected here" button + `addSelectedToLine` handler + the
  `add-atoms` call (estimate ~line 304, CO ~line 436). INVOICE stays
  (scoping decision above). The per-atom Remove on draft projected
  lines STAYS (dissolve-on-last is correct in this model — RM
  2026-08-15).
- Backend: block the manual PATCH `approved → in_progress` in
  `JobService.update_job` for non-system callers (same shape as the
  existing direct-approval gate — read that guard and mirror it), so
  the API matches the UI.
- Test: Vitest updates (JobHeader options, edit views' buttons);
  Django: extend `tests/test_auto_release.py` with the manual-edge
  block test.
- [ ] TDD both sides; full Vitest once; run the touched Django modules;
  commit.

### Task 7: mint + decline + checklist on the estimate surface

**Files:**
- Modify: `frontend/src/components/WorkItemForm.svelte` — salvage the
  `claimEstimateLine` + `presetQty` props from
  `git show c231c8de:frontend/src/components/WorkItemForm.svelte`
  (diff against current; take ONLY those prop hunks — not the
  MaterialModal ones).
- Modify: `frontend/src/components/estimates/EstimateEditView.svelte` +
  `EstimatePanel.svelte`:
  - `canMint = $derived(canManageJobs && estimate?.status === 'accepted')`.
  - On each UNANSWERED plain hand line (no sources, not declined, not
    adjustment/deposit/catalog-identity) when `canMint`:
    **"Generate work…"** (WorkItemForm, mode="manual", mirror-seeded:
    presetName=description, presetQty=qty, claimEstimateLine=line id;
    onSaved → onChanged) and **"No work needed"** (PATCH
    work_declined=true; no confirm — reversible).
  - Declined lines: small caption `no work needed` + an **Undo** button
    (PATCH false).
  - **Checklist banner** on an ACCEPTED estimate with unanswered lines:
    "N line(s) need a work decision — the job starts automatically when
    all are answered." (`.doc-warning` family styling.)
  - Actions column header/colspan gates grow `|| canMint` (audit every
    colspan fed by the condition — the AtomCaptionRow one included).
- Test: `frontend/tests/components/estimates/EstimateEditView.test.js`
  — button gating (per line-kind and per status), seeded modal props,
  decline+undo PATCH bodies, banner presence/count, colspan integrity;
  panel test for `canMint`.
- [ ] TDD; full Vitest; commit.

### Task 8: bundle modal (draft composition + keep-the-total)

**Files:**
- Backend: `apps/core/wizard.py` `add_atoms_to_new_line_item` — accept
  optional authored overrides:

```python
def add_atoms_to_new_line_item(cls, container, atoms, *, overrides=None):
    """overrides: optional {'description','qty','units','price'} applied
    over the derived defaults before save (bundle-modal authoring). A
    provided qty/price pair wins; partial overrides merge onto the
    derivation. Claims/atomicity unchanged."""
```
  Endpoint: the existing `line-items-from-atoms` action grows an
  optional `overrides` body key (draft-gated as today). Estimate + CO
  wrappers pass it through.
- Frontend: new `frontend/src/components/docsurface/BundleModal.svelte`
  (Modal shell): shows the selected atoms (kind/desc/qty/amount, the
  derived total), then authoring fields — description, qty, units,
  price — with **keep-total ON by default**: editing qty re-derives
  price = total ÷ qty (and vice versa), a visible "keep total
  $X" checkbox turns the coupling off. Create → POST with overrides →
  close + refresh. Replaces `NewLineFromSelectedRow` on the ESTIMATE
  and CO edit views (selection checkbox flow stays; the dashed row's
  action becomes "Bundle into line…" opening the modal). Invoice keeps
  its current flow.
- Test: Django — overrides merge/atomicity in the wizard tests
  (`tests/test_estimate_wizard*` neighborhood, new cases); Vitest —
  BundleModal math (keep-total both directions, toggle off), POST body,
  and the edit views' swap.
- [ ] TDD both sides; targeted Django modules + full Vitest; commit.

### Task 9: converter — checklist-consistent datasets

**Files:**
- Modify: `nealsdata/converter/build.py`; Test:
  `tests/test_neals_builders.py`

On converted jobs at `approved`/`in_progress`+: every plain hand line
(no synthetic sources, no catalog identity, non-adjustment, non-deposit)
on the accepted estimate gets `work_declined=True`, so no phantom
checklist items appear and auto-release invariants hold on regenerated
data. Invariant test: after conversion, no accepted estimate on an
approved+ job has unanswered lines. `nealsmall.json`/nealseed are
RM-managed — NEVER regenerate; `converted.json` is the regenerable
artifact (regenerate + run the fixture suite if the repo's converter
workflow does so — check how the last converter change was verified and
mirror it).
- [ ] TDD; run `tests.test_neals_builders` (mandatory) + the fixture
  suite used last time; commit.

### Task 10: e2e — the structure journey

**Files:** Create `e2e/specs/estimating-structure/mint-and-release.spec.js`
(follow `e2e/specs/change-orders/amend-in-place.spec.js` conventions:
build own job via API, personas, test.step, scoped selectors).

One journey: draft with a catalog service line + two hand lines + a
bundled projected line (BundleModal path: select pool atoms → Bundle
into line… → keep-total edit → create); assert "Add selected here"
absent; send (open) → assert the surface is inert (no Generate work /
No work needed anywhere); accept via API → checklist banner counts the
two hand lines; "Generate work…" on hand line A (mirror-seeded modal →
save → based-on caption, banner counts down); "No work needed" on B →
banner clears AND the job reads `in_progress` (auto-release; assert via
API + the header pill);
also assert the status pill no longer offers a manual approved →
in_progress option on a second approved job. Second short spec or step:
all-catalog estimate accepts straight to `in_progress`.
- [ ] Green twice consecutively; commit.

### Task 11: docs + checklist + full verification gate

**Files:** `docs/designs/estimates-and-prices.md` (the model: line
identities, mint/decline, checklist, MINT_STATUSES; supersede the
§12.1a-era text), `jobs-and-tasks.md` (auto-release replaces
release-to-floor; lifecycle section), `architecture-and-conventions.md`
(endpoints: crystallize, claim param, work_declined PATCH carve-out;
BundleModal in the docsurface table), `users-and-permissions.md`
(gates), `data-constraints.md` (work_declined field + answeredness
invariant), `docs/plans/2026-08-09-rm-review-checklist.md` (new
click-through section), `docs/designs/LATER.md` (resolve the
release-to-floor gating entry — settled by the checklist design; the
keep-total "lost gesture" entry — delivered at bundle-time, note
edit-time re-expression still open).
- [ ] Write docs; then the gate IN ORDER, one at a time:
  1. `cd frontend && npm run test:run` (full).
  2. Full Django suite, **FRESH DB (no --keepdb — this branch has a
     migration)**, `--noinput`, foreground-tracked, judged by the
     summary line only.
  3. `cd e2e && npx playwright test specs/estimating-structure/
     specs/invoice-skeleton/estimate-three-modes.spec.js
     specs/change-orders/amend-in-place.spec.js` (new + the two
     agreement-surface regressions — amend-in-place exercises the CO
     edit view the attach-removal touched).
  Record all three verbatim summary lines; fix only genuine branch
  breakage.
- [ ] Commit docs (+ fixes separately if any).

---

## Self-review notes (applied)

- Spec coverage: model→Tasks 2/3/7; timeline draft→8, open→inert (2's
  refusal tests), accept→5 + the checklist surface in 7 (Task 4 cut);
  auto-release→5/6; modals→7/8; removals→6; converter→9;
  fifteen-shapes: 1:1 mint (7), presets/materials (4 + acceptance),
  never-mint (decline, 1/7), deep (bundle, 8); compat→9 + Task 5's
  event-driven evaluation (pre-ship approved jobs simply never
  re-evaluate; converter makes regenerated data coherent; timeslip-start
  remains the safety valve).
- Mint modal interior: v1 is Save-&-close only (WorkItemForm as-is) +
  decline — per RM's "leave the multi-task details alone"; Save-&-add-
  another is NOT in this plan.
- Type consistency: `work_declined` (field/PATCH), `MINT_STATUSES`,
  `claim_estimate_line`, `overrides` — used consistently above.
- Deliberately absent: pool add/edit powers on the estimate page, any
  attach gesture, material mint param, draft minting, multi-task mint,
  checklist UI beyond the estimate surface (job-overview integration
  can ride a later pass).
