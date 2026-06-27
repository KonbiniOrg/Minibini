# Phase 3 — UI vocabulary + the single-view Estimate pillar

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> See `docs/plans/2026-06-24-planning-billing-consolidation-draft.md` (the design
> draft, §2/§8/§13) for the why. This is design-draft §14 step 3.

**Goal:** Apply the agreed UI vocabulary and rebuild the job overview's *two*
estimate-related sections (worksheets + estimates) into **one "Estimate" pillar**
that shows a single view at a time via a **`[ Plan | Client View ]` toggle**
(default by lifecycle), with **Open Estimate** when a Plan already exists (the bit
deferred from Phase 2). Backend object/db names stay; this is UI labels + a
frontend restructure.

**Vocabulary (UI labels only — backend keeps `EstWorksheet`/`Estimate`/wizard):**
- **Estimate** = the whole pillar/object. **Plan** = the build view (`EstWorksheet`,
  `/worksheets/{id}`). **Client View** = the send view (`Estimate`,
  `/estimates/{id}`). **Price List** = the add picker (done in Phase 1).
- Projection verbs: "Send all atoms to estimate" → **Show Client View**; the
  wizard / grouping → **Customize Client View**.

**Depends on:** Phase 2 (Start Estimate / the Plan entry). **Intersects** the
user's own modal/process rework — confirm with them before executing so we don't
collide on JobDetail.

## Global constraints
- Frontend-only (UI labels + JobDetail restructure). No backend object/db renames
  (deferred to a final naming pass), no model changes, no migrations.
- Svelte 5 runes; reuse existing components; never write the dev DB. Tests:
  `cd frontend && npm run test:run`.
- Don't change route paths, API URLs, or field keys — display strings only.

## Reference (from exploration)
- `frontend/src/components/jobs/JobDetail.svelte`: accordion `VALID_SECTIONS =
  ['worksheets','estimates','tasks','materials','invoices','shipments','pos']`
  (~L468); worksheets section (~L545–650), estimates+COs section (~L652–750+) with a
  `versionTimeline` (estimate versions then COs); `currentWorksheet` (~L233),
  `displayedEstimate` (~L52/83); the "Start Estimate" button (Phase 2, in the
  estimates section).
- `frontend/src/routes/worksheets/WorksheetDetailPage.svelte` = the Plan build view.
- `frontend/src/routes/estimates/EstimateDetailPage.svelte` = the Client View
  (status/send/line items); links to the wizard at `/estimates/{id}/wizard`.
- `frontend/src/routes/estimates/EstimateWizardPage.svelte` = the projection/grouping
  surface ("Customize Client View"); the "send all atoms" action lives in the
  worksheet/wizard flow.

## Tasks (TDD; each ends green + commit)

### Task 1 — Vocabulary label sweep
Relabel user-facing copy across `WorksheetDetailPage`, `EstimateDetailPage`,
`EstimateWizardPage`, and JobDetail section headers/buttons: "Worksheet"→**Plan**
(where it means the build view), the customer estimate doc →**Client View**, and the
projection verbs →**Show Client View** / **Customize Client View**. **Do not** touch
route paths, API URLs, model/field keys, or the `ChangeOrder` term. Add/adjust the
component tests that assert these labels. (Grep for visible "Worksheet"/"worksheet"
strings in those files; leave code identifiers alone.)

### Task 2 — Merge JobDetail's two sections into one "Estimate" pillar
Replace the separate `worksheets` and `estimates` accordion sections with a single
**Estimate** pillar. Inside it, a **`[ Plan | Client View ]` toggle**:
- default **Plan** while the live Client View is draft / none; default **Client
  View** once it's sent/frozen (key off the live estimate's status);
- the toggle swaps which view's summary the pillar shows (reuse the existing
  worksheet-summary and estimate-summary render blocks);
- a single **Open** link opens the full page of the active view
  (`/worksheets/{id}` or `/estimates/{id}`).
Update `VALID_SECTIONS` (replace `worksheets`+`estimates` with one key, e.g.
`estimate`) and the default-section logic. Preserve the version/CO timeline access
from the Client View side (reachable from its Open/full page, not the pillar).
Update JobDetail tests.

### Task 3 — "Start Estimate" / "Open Estimate" on the pillar
Fold the Phase-2 "Start Estimate" CTA into the pillar and add the deferred **Open
Estimate** state: no Plan → "Start Estimate" (→ create-worksheet flow); Plan exists
→ the pillar defaults appropriately and "Open Estimate" opens the live Client View
(or Plan via the toggle). Update tests.

## Out of scope
- Backend object/db renames (final naming pass, later). The combined Tasks &
  Materials pillar (its own phase). The re-projection "underlying changed" marker
  (its own phase). Removing direct line authoring / slimming (later phases).

## Decisions to confirm
- Exact toggle labels ("Plan" / "Client View") and the pillar key name.
- Lifecycle trigger for the default side (lean: live estimate status ∈ {draft,none}
  → Plan; else Client View).
- This phase rewrites JobDetail heavily — **coordinate with the user's process
  rework first.**
