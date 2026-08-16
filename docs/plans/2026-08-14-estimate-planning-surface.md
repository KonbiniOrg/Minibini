# Estimate/Planning joint surface — design

**Status: SUPERSEDED 2026-08-15** by
`2026-08-15-estimating-structure.md` (claims by construction). This
design was implemented in full on branch `feature/planning-surface`
(abandoned at `c231c8de`, kept for reference/salvage) and failed RM's
hands-on testing — the freeform claim attachment and dual catalog doors
it permitted produced overlapping/faithless states (see the successor
spec's post-mortem). Retained for the record.

**Original status:** design settled with RM 2026-08-14 (this session); awaiting RM
review of this write-up before any implementation planning.
**Branch:** TBD — RM creates the working branch when implementation starts.
Disposable plan doc; durable record lands in `docs/designs/`
(estimates-and-prices, jobs-and-tasks, architecture-and-conventions) when
implemented.

## Problem (RM's framing)

Different people work differently:

- **Plan-first:** do all the task/material planning, then generate the
  estimate from the plan. (Works today: pool → select → merge into lines.)
- **Estimate-first:** write up the estimate — likely the fastest way to
  complete it — then make the plan afterward. Today this barely works:
  tasks appear only at acceptance, only for service-item lines; hand
  lines never become work. "If a user just writes a bunch of estimate
  lines, the system doesn't have a good way to know how to turn them
  into Tasks. That process has to be done by (the same or a different)
  user, after acceptance, which is another whole thing."

Two halves of one problem (RM): *"How to get tasks and materials out of
hand-written estimate lines? this is half the problem. The other half is,
how to consolidate a set of tasks and materials that result in salable
objects into one or more estimate lines?"*

Hard constraint: **hand lines are necessary** — job variance is
irreducible. Catalogs (ServiceItems), and templates when they return, are
accelerators layered on a path that must work bare. Never require a
catalog pick, and never put a rate-scheme picker on a hand line (that
would reinvent the service catalog, worse — the catalog *is* the
scheme-shortcut path).

The estimate-line↔task association (claims) this creates is also
groundwork for the invoice side: "for the invoicing wizard to work at all
it will be very useful to associate work with existing estimate lines,
although this is not essential" (RM).

## Settled design

### 1. The pool becomes a planning surface (draft estimates)

On a **draft** estimate, the "Unquoted work" pool grows real planning
powers: **Add task**, **Add material**, and per-row **edit** — reusing the
task page's existing modals (same components, not slim clones). Everything
minted is immediately real (a real `Task` / `Material` on the job).

- **Crystallization rules unchanged.** Real atoms on unaccepted jobs are
  already how the tasks-first path works; job status keeps unaccepted work
  off the board; pre-approval work happens legitimately and gets tracked
  (RM). No "proposed" task state, no deferred creation.
- Half 2 (tasks → lines) is served by iteration on one surface: dig into
  tasks, discover structure, group atoms into lines via the existing
  select-and-merge machinery, pull atoms back out, regroup. The #1
  finished-items shape ("not clear how to put the estimate together until
  you start digging into the tasks") is exactly this loop.
- Related but separate: the keep-the-total re-expression gesture
  (LATER.md, "Lost gesture") is the natural finish of this loop —
  re-express merged hour-tasks as "3 ea @ $600". Build it with or after
  this surface.

### 2. "Plan work" — the downward gesture (line → tasks)

Any **claimless** line gets a **Plan work** action:

- Opens the task modal **seeded as a mirror of the line** — name from
  description, qty/units copied — and on save mints the task **claimed to
  that line** on the spot.
- The flow stays open to add further tasks/materials under the same line
  (deep lines: finished items, parts-from-material). The seed is a
  starting point, not an answer — the system guesses nothing beyond the
  mirror.
- Material-vs-task at mint follows the line's AC (`_derive_is_material`
  rail) with the modal's own controls available to override.
- Roughly ten of the fifteen shapes (appendix) are one-line ↔ one-atom;
  for them this is one click plus at most one tweak.

### 3. Rate scheme resolution (the settled ladder)

The estimator's head-scheme doesn't reach a hand line, and asking for it
anywhere is either catalog-reinvention (authoring time) or
repeating-oneself (plan time). Resolution:

1. **Catalog/service-picked lines:** `source_scheme` provenance upgrades
   the mint for free — the minted task carries the line's scheme.
2. **Hand lines:** mint with the **existing mid-work task default
   scheme**, prefilled and editable in the already-open modal.

The claim is the load-bearing artifact; the task's scheme is a *valuation
placeholder*, not a truth claim — a claimed task prices nothing (money
lives on the agreement line). A wrong scheme self-announces where it
matters (reconcile "Use actuals" figures, schedule forecast) and gets
fixed there. Do not build any scheme-guessing beyond this ladder.

### 4. No draft-only wall — the post-acceptance gap

The same **Plan work** gesture works on an **open or accepted** estimate's
claimless lines (RM 2026-08-15: "let Open estimates have the same planning
affordances as Accepted, there's no real reason to limit that"). This
fills the acceptance→release-to-floor phase — the task-first process run
in reverse, on the far side of acceptance — and covers pre-approval
planning while the customer decides. It absorbs the "tasks-from-estimate
view" LATER sketch as a gesture on the existing surface instead of a new
page. The joint surface stays available there with **estimate lines
frozen** (document immutable; planning half alive).

- Requires a sanctioned post-draft claim-mint path (today's wizard
  service is `_validate_draft`-gated): planning an open/accepted line
  mints task + `EstimateLineItemSource` claim. Scope it narrowly —
  claimless lines on live (`open`/`accepted`) estimates only; no line
  mutation. Dead statuses (rejected, superseded) get nothing.
- **Duplicate guard:** acceptance-time crystallization must skip service
  lines that already carry task claims (pre-planned before send) — same
  shape as CO acceptance's re-claimed-atom skip.

### 5. After send, the surfaces separate

Pool planning powers (add/edit) and line editing are draft affordances;
the one post-draft affordance is §4's Plan-work-on-claimless-lines. Sent/
accepted documents keep the strict breakdown RM confirmed: "Once an
estimate is sent, the existing breakdown makes a lot of sense."

### 6. Templates (future, separate effort)

RM plans to bring templates back: "a single estimate line item backed by a
set of editable tasks and materials seeded from a template… create the
association quickly and easily, then let the user make adjustments."
That is tier three of the same Plan-work gesture — a richer seed than the
mirror. Design it in the templates revival, not here; this spec only
guarantees the gesture's seed is pluggable (mirror | template set).

### 7. Legibility (the bugbear)

RM: "The bugbear will still be the complexity of the interface and being
able to understand what bits are what and how they relate." Commitments,
not implementation taste:

- **Two domains, two colorways, one page:** the pool-as-planner is
  task-domain material inside an estimate-domain page. The pool section
  wears the **amber** (cw-tasks) band; the line table stays **indigo**.
  Indigo = the commercial document; amber = the shop plan; the
  `AtomCaptionRow` ("based on 2 tasks:") and Based-on chips are the
  visible bridge.
- **Frozen vs. editable must be unmistakable** post-acceptance: frozen
  lines render read-only (no edit/remove affordances), while Plan work
  stays visibly live on claimless lines.
- **Claimed vs. unclaimed** in the pool keeps today's states; newly
  minted-and-claimed atoms appear nested under their line immediately
  (not in the pool), so a Plan-work action has a visible landing spot.
- Prototype the surface and review with RM in the browser before
  polishing — this is the highest-risk part of the design and RM expects
  to adjust it.

## Out of scope (recorded, deferred)

- **Invoice-side estimated-vs-actual composition** (LATER.md 2026-08-14)
  — explicitly sequenced after this work; the claims this surface mints
  are its groundwork.
- **Whole-estimate "planning pass" view** — considered and not chosen;
  the per-line gesture plus the joint surface covers both rhythms. Revisit
  only if deep lines prove awkward per-line in practice.
- **Templates revival** (§6) — separate effort.
- **Keep-the-total re-expression** — separate LATER, natural companion.
- **"Unbilled work" descoped-atom wording tension** — invoice-side pass.

## Appendix: the fifteen shapes (acceptance list)

RM's list of everything that gets estimated and worked (recovered
2026-08-14; the durable copy now lives in
`docs/designs/estimates-and-prices.md` appendix). Any design in this area
must give each shape a sane path:

1. **N finished items we manufacture** — the deep case: structure emerges
   from digging into tasks; may reduce to combinations of the shapes
   below, or split design / prototyping / finished-object work — multiple
   tasks coalescing into one or more estimate lines. Served by the §1
   iteration loop (and eventually templates).
2. **A material we're reselling** — material atom → line.
3. **Making N parts from a particular material** (may or may not also
   sell the material) — cutting task(s) + material, grouped.
4. **Setup fee** — flat task; mirror-seed, one click.
5. **Delivery (usually flat)** — flat task; mirror-seed.
6. **CAD/design time (hourly)** — hourly task; mirror-seed + scheme check.
7. **Engraving (router or laser)** — preset/catalog path (`source_scheme`).
8. **Cutting charges** (machine-minutes entered-qty → per-piece) —
   preset/catalog path.
9. **Jigs kept for re-use** — ordinary task+material.
10. **Specialized tools funded by customer** — ordinary task+material.
11. **Outsourced work** (powder coating, waterjet) — PO reconciliation
    (Phase 5); Plan work still mints the placeholder task/claim.
12. **Site visits (priced up front)** — flat task; mirror-seed.
13. **Untracked consumables** — hand line, typically no work to plan
    (claimless line is fine — Plan work is optional everywhere).
14. **Deposits** — already built; no planning.
15. **Credits** — signed hand line; no planning.
