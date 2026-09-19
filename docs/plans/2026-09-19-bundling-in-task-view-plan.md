# Bundling in the Task View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move estimate-line composition (atom selection + bundling) from the estimate page to the job's Tasks page, with an explicit one-draft-estimate-per-job invariant underneath it.

**Architecture:** The bundle/pool backend stays estimate-scoped and unchanged (except the new model-level draft-uniqueness check). The Tasks page (`TasksPanel`) resolves the job's single live estimate client-side, fetches its source-pool when it's a draft, renders selection checkboxes on the existing `TaskRow`/`MaterialRow` fragments, and mounts the existing `BundleModal`. The estimate page loses its pool section and bundling affordances entirely. The CO and invoice surfaces are untouched.

**Tech Stack:** Django 5.2 + DRF (backend), Svelte 5 runes SPA (frontend), Django TestCase + Vitest + Playwright.

**Spec:** `docs/plans/2026-09-19-bundling-in-task-view.md` (RM decisions 2026-09-19).

## Global Constraints

- Branch: **feature/estimating** — commit there; never merge/push/PR.
- **NEVER write to the dev database** (no `migrate`, no shell ORM writes, no `loaddata`, no SQL writes; `makemigrations` OK, read-only SQL OK). Verify model behavior via tests only.
- Django tests: FOREGROUND single Bash call with a generous `timeout` param, always `--noinput`, never piped for pass/fail judgment — read the `Ran N tests` / `OK` / `FAILED` summary line. Never run Django tests from two agents at once. Targeted modules only (no full suite per task).
- Vitest: `cd frontend && npm run test:run` (never watch mode).
- E2E: `cd e2e && npx playwright test <spec>` (own DB/ports; dev servers can stay up).
- User-visible text must never say "atom", "wizard", or "blep" — say "tasks and materials"/"work", "Reconcile", "timeslip". Code/API identifiers keep the internal names.
- Error contract: services raise field-shaped `ValidationError({'field': [...]})` for input-field problems, sentence `ValidationError('...')` otherwise; frontend routes errors through `triageError`/`errorMessage` — never bare `e.message`, never `window.alert`.
- UI conventions: links navigate / buttons act; saves explicit (never blur-only); confirmations only for the irreversible; `<tr>` always inside `<tbody>`/`<thead>`.
- TDD per task; commit at each task's end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Existing model constants only (`Estimate.STATUS_DRAFT`, `Job.STATUS_SUBMITTED`, …) — no string literals.

---

### Task 1: One-draft-estimate-per-job invariant (backend)

**Files:**
- Modify: `apps/estimates/models.py` (inside `Estimate.clean()`, directly after the one-accepted-per-job block at ~lines 110-118)
- Create: `tests/test_estimate_draft_uniqueness.py`
- Modify: `docs/designs/data-constraints.md` (estimates section, beside the one-accepted-per-job entry)

**Interfaces:**
- Consumes: `Estimate.clean()` already runs on every save — `Estimate.save()` calls `self.full_clean()` (`models.py:162`), so `objects.create(...)` in all three creation sites is covered automatically.
- Produces: creating a second `draft` estimate for a job raises `ValidationError('Job <job_number> already has a draft estimate')` from every path, including `EstimateService.create_direct`.

Context: verified 2026-09-19 that the API already cannot produce two drafts (`create_for_job` guard + serializer re-check in `apps/api/estimates/views.py:88-99`; `revise_estimate` refuses draft parents and supersedes its parent). This task makes the invariant *declared* so `create_direct` (converter/tests) and any future path are bound too. Scope is draft-vs-draft ONLY — during `revise_estimate` an open/accepted parent legally coexists with the new draft child before the parent is superseded (child is created at `services.py:274`, parent superseded at `:323`), and a "one non-superseded" check would break that; a draft-only check never trips it because the parent is never draft there.

- [ ] **Step 1: Write the failing tests** in `tests/test_estimate_draft_uniqueness.py`:

