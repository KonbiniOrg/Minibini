# Bundling moves to the Task view

RM decisions 2026-09-19. Precedes (and reshapes the surface for) the
RM-gated bundle-modal restructure phase (per-unit-lines spec §12 "modal UI
refinement is the LAST phase") — that phase will land on the surface this
spec builds.

## 1. Intent

Line composition (selecting job atoms and bundling them into estimate line
items) happens in the **Tasks area**, not the estimate page. The workflow:
make a set of tasks → bundle them into a line → make the next set → bundle
those → … Then visit the Estimate page to adjust the document. The user can
go back and forth at any time, but *bundling* lives in the Task view.

The estimate page becomes document-only: line items, line editing,
remove-atoms, per-unit drift/Revert, adjustments, reordering, mint flow
("Generate work…"), customer view. The unclaimed-atom pool list and every
bundling affordance leave it.

**Change orders are untouched** (RM: "leave CO as is for now, I need to
work through that in the UI to decide"). The CO edit page keeps its pool +
bundle components exactly as today. `UncoveredWorkSection`,
`NewLineFromSelectedRow`, and `BundleModal` remain shared components — only
the *estimate page's* usage moves/dies.

## 2. Invariant made explicit: one draft estimate per job

Verified 2026-09-19: the API cannot produce two live estimates on one job —
`EstimateService.create_for_job` refuses when any non-superseded estimate
exists (and the API create path re-checks in the serializer),
`revise_estimate` refuses draft parents and supersedes its parent in the
same transaction, and the status map has no transition *into* draft. The
only unguarded creation site is `EstimateService.create_direct`, which has
no API callers (tests + nealsdata converter only).

Make the invariant explicit at the model layer: **only one `draft`
estimate per job**, enforced next to (and in the same mechanism as) the
existing one-`accepted`-per-job check in `Estimate.clean()`
(`apps/estimates/models.py:110-118`). Scope it to draft-vs-draft — NOT
"one non-superseded" — because `revise_estimate` legitimately holds
(open/accepted parent + new draft child) inside its transaction before the
parent is superseded; the parent there is never draft, so a draft-only
check never trips that flow.

The check must actually fire on every creation path, including
`create_direct` — the implementer must verify where `clean()` runs today
(the accepted-uniqueness check is the precedent to match; if it only fires
via `full_clean()` callers, `create_direct` and the create services should
be brought under it the same way the accepted check is enforced — same
layer, same style). MySQL cannot express a conditional unique constraint,
so clean-level is the ceiling, matching the accepted check.

Converter caveat: nealsdata builders use `create_direct`; run
`tests.test_neals_builders` after adding the check.

Document in `docs/designs/data-constraints.md` (alongside the existing
one-accepted-per-job entry).

## 3. Task page: three states

The Tasks page (`/jobs/:jobId/tasks`, `TasksPanel.svelte`) resolves the
job's **live estimate**: fetch `/api/estimates/?job={id}` and take the
single non-superseded row (§2 guarantees at most one). Three states:

**A. A draft estimate exists** → bundling affordances are live (§4),
targeting that draft.

**B. No draft, but room for one** — the job's status allows estimate
creation. The room test is *exactly* `create_for_job`'s own gate: job
status in (`draft`, `submitted`). No bundling affordances; instead an
explicit **"Start estimate"** offer (toolbar button beside "Add Work").
Clicking it POSTs `/api/estimates/` with `{job}` (the existing endpoint
`EstimatePanel.svelte:331` already uses) and, on success, the bundling
affordances appear in place — the user stays on the Tasks page. Creation is
always explicit; bundling never auto-creates an estimate.

**C. No draft, no room** (live estimate is open/accepted/rejected/expired,
or the job is past the estimating phase) → **no bundling UI at all** — no
checkboxes, no CTA, no create offer. Backend already rejects: the bundle
endpoint is estimate-scoped and `_validate_draft` refuses non-draft
containers server-side; §2's serializer guard refuses a second estimate.
No new backend rejection is needed — a backend test pinning both refusals
is.

All bundling affordances additionally require the same permission the
bundle endpoint enforces (`CanManageJobOrPM` → `job.can_manage` flag) and
a job that isn't locked (`completed`/`cancelled`/`rejected` — the panel's
existing `jobLocked`) or on hold.

## 4. Selection and bundling in the Task view

No transplanted pool list — the task tree IS the list (RM: "the Task UI
will be different enough"). Selection happens on the actual rows:

- **Data source:** when state A holds, `TasksPanel` fetches
  `GET /api/estimates/{draftId}/source-pool/` alongside the job and keys
  the pool atoms by `(type, id)`. The pool drives selectability, claim
  notes, and the raw atom objects handed to `BundleModal` (which needs the
  pool shape: `{type, id, description, qty, units, rate, amount,
  worker_time}`).
- **Checkboxes** on task rows and material rows (`TaskRow` /
  `MaterialRow`, in a new leading column like the existing move-material
  radio column), rendered only in state A. Enabled when the atom's pool
  state is `available`. Atoms claimed by the current draft show a passive
  "estimated" indicator instead of a checkbox; atoms claimed by a change
  order show the pool's note ("Claimed by change order N") as a disabled
  tooltip/title. Rows with no pool entry (cancelled tasks, released
  materials) get neither.
- **CTA:** a toolbar button — "Bundle N selected into a line…" — enabled
  when the selection is non-empty. Opens the existing `BundleModal`
  (mounted in `TasksPanel`) with `apiBase = /api/estimates/{draftId}`.
  Selection state lives in `TasksPanel` (same `"task:12"` /
  `"material:5"` row-id convention as `EstimateEditView` today).
- **409 handling:** the `atoms_already_claimed` conflict pattern moves
  with the caller — on conflict, reload the pool, clear the stale
  selection, and surface the message (copy the handling from
  `EstimateEditView.svelte:188-196`; BundleModal deliberately doesn't own
  it).
- **After a successful bundle:** clear selection, reload the pool AND the
  job (a per-unit bundle stamps atom totals — task rows visibly change),
  and show a success overlay naming the line landed on the draft estimate,
  with a link to the estimate page.
- Expense rows and the mint/claim flows are unaffected.

## 5. Estimate page reductions

In `EstimateEditView.svelte`:

- Remove the pool section (`UncoveredWorkSection` usage + `cw-tasks`
  wrapper), the `selected` state, `NewLineFromSelectedRow`, the
  `BundleModal` mount and its handlers, and the 409-conflict handler that
  served them.
- Remove `billDirect` (the per-row "Add as its own line" gesture) —
  dropped entirely, not relocated (RM 2026-09-19).
- `EstimatePanel` stops fetching/passing `sourcePool` for the edit view.
- Empty-state: a draft estimate with no line items shows a hint linking to
  the job's Tasks page ("Compose lines from the Tasks page").
- Everything else stays: line editing, per-line remove-atoms, drift
  badges/DriftModal, adjustments, reorder, mint flow, customer view.
- `COEditView` and `InvoiceEditView` keep their current use of the shared
  components — untouched.

**send-all-atoms:** `POST /api/estimates/{id}/send-all-atoms/` is already
UI-unlinked (verified 2026-09-19: zero frontend/e2e references). Retain
the endpoint + service untouched; RM decides its fate after using the new
flow (LATER.md entry).

## 6. Backend surface

No new endpoints. The pool and bundle endpoints stay estimate-scoped; the
Tasks page resolves the draft estimate client-side (§3). §2's model check
is the only backend behavior change.

## 7. Tests

- **Backend:** draft-uniqueness tests (second draft refused on every
  creation path incl. `create_direct`; `revise_estimate` unaffected;
  accepted+draft coexistence during revise unaffected). Pin the state-C
  refusals (bundle into non-draft, create over live estimate). Run
  `tests.test_neals_builders`.
- **Vitest:** `TasksPanel` three-state logic + create-offer + selection +
  bundle CTA + 409; `TaskRow`/`MaterialRow` checkbox/indicator rendering;
  `EstimateEditView` tests updated for the removals (pool-related tests
  move conceptually to the task side, don't just delete coverage).
- **E2E:** bundling journeys move to the Tasks page. Affected specs
  (grep-verified): `per-unit-lines/plan-first`, `per-unit-lines/
  split-materials`, `per-unit-lines/drift-revert` (bundles via UI or API —
  audit), `invoice-skeleton/estimate-three-modes`,
  `estimating-structure/mint-and-release` — each bundles through the
  estimate page today and must be rewritten to select-on-task-rows →
  toolbar CTA → modal. `change-orders/amend-in-place` bundles on the CO
  page — verify it's unaffected and leave it. New e2e coverage: the
  "Start estimate" offer (state B) and the no-affordance state (state C).

## 8. Best-guess decisions tracked for RM review

Made without RM input (RM 2026-09-19: "make your best guess and track it"):

1. Selection commits from a **toolbar button** (with count), not a sticky
   bar or in-table CTA row.
2. Checkbox column placement mirrors the move-material radio column
   (leading, headerless).
3. Claimed-by-current-draft rows show a passive "estimated" chip; wording
   TBD by RM in the browser.
4. Post-bundle feedback is a success overlay (text only, no
   auto-navigation); navigation to the document comes from a persistent
   context line shown in state A — "Bundling into estimate N (draft) —
   view" — beside the toolbar, since the success overlay is text-only.
5. "Start estimate" button label/placement (toolbar, beside "Add Work").
6. State B's "room" test is job status ∈ {draft, submitted} — exactly
   `create_for_job`'s gate, no wider.
7. send-all-atoms stays parked (already unlinked); LATER.md entry for the
   keep-or-kill decision.
