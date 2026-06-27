# Phase 4 — Re-projection: "underlying changed" marker on Client-View lines

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §8 (the three line states) + §13. Self-contained feature.

**Goal:** When the Client View is re-projected from the Plan, give each line one of
three states: **(1) in sync** — line still matches its atom → auto-updates;
**(2) overridden, atom unchanged** → left alone; **(3) overridden AND the atom
changed since** → a visible **"underlying changed — review"** marker (never silently
overwritten or ignored). A deleted underlying atom shows **"underlying removed."**
Reconcile actions: **re-pull** (take the fresh projection) or **keep mine**
(dismiss, re-baseline).

**Depends on:** Phase 3 (Client-View vocabulary/pillar) is nice-to-have but not
required; this can ship independently. **Note:** today, re-running
`send_all_atoms_to_estimate` only *adds new* lines — it does not update in-sync
lines. Part of this phase is making re-projection update in-sync lines.

## Why a snapshot is needed
There is **no stored sync-point today.** `BaseWizardService._is_in_sync` derives
"in sync" only as `price == round(sum(source amounts)/qty, 2)` — it can't tell that
an atom's *description/qty/AC* drifted, nor distinguish "user overrode" from "atom
changed." We add a **billing-relevant snapshot** captured at projection time.

## Global constraints
- One model change (a snapshot field) → **one migration** → run the suite WITHOUT
  `--keepdb` once (fresh build) per the `feedback_fresh_db_after_migrations` rule.
- Never write the dev DB; backend tests on the test DB; one process. Svelte 5 runes.

## Reference (from exploration)
- `apps/estimates/models.py` `EstimateLineItemSource` (~L591–633): `source_type` /
  `source_pk` / `resolve()`; unique on `(source_type, source_pk)`.
- `apps/estimates/services.py` `EstimateWizardService.send_all_atoms_to_estimate`
  (~L1199–1242) copies description/qty/units/price/AC from the atom; re-run adds
  only new lines. `_is_in_sync` / `_resync_in_sync_line_item` in
  `apps/core/wizard.py`.
- `apps/api/estimates/serializers.py` `EstimateLineItemSerializer` exposes `sources`.

## Tasks (TDD)

### Task 1 — Snapshot the atom's billing-relevant fields at projection time
Add a JSON snapshot (e.g. `atom_snapshot` on `EstimateLineItemSource`, or a
`projected_from` blob on the line) capturing the atom's **description, qty, price,
accounting_category** at the moment a line is projected/synced. Populate it in
`send_all_atoms_to_estimate` and in the wizard's add-atoms paths. Migration +
fresh-build test run. Tests: creating a line from an atom stores the snapshot.

### Task 2 — Compute the three states + "underlying removed"
Add a service/serializer-level computation: for each line with sources, compare each
source atom's **current** billing fields against the snapshot. Derive a per-line
state: `in_sync` (matches snapshot AND line not hand-edited), `overridden_clean`
(line hand-edited, atom == snapshot), `underlying_changed` (atom != snapshot),
`underlying_removed` (atom resolve() is None). Expose it read-only on
`EstimateLineItemSerializer` (e.g. `reprojection_state`). Tests for each state.
("hand-edited" = line's stored fields differ from the snapshot's projection, i.e.
the existing `_is_in_sync` notion generalized to the snapshot.)

### Task 3 — Re-projection updates in-sync lines; leaves others
Change "Show Client View" re-projection so in-sync lines **update** from their atoms
(refresh fields + snapshot), overridden lines are **left untouched**, and
changed/removed lines are flagged (state from Task 2), not overwritten. Tests:
re-project after an atom change updates an in-sync line but not a hand-edited one.

### Task 4 — Reconcile endpoints
Add per-line actions: **re-pull** (re-derive the line from its atoms + reset the
snapshot) and **keep mine** (re-baseline the snapshot to current atom values,
clearing the flag). Endpoints under the estimate line-item namespace; draft-only.
Tests for both.

### Task 5 — Frontend marker + reconcile UI
On the Client View (`EstimateDetailPage` / wizard line cards), render the
**"underlying changed — review"** / **"underlying removed"** markers passively from
`reprojection_state`, with **Re-pull** / **Keep mine** buttons calling Task 4.
Component tests.

## Out of scope
- Applying the same marker to the Invoice (do it there if/when invoice projection
  gains hand-editing — see the invoice phase).
- The "billing-relevant fields" set is fixed to description/qty/price/AC; modifiers
  are already frozen out of lines.

## Decisions to confirm
- Snapshot location: on `EstimateLineItemSource` (per-atom) vs. on the line
  (per-line projection blob). Lean: per-line blob keyed by source, simplest to diff.
- Whether to ship Tasks 1–3 first (the correctness core) and 4–5 (reconcile UX)
  as a follow-up.
