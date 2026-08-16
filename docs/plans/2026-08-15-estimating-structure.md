# Estimating/planning structure — claims by construction

**Status:** design settled with RM 2026-08-15 (sixth redesign of the
estimating/planning process, RM's count); awaiting RM review of this
write-up. **Supersedes** `2026-08-14-estimate-planning-surface.md`, whose
implementation (branch `feature/planning-surface`, abandoned at
`c231c8de`, kept for reference/salvage) failed RM's hands-on testing.
**Branch:** `feature/estimating` (off `feature/better-fees`).
Disposable plan doc; durable record lands in `docs/designs/` when built.

## What the failed experiment taught (the post-mortem, kept short)

The joint surface kept two representations of the same conceptual thing —
the line (commercial) and the atom (operational) — both freely editable in
one place, linked by claims that were supposed to mean "this is the work
behind this line" but were never verified. Maintaining that correspondence
became the user's job, and every observed collision was a way of failing
at it: the same material entered through two doors and existed twice;
any atom could claim onto any line in any quantity (laser *engraving*
claimed onto a laser *cutting* line, mismatched plywood quantities);
crystallization resolved conflicts silently in favor of whichever side
had claims; removing a line's last atom deleted the authored line; the
pool's planning buttons read as estimate-scoped; two adjacent
catalog-add gestures had different outcomes and capabilities.

**The governing principle this design follows: claims arise only by
construction, never by attachment.** There is no gesture anywhere that
links a pre-existing atom to a pre-existing line. Faithless states become
unrepresentable instead of merely inadvisable.

## The model

A line has exactly one identity:

- **Projected** — built from plan atoms via the bundle gesture (below).
  Its claims exist because the atoms *made* the line.
- **Generative** — hand-written or catalog-picked. It will *mint* its work
  (or be explicitly declined) later; the mint creates new atoms claimed at
  birth. Its claims exist because the line made the atoms.

Planning stays home on the **task page** — the estimate page never grows
task/material add/edit powers again (that was the failed branch's central
mistake). The estimate page *sees* the plan (the pool, unchanged as a
display + selection surface) and *projects* from it. One catalog door per
surface. In all cases the line↔work claims are retained as the invoicing
rail.

## The timeline

**Draft** — write lines (hand or catalog pick); bundle plan atoms into
projected lines. NO minting: a draft line can change out from under a
minted task, and the sync machinery that would require is the
two-representations problem reborn (RM considered and rejected a
draft-mint + auto-modify option for this reason). Draft-time is
plan-first time; the task page and bundling are fully available.

**Send (`open`)** — lines freeze. Minting becomes available on hand
lines: each non-adjustment, non-deposit hand line can be **minted**
(work generated from it) or **declined** ("no work needed", a stored mark
on the line). Frozen source ⇒ the mint is a one-shot copy; all later
drift is task-side and legitimately means "the plan evolved"
(chip-flagged, never synced). Covers pre-approval work: send early,
mint, start.

**Accept** — catalog-backed lines (service_item / inventory_item /
bare-material) auto-crystallize exactly as today; **no change to that
code path**. Hand lines that are still unanswered enter the **acceptance
checklist**: an explicit small-t task on the accepted job — every hand
line must be minted or declined. The checklist is the visible to-do that
replaces the failed design's silent defaults.

**Auto-release (replaces "release to floor")** — when every line is
answered (claims exist, or declined, or crystallized), the job advances
`approved → in_progress` automatically. Corollary RM endorsed
explicitly: an estimate whose lines are ALL catalog-backed releases to
the floor automatically at acceptance. The manual release-to-floor
action is retired; `mark_work_started` (timeslip-start) keeps its
existing behavior. A job whose every hand line was consciously declined
releases with no tasks — taskless hand-billed jobs are thereby a
supported flow, settled deliberately (this resolves LATER's
"release-to-floor should require at least one Task" gating question:
the answer is the checklist, not a task-count guard).

## The two modals (bounded homes)

RM: complexity needs "a very clear bounded home" — both compound gestures
get modals; neither generates in place.

1. **Bundle modal** (draft only; the projection gesture): select pool
   atoms → compose a line. This is where the recalculation machinery
   returns: derived qty/price from the atom set, and the re-express-
   keeping-the-total gesture (the lost old-wizard capability, LATER
   2026-08-12) — e.g. 12 task-hours re-expressed as "3 ea @ $600".
   Un-bundling and the empty-line question (the remove-last-atom bug RM
   hit) get resolved *inside this modal's design*: atom removal never
   silently deletes an authored line.
2. **Mint modal** (open/accepted; the generation gesture): opens
   mirror-seeded — name/qty/units from the line, scheme from the line's
   catalog recipe when it has one, else the mid-work default (placeholder
   valuation, corrected where it matters). "Save & close" is the
   one-task path (the ~ten simple shapes: effectively one click since
   the seed is right). "Save & add another" generates a set under the
   same line, each claimed at save. Safe where the failed branch wasn't:
   the modal can only CREATE new work under this frozen line — it cannot
   reach existing atoms and cannot alter the commercial side.
   **Interior details deliberately deferred** (RM): build and test the
   surrounding structure first; the multi-task interior may yet expose a
   blocking problem, and v1 may ship Save-&-close + decline only.

## Removals from the current (better-fees) baseline

- **"Add selected here"** (attach pool atoms to an existing line) — the
  freeform-attachment gesture; dies everywhere. Composing atoms into
  lines happens only in the bundle modal; growing an existing projected
  line's atom set, if kept at all, is a bundle-modal re-open, not an
  in-table attach.
- **Remove-last-atom deletes the line** (`apps/core/wizard.py`
  `remove_atoms_from_line_item`) — replaced by whatever the bundle modal
  decides; never silent line deletion.
- The estimate surface's second catalog door: catalog picks exist once
  per surface (line authoring); the pool is not an alternate catalog
  entry point.

## The fifteen shapes under this model (acceptance walk)

1:1 mint (setup, delivery, CAD, site visits): hand or service-pick line →
mint Save-&-close; catalog recipe upgrades the scheme when present.
Presets (engraving, cutting): service pick; the pick's recipe IS the
mint — the modifiers-visibility asymmetry dies structurally. Materials
(resale; material halves of parts/jigs/tools): inventory pick →
today's crystallization, or minted earlier (post-send) when earmarking/
ordering must precede approval. Compound (parts-from-material, jigs,
tools): two simple lines, or plan-first bundle. Outsourced: mint a
placeholder task; PO reconciliation (Phase 5) carries the actuals.
Never-mint (consumables, credits): explicit decline (deposits excluded
by kind). Deep (#1 finished items): plan-first bundling is the sanctioned
path; estimate-first gives a stub task via Save-&-close (or a set via
Save-&-add-another once that ships); no multi-attach ever returns.

## Open questions / risks (tracked, not blocking the spec)

- **Checklist surface**: where the accepted job shows its unanswered
  lines (job overview block? estimate panel banner?) — design during
  build.
- **Auto-release edge**: an accepted-now/start-later job walks onto the
  floor as soon as its checklist completes; RM accepts this (on_hold
  exists for genuine deferral).
- **Transition/compat**: jobs already `approved` when this ships have no
  checklist state; they must not strand — define a backfill rule
  (probably: existing approved jobs count as all-answered).
- **`maybe_complete_if_resolved` cascade** (from the release-to-floor
  LATER entry): with auto-release replacing the manual edge, re-check
  that a never-worked job's completion walk stays coherent.
- **Decline representation**: a stored per-line mark (name TBD; visible
  to invoicing later as "no work behind this line, on purpose").
- RM: "It's still possible this will have some blocking problem I can't
  see until I try it." Build lean, browser-test early, expect a seventh
  pass on the interior of the mint modal.