```python
from django.core.exceptions import ValidationError
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from tests.base import BaseTestCase


class DraftEstimateUniquenessTests(BaseTestCase):
    # BaseTestCase provides job-creation helpers — follow the conventions
    # in neighboring tests (e.g. tests/test_estimate_create_and_claim_state.py)
    # for building the job.

    def test_second_draft_via_create_direct_is_refused(self):
        job = self._make_job()
        EstimateService.create_direct(job)
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.create_direct(job, version=2)  # distinct version so
            # the (estimate_number, version) uniqueness check isn't what fires
        self.assertIn('already has a draft estimate', str(ctx.exception))

    def test_second_draft_via_create_for_job_is_refused(self):
        job = self._make_job()
        EstimateService.create_for_job(job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.create_for_job(job.pk)

    def test_revise_open_estimate_still_works(self):
        # revise holds (open parent + draft child) transiently — must not trip.
        job = self._make_job()
        est = EstimateService.create_for_job(job.pk)
        # give it a line so draft -> open passes the has-line-items gate,
        # then transition and revise
        ...  # (use the same line-item + update_status helpers neighboring
             # revision tests use — see tests that call revise_estimate)
        new = EstimateService.revise_estimate(est.pk)
        self.assertEqual(new.status, Estimate.STATUS_DRAFT)
        est.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_SUPERSEDED)

    def test_draft_can_still_be_edited_and_saved(self):
        # the check must exclude self — resaving the only draft is fine.
        job = self._make_job()
        est = EstimateService.create_for_job(job.pk)
        est.terms = None
        est.save()  # must not raise
```

Find the exact job/line-item fixture helpers by reading `tests/test_estimate_create_and_claim_state.py` and one test module that exercises `revise_estimate` (grep `revise_estimate` under `tests/`); mirror their setup rather than inventing new fixtures.

Also pin the other state-C refusal (spec §7): bundling into a non-draft estimate must raise. First grep `tests/` for existing `_validate_draft` / bundle-on-non-draft coverage (likely in `tests/test_estimate_wizard_service.py`); if it already exists, note the test name in your report — if not, add one test here calling `EstimateWizardService.add_atoms_to_new_line_item` against an open estimate and asserting `ValidationError`.

- [ ] **Step 2: Run to verify the two refusal tests FAIL** (no such validation yet) and the two pass-through tests PASS:

Run: `python manage.py test tests.test_estimate_draft_uniqueness --noinput`
Expected: 2 failures ("ValidationError not raised"), 2 passes.

- [ ] **Step 3: Add the check to `Estimate.clean()`**, directly after the accepted-uniqueness block (same style):

```python
        # Only one draft estimate per job (RM 2026-09-19): the draft is the
        # only composable document, and the Tasks-page bundling flow resolves
        # "the job's draft" as a singleton. Draft-vs-draft only — during
        # revise_estimate a non-draft parent legally coexists with the new
        # draft child until the parent is superseded moments later.
        if self.status == Estimate.STATUS_DRAFT:
            existing_draft = Estimate.objects.filter(
                job=self.job,
                status=Estimate.STATUS_DRAFT
            ).exclude(pk=self.pk if self.pk else None)

            if existing_draft.exists():
                raise ValidationError(f'Job {self.job.job_number} already has a draft estimate')
```

- [ ] **Step 4: Run the new module + collateral modules:**

Run: `python manage.py test tests.test_estimate_draft_uniqueness tests.test_api_estimates tests.test_neals_builders --noinput`
(`test_neals_builders` is mandatory — the nealsdata converter uses `create_direct` and is the one caller that could hold multiple drafts per job.) Expected: all pass. If a converter builder genuinely creates two drafts on one job, STOP and report BLOCKED with the failing output — do not weaken the check.

- [ ] **Step 5: Document** in `docs/designs/data-constraints.md`: add a bullet beside the one-accepted-per-job constraint: one draft estimate per job, enforced in `Estimate.clean()` (clean-level like its accepted sibling — MySQL cannot express conditional unique constraints), verified to cover all creation paths because `Estimate.save()` calls `full_clean()`.

