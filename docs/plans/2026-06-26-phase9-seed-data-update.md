# Phase 9 — Update the seed data (nealsdata) to the consolidated shape

> ⚠️ **Predates the 2026-06-27 design revision.** Names here use the OLD mapping (rate
> card = `ServiceItem`, work catalog = `TaskTemplate`); the design draft now swaps
> these (rate card → `RateScheme`, saved work item → `ServiceItem`). Read against
> `2026-06-24-planning-billing-consolidation-draft.md`; re-derive specifics when
> executing.

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §12 ("Migration: none — regenerate from the source spreadsheets") +
> §14 step 8. **Do this AFTER the model changes (Phases 6–8) so the seed matches the
> final shape.**

**Goal:** Update the `nealsdata/` converter/builders and regenerate the dataset
fixtures so the seed reflects the consolidated model — no `source_template` /
line-`inventory_item` on estimate/invoice line items, adjustments in their new
(job-scoped) shape, and line items consistent with "documents are pure projections
of atoms." No data migration — we regenerate.

**Depends on:** Phases 6 (removed authoring/Phase B), 7 (slimmed fields), 8
(job-scoped adjustments). It tracks whatever those land on.

## Global constraints
- **Never write the dev DB.** Tests use the test DB. After regenerating, validate by
  loading the fixture in the test suite (it does this), and run the suite — including
  a **fresh build** if any migration shipped in 6–8.
- nealsdata writes fixtures; it must not require touching the dev DB.

## Reference (from exploration)
- `nealsdata/converter/orchestrator.py` `convert()` (~L96–122) sequences builders:
  `build_estimates()` (~L774–944, authors `estimates.estimatelineitem` fixtures) →
  `derive_atoms()` (~L1431–1560, emits `EstWorksheet`+`PlanTask`/`PlanMaterial` for
  plan-side jobs, or `Task`/`Material`+`Deliverable` for real-side, plus
  `EstimateLineItemSource` links) → `build_invoices()` (authors
  `invoicing.invoicelineitem`).
- `build.py` currently sets `source_template: None` (~L922/1144/1182) and
  `inventory_item: None` (~L923) on line-item fixtures — these keys must be removed
  once Phase 7 drops the fields.
- `validate_data.py` check_* methods (run against the fixture in tests).
- Datasets: `fixtures/large_datasets/nealseed.json` (tracked, seed reference data),
  `fixtures/large_datasets/nealsmall.json` (tracked, small subset),
  `nealsdata/datasets/converted.json` (**gitignored**, full output). Regenerate via
  the converter (e.g. `--limit 100` for nealsmall).
- Tests: `tests/test_neals_builders.py` (builder outputs),
  `tests/test_neals_fixture.py` (fixture loads + validate_data runs + invariants).

## Tasks (TDD)

### Task 1 — Drop removed fields from the builders
Remove the `source_template` / line-`inventory_item` keys the builders emit on
estimate/invoice line-item fixtures (matching Phase 7's field removals). Update
`tests/test_neals_builders.py` cases that assert those keys.

### Task 2 — Adjustments in the new shape
Update the converter to emit adjustments in the **job-scoped** form Phase 8 chose
(e.g. `JobAdjustment` rows) instead of per-document adjustment line items — or omit
adjustments from the seed if simplest. Keep `validate_data` happy.

### Task 3 — Line items consistent with projection
Ensure seeded estimate/invoice line items are valid frozen rows under the new model
(no provenance fields; sources still link atoms where applicable). `derive_atoms`
already authors atoms + `EstimateLineItemSource`; confirm nothing relies on the
removed paths.

### Task 4 — Regenerate datasets + gate
Regenerate `converted.json` (gitignored) and `nealsmall.json` (tracked) via the
converter; confirm valid JSON and counts. Run `tests/test_neals_builders` +
`tests/test_neals_fixture` and the full suite (fresh build if Phases 6–8 added
migrations). Carry over the existing LATER note about the `nealsmall` zero-rate
flat-fee row if still relevant.

## Out of scope
- Changing the source spreadsheets themselves (we convert what's there).
- nealseed.json reference data (users/ACs/ServiceItems) unless a field it carries
  changed.

## Decisions to confirm
- Whether the seed should include adjustments at all (vs leaving them out for a
  cleaner baseline until the job-scoped flow is exercised by hand).
- Regeneration command/limits for nealsmall (match the existing convention).