- [ ] **Step 6: Commit** — `feat: enforce one draft estimate per job at the model layer`

---

### Task 2: Tasks page estimate context — three states + "Start Estimate" offer

**Files:**
- Modify: `frontend/src/components/tasks/TasksPanel.svelte`
- Test: `frontend/tests/components/tasks/TasksPanel.test.js`

**Interfaces:**
- Consumes: `GET /api/estimates/?job={id}` (list with `.results`), `GET /api/estimates/{id}/source-pool/` (`{atoms: [{type, id, description, qty, units, rate, amount, worker_time?, state, claiming_change_order_number?, claiming_estimate_number?}, ...]}`), `POST /api/estimates/` with `{job}` (the exact call `EstimatePanel.svelte:331` makes), `job.can_manage`, existing `jobLocked`.
- Produces (state consumed by Tasks 3-4 — keep these exact names): `liveEstimate` ($state, the single non-superseded estimate or null), `draftEstimate` ($derived: `liveEstimate?.status === 'draft' ? liveEstimate : null`), `sourcePool` ($state, pool payload when `draftEstimate` else null), `canBundle` ($derived boolean), `loadEstimateContext()` (async refetch of both).

- [ ] **Step 1: Write failing Vitest cases** in the existing `TasksPanel.test.js` (follow its established mock/render harness — read it first and extend, don't restructure). Cases:

```js
// State A: estimates list returns one draft -> a "Bundling into estimate
// <number> (draft)" context line renders with a link to
// `#/jobs/<id>/estimate`, and NO "Start Estimate" button.
// State B: estimates list empty + job.status 'draft' + can_manage ->
// "Start Estimate" button renders; clicking it POSTs /api/estimates/
// with {job: <id>} and then shows the state-A context line.
// State C: estimates list returns one 'accepted' row -> neither the
// context line nor "Start Estimate" renders.
// State C': estimates list empty but job.status 'approved' -> no offer.
// Permission: state B but can_manage false -> no offer.
```

Mock `api.get` per-URL (the panel also fetches expenses/service-items/categories/settings — the existing tests already stub those).

- [ ] **Step 2: Run to verify they fail:** `cd frontend && npm run test:run -- tests/components/tasks/TasksPanel.test.js` — new cases FAIL (elements absent).

- [ ] **Step 3: Implement in `TasksPanel.svelte`:**

```js
  import { showError, showSuccess } from '../../stores/messages.js'; // showError already imported

  let liveEstimate = $state(null);
  let sourcePool = $state(null);
  let estimateContextLoaded = $state(false);

  const draftEstimate = $derived(
    liveEstimate?.status === 'draft' ? liveEstimate : null);
  const canBundle = $derived(
    !!draftEstimate && !!job?.can_manage && !jobLocked && !job?.on_hold);
  const canOfferEstimate = $derived(
    estimateContextLoaded && !liveEstimate && !!job?.can_manage && !jobLocked
    && ['draft', 'submitted'].includes(job?.status));

  // The job has at most one non-superseded estimate (enforced in
  // Estimate.clean() + create_for_job) — .find() is exact, not heuristic.
  async function loadEstimateContext() {
    try {
      const resp = await api.get(`/api/estimates/?job=${job.job_id}&page_size=100`);
      const rows = resp.results ?? resp;
      liveEstimate = rows.find((e) => e.status !== 'superseded') ?? null;
      sourcePool = liveEstimate?.status === 'draft'
        ? await api.get(`/api/estimates/${liveEstimate.estimate_id}/source-pool/`)
        : null;
    } catch (e) {
      liveEstimate = null;
      sourcePool = null;
    } finally {
      estimateContextLoaded = true;
    }
  }

  async function handleStartEstimate() {
    try {
      const est = await api.post('/api/estimates/', { job: job.job_id });
      showSuccess(`Estimate ${est.estimate_number} started.`);
      await loadEstimateContext();
    } catch (e) {
      showError(errorMessage(e, 'Could not start an estimate.'));
    }
  }
```

Call `await loadEstimateContext()` from `loadPanelData()` (so every job-prop refresh re-resolves it). Check the estimate list serializer's id field name (`estimate_id`) against what `JobEstimatePage.svelte` reads — use whatever the serializer actually emits.

Toolbar additions (inside the existing `.toolbar` div, after "Add Expense"):

```svelte
    {#if canOfferEstimate}
      <button type="button" onclick={handleStartEstimate}>Start Estimate</button>
    {/if}
  </div>
  {#if draftEstimate}
    <p class="estimate-context">
      Bundling into estimate {draftEstimate.estimate_number} (draft) —
      <a href={`#/jobs/${job.job_id}/estimate`}>view</a>
    </p>
  {/if}
```

(Verify the estimate page's actual route by reading `App.svelte`'s route table / how the jobs sidebar links to the estimate section; use that exact href.) Style `.estimate-context` as a small dim line under the toolbar.

- [ ] **Step 4: Run the file's tests, then the full Vitest suite:** `cd frontend && npm run test:run` — all pass.

- [ ] **Step 5: Commit** — `feat: Tasks page resolves estimate context (three states + Start Estimate offer)`

---

### Task 3: Selection checkboxes on task and material rows

**Files:**
- Modify: `frontend/src/components/tasks/TasksPanel.svelte`
- Modify: `frontend/src/components/TaskTree.svelte`
- Modify: `frontend/src/components/tasks/TaskRow.svelte`
- Modify: `frontend/src/components/materials/MaterialRow.svelte`
- Test: `frontend/tests/components/tasks/TasksPanel.test.js` (integration-level; add row-level cases to existing TaskRow/MaterialRow test files if present — check `frontend/tests/components/` for them)

**Interfaces:**
- Consumes from Task 2: `sourcePool`, `canBundle`.
- Produces for Task 4 (exact names): in `TasksPanel` — `selected` ($state array of `"task:12"` / `"material:5"` ids, same convention as `EstimateEditView.svelte:146-156`), `poolByKey` ($derived Map from `"type:id"` → pool atom), `toggleBundleSelect(key)`. New TaskTree props: `bundleMode` (bool), `poolByKey` (Map), `bundleSelected` (array), `onToggleBundle(key)`. New TaskRow/MaterialRow props: `bundleMode = false`, `bundleAtom = null`, `bundleChecked = false`, `onToggleBundle = null`.

- [ ] **Step 1: Failing tests.** In `TasksPanel.test.js`: with state A and a pool containing one `available` task, one `claimed_by_current` task, one `claimed_by_other` material (with `claiming_change_order_number`), and one task absent from the pool — assert: exactly one enabled checkbox; the claimed_by_current row shows the text "estimated"; the claimed_by_other row's checkbox is disabled with a `title` of `Claimed by change order N`; the absent row has no checkbox; with state C (`canBundle` false) no checkboxes render at all. Run to verify FAIL.

- [ ] **Step 2: TasksPanel selection state:**

```js
  let selected = $state([]);
  const poolByKey = $derived.by(() => {
    const map = new Map();
    for (const a of (sourcePool?.atoms || [])) map.set(`${a.type}:${a.id}`, a);
    return map;
  });
  function toggleBundleSelect(key) {
    selected = selected.includes(key)
      ? selected.filter((k) => k !== key)
      : [...selected, key];
  }
```

Clear stale selection whenever the pool reloads: at the end of `loadEstimateContext()`, drop selected ids whose pool atom is no longer `available`:
`selected = selected.filter((k) => poolByKey.get(k)?.state === 'available');`
(Note `poolByKey` is $derived — read it after `sourcePool` is assigned; if derived timing is awkward inside the async function, build a plain local map there instead.)

Pass to TaskTree: `bundleMode={canBundle}` `{poolByKey}` `bundleSelected={selected}` `onToggleBundle={toggleBundleSelect}`.

- [ ] **Step 3: TaskTree plumbing.** Add the four props (defaults: `bundleMode = false, poolByKey = null, bundleSelected = [], onToggleBundle = () => {}`). Add `+ (bundleMode ? 1 : 0)` to `colCount` (`TaskTree.svelte:84`). Add a leading header cell before the move-cell header when `bundleMode`: `<th class="bundle-cell" aria-label="Select for bundling"></th>`. For each `TaskRow` pass `bundleMode`, `bundleAtom={poolByKey?.get(`task:${task.task_id}`) ?? null}`, `bundleChecked={bundleSelected.includes(`task:${task.task_id}`)}`, `onToggleBundle={() => onToggleBundle(`task:${task.task_id}`)}`; same for both `MaterialRow` render sites with `material:${mat.material_id}`. The expense-row snippet and the `job-materials-header` / `Expenses` header rows need a leading empty `<td>` when `bundleMode` (header rows use `colspan={colCount}` so they're already covered — only the snippet's explicit cells need the extra `<td>`).

- [ ] **Step 4: Row cells.** In `TaskRow.svelte`, as the FIRST cell (before the move-cell), mirror the move-cell pattern (`TaskRow` renders `<tr>` directly):

```svelte
{#if bundleMode}
  <td class="bundle-cell">
    {#if bundleAtom?.state === 'available'}
      <input type="checkbox" checked={bundleChecked}
             onchange={onToggleBundle}
             aria-label={`Select ${task.name} for bundling`}>
    {:else if bundleAtom?.state === 'claimed_by_current'}
      <span class="bundle-claimed" title="Already on the draft estimate">estimated</span>
    {:else if bundleAtom?.state === 'claimed_by_other'}
      <input type="checkbox" disabled title={bundleClaimNote(bundleAtom)}>
    {/if}
  </td>
{/if}
```

with the note helper copied from `EstimateEditView.svelte:162-168`'s logic:

```js
  function bundleClaimNote(atom) {
    if (atom.claiming_change_order_number) {
      return `Claimed by change order ${atom.claiming_change_order_number}`;
    }
    return `Claimed by estimate ${atom.claiming_estimate_number || ''}`.trim();
  }
```

Style `.bundle-cell` like `.move-cell` (24px, centered) and `.bundle-claimed` as an 11px dim italic chip. Same cell block in `MaterialRow.svelte` (its `<tr>` — put the cell first, matching its `taskAligned` leading-cell order; check where MaterialRow renders its move-cell filler and keep the new cell aligned with TaskRow's). User-visible text here must not say "atom".

- [ ] **Step 5: Run Vitest (file, then full):** `cd frontend && npm run test:run` — all pass. Fix the TaskTree-consuming surfaces if the new leading column broke any other test (TaskDetailPage uses MaterialRow with `taskAligned={false}` — bundleMode defaults false there, so no cell renders).

- [ ] **Step 6: Commit** — `feat: bundle-selection checkboxes on task/material rows (Tasks page)`

---

### Task 4: Bundle CTA + BundleModal on the Tasks page

**Files:**
- Modify: `frontend/src/components/tasks/TasksPanel.svelte`
- Test: `frontend/tests/components/tasks/TasksPanel.test.js`

**Interfaces:**
- Consumes from Tasks 2-3: `selected`, `sourcePool`, `draftEstimate`, `canBundle`, `loadEstimateContext()`, `reload()`.
- Consumes component: `BundleModal` (`frontend/src/components/docsurface/BundleModal.svelte`) with props `{open, atoms, apiBase, onCreated, onConflict, onClose}` — `atoms` takes RAW pool atoms (`sourcePool.atoms` entries, NOT reshaped rows); `apiBase` = `/api/estimates/${draftEstimate.estimate_id}`. BundleModal owns the POST; the host owns 409 handling (see `BundleModal.svelte:49-52`).

- [ ] **Step 1: Failing tests.** Cases: (a) state A with 2 selected → toolbar shows an enabled "Bundle 2 selected into a line…" button; 0 selected → button disabled; (b) clicking it opens BundleModal (assert via the modal's `bundle-preview` testid or its heading); (c) simulate `onCreated` → selection clears and the pool + job refetch (assert the api.get mocks were re-called); (d) simulate `onConflict` with a 409 error object → error overlay message shown, selection cleared, pool refetched. Run to verify FAIL.

- [ ] **Step 2: Implement.** Import BundleModal. Toolbar (inside state A, next to the context line from Task 2):

```svelte
    {#if canBundle}
      <button type="button" disabled={selected.length === 0}
              onclick={() => { bundleModalOpen = true; }}>
        Bundle {selected.length} selected into a line…
      </button>
    {/if}
```

```js
  let bundleModalOpen = $state(false);
  const bundleAtoms = $derived(
    (sourcePool?.atoms || []).filter((a) => selected.includes(`${a.type}:${a.id}`)));

  async function refreshAfterBundle() {
    selected = [];
    await Promise.all([reload(), loadEstimateContext()]);
    // reload() refetches the job (a per-unit bundle stamps atom totals, so
    // task rows change); loadEstimateContext() refetches the pool.
  }
  async function handleBundleCreated() {
    bundleModalOpen = false;
    const estNumber = draftEstimate?.estimate_number;
    await refreshAfterBundle();
    showSuccess(`Line added to estimate ${estNumber} (draft).`);
  }
  async function handleBundleConflict(e) {
    bundleModalOpen = false;
    selected = [];
    await Promise.all([reload(), loadEstimateContext()]);
    showError(errorMessage(e,
      'Some of the selected work was claimed elsewhere in the meantime — refreshed.'));
  }
```

Mount at the end of the modals block:

```svelte
  <BundleModal
    open={bundleModalOpen}
    atoms={bundleAtoms}
    apiBase={draftEstimate ? `/api/estimates/${draftEstimate.estimate_id}` : ''}
    onCreated={handleBundleCreated}
    onConflict={handleBundleConflict}
    onClose={() => { bundleModalOpen = false; }}
  />
```

- [ ] **Step 3: Run Vitest (full):** `cd frontend && npm run test:run` — all pass.

- [ ] **Step 4: Manual smoke note.** Do NOT touch the dev DB; just confirm the dev build compiles (`cd frontend && npm run build`). Expected: build succeeds.

- [ ] **Step 5: Commit** — `feat: bundle selected work into estimate lines from the Tasks page`

---

### Task 5: Estimate page reductions

**Files:**
- Modify: `frontend/src/components/estimates/EstimateEditView.svelte`
- Modify: `frontend/src/components/estimates/EstimatePanel.svelte`
- Modify: `docs/designs/LATER.md`
- Test: `frontend/tests/components/estimates/EstimateEditView.test.js`, `frontend/tests/components/estimates/EstimatePanel.test.js`

**Interfaces:**
- Consumes: nothing from Tasks 2-4 (pure removal; independent besides UX continuity).
- Produces: `EstimateEditView` no longer accepts/uses a `sourcePool` prop; `EstimatePanel` no longer fetches `/source-pool/`. `COEditView`, `ChangeOrderPanel`, `InvoiceEditView`, and the shared `UncoveredWorkSection`/`NewLineFromSelectedRow`/`BundleModal` components are NOT touched.

- [ ] **Step 1: Update the tests first.** In `EstimateEditView.test.js`: delete/repoint cases that exercise the pool list, selection, "Bundle into line…", direct "Add as its own line", and bundle-conflict handling from this surface (that behavior now lives in `TasksPanel.test.js` — verify it's covered there before deleting, don't orphan coverage). Add: a draft estimate with zero line items renders a hint containing "Compose lines from the Tasks page" as a link to `#/jobs/{jobId}/tasks`. In `EstimatePanel.test.js`: drop source-pool fetch expectations. Run to verify the new empty-state case FAILS.

- [ ] **Step 2: `EstimateEditView.svelte` removals.** Remove: the `UncoveredWorkSection`, `NewLineFromSelectedRow`, and `BundleModal` imports and their markup (`:465-469`, `:474-498`, `:548-555` — re-locate by content, lines have drifted); `selected`, `atomRowId`, `parseSelected`, `unselectableNote`, `uncoveredRows`, `bundleModalOpen`, `bundleAtoms`, `openBundleModal`, `handleBundleCreated`, `handleBundleConflict`, `billDirect`; the `sourcePool` prop. KEEP `handleMutationError` (still used by `removeAtomFromLine` and other line mutations) but delete its `selected = [];` line. Add the empty-state hint where the line-items table renders with no rows (edit mode only):

```svelte
  {#if canEdit && lineItems.length === 0}
    <p class="empty-hint">
      No line items yet — <a href={`#/jobs/${jobId}/tasks`}>compose lines
      from the Tasks page</a> by selecting work and bundling it.
    </p>
  {/if}
```

(`jobId`: check what the view already knows — it may need `estimate.job` or a prop EstimatePanel already has; wire whichever exists rather than adding an API call.)

- [ ] **Step 3: `EstimatePanel.svelte` removals.** Remove `sourcePool` state, `loadSourcePool()`, the pool half of `handleEditChanged()` (keep the silent estimate reload), and the `{sourcePool}` prop pass. First grep the panel for other `sourcePool` consumers (the mint flow must NOT depend on it — verify by grep, and leave the mint wiring alone).

- [ ] **Step 4: LATER.md entry** (Estimates section): `send-all-atoms` endpoint (`POST /api/estimates/{id}/send-all-atoms/`, `apps/api/estimates/views.py:186-193`) is retained but has had no UI link since 2026-09-19's Tasks-page bundling move (verified zero frontend/e2e references even before it) — RM to keep-or-kill after using the new flow. _Done when:_ RM rules and the endpoint is either wired into the Tasks page or deleted with its service method.

- [ ] **Step 5: Run Vitest (full):** `cd frontend && npm run test:run` — all pass, including the untouched COEditView/InvoiceEditView suites (they share the components; their tests prove the components still work).

- [ ] **Step 6: Commit** — `feat: estimate page is document-only — pool and bundling affordances removed`

---

### Task 6: E2E migration — bundling journeys move to the Tasks page

**Files:**
- Modify: `e2e/specs/per-unit-lines/plan-first.spec.js`, `e2e/specs/per-unit-lines/split-materials.spec.js`, `e2e/specs/per-unit-lines/drift-revert.spec.js`
- Modify: `e2e/specs/invoice-skeleton/estimate-three-modes.spec.js`, `e2e/specs/estimating-structure/mint-and-release.spec.js`
- Verify-only: `e2e/specs/change-orders/amend-in-place.spec.js` (CO-page bundling — must stay untouched and green)
- Possibly create: a shared helper (e.g. `e2e/lib/bundling.js`) if the same select-on-tasks-page → CTA → modal sequence repeats across 3+ specs — follow the existing `e2e/lib` conventions.

**Interfaces:**
- Consumes: the Task 2-4 UI (Tasks page at `#/jobs/{id}/tasks`: row checkboxes, "Bundle N selected into a line…" button, BundleModal unchanged inside).
- Produces: all five affected specs green against the new surface.

- [ ] **Step 1: Audit.** For each of the five specs, identify every step that (a) visits the estimate page to select pool rows / click "Bundle into line…" / "Add as its own line", vs (b) seeds lines via `apiAs(...)` POSTs to `line-items-from-atoms` (API seeding is UNAFFECTED — leave it). `drift-revert.spec.js` greps 0 for "Bundle into" — confirm whether it bundles via API (then untouched) or another label. Write the audit as a comment in your report file, not in the specs.
- [ ] **Step 2: Rewrite the UI-bundling steps**: navigate to `#/jobs/{id}/tasks`, check the named rows' bundle checkboxes (target via row text + `input[type=checkbox]` in the bundle cell — add a `data-testid="bundle-select"` to the checkbox in `TaskRow`/`MaterialRow` if role/text targeting is brittle, matching how the specs already target `bundle-preview`), click the toolbar CTA, drive the (unchanged) BundleModal exactly as before. Where a spec previously asserted pool-row disappearance on the estimate page, assert instead the row's "estimated" chip on the Tasks page and the new line on the estimate page.
- [ ] **Step 3: Run the touched suites:** `cd e2e && npx playwright test specs/per-unit-lines specs/invoice-skeleton/estimate-three-modes.spec.js specs/estimating-structure/mint-and-release.spec.js specs/change-orders/amend-in-place.spec.js` — all green. (Foreground, generous timeout; judge by the Playwright summary line.)
- [ ] **Step 4: Commit** — `test(e2e): bundling journeys drive the Tasks-page flow`

---

### Task 7: E2E — new coverage for states B and C

**Files:**
- Create: `e2e/specs/task-view-bundling/start-estimate-offer.spec.js`

**Interfaces:**
- Consumes: Task 2's UI ("Start Estimate" button, context line, affordance gating) and the existing e2e persona/seed conventions (read a per-unit spec for the harness shape: personas, `apiAs`, `test.step`).

- [ ] **Step 1: Write the spec**, three journeys in one file:
  1. **State B → A:** seed a fresh draft job with two tasks via API; visit `#/jobs/{id}/tasks` as a manager persona; assert no checkboxes and no bundle CTA; assert "Start Estimate" visible; click it; assert the "Bundling into estimate" context line, checkboxes now present; bundle one task via the modal; assert the line exists via API read of the estimate.
  2. **State C (accepted):** seed a job whose estimate is accepted (reuse the acceptance seeding an existing spec uses — grep `accept` under `e2e/specs/estimating-structure/`); visit the Tasks page; assert NO checkboxes, NO bundle CTA, NO "Start Estimate".
  3. **State C (no room):** job past estimating (e.g. approved via the accepted path — the same seeded job can serve both if statuses fit; otherwise seed distinctly); assert no offer.
- [ ] **Step 2: Run it:** `cd e2e && npx playwright test specs/task-view-bundling` — green.
- [ ] **Step 3: Commit** — `test(e2e): Start Estimate offer and no-affordance states on the Tasks page`

---

### Task 8: Durable docs

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (the wizard/composition sections — pool + bundling surface)
- Modify: `docs/designs/jobs-and-tasks.md` (Tasks page section)

**Interfaces:** none — documentation of Tasks 1-7 as shipped.

- [ ] **Step 1: `estimates-and-prices.md`:** update the composition narrative: the estimate page is document-only (line editing, drift/Revert, adjustments, mint flow); the pool + bundle UI lives on the job's Tasks page targeting the job's single draft estimate; "Add as its own line" (direct bill) is removed; `send-all-atoms` endpoint retained but unlinked (LATER.md); CO composition unchanged on the CO page. Record the one-draft-per-job invariant with a pointer to data-constraints.md.
- [ ] **Step 2: `jobs-and-tasks.md`:** document the Tasks-page bundling surface: three states (draft → affordances; no estimate + job draft/submitted → "Start Estimate" offer; otherwise none), row checkboxes/indicators, the toolbar CTA, context line, post-bundle refresh semantics (per-unit bundles restamp task totals in place).
- [ ] **Step 3: Verify claims against code** (each statement you write must name behavior that exists at HEAD — re-read the shipped components, not the plan).
- [ ] **Step 4: Commit** — `docs: bundling-in-task-view surface + one-draft invariant`

---

## Execution notes (controller)

- Task order is 1 → 8 as written; 2-4 are sequential (shared state names in one file); 5 may run after 4 (never before — the e2e suite in between would have no bundling surface at all); 6-7 require 2-5 complete.
- Only ONE agent runs Django or Playwright tests at a time; e2e runs are foreground with a generous timeout.
- Best-guess decisions already made and tracked in spec §8 — implementers should not re-litigate them, and new ambiguities get a controller ruling + a spec §8 addition, not an improvisation.
