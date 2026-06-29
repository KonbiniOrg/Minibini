# Invoice changes — spec (seed buttons, retained editing, adjustments)

> **Status: SPEC / design — decisions settled (2026-06-28).** §6 (joined-line/category) is
> decided: **option D + hand-edited category + Send-gate**. No blocking open questions remain;
> ready to graduate to a task-by-task implementation plan. Replaces the deleted
> Phase 6/7/8-invoice plan docs; master design rationale is
> `2026-06-24-planning-billing-consolidation-draft.md` §8–§10.

## Goal

Bring the invoice into the consolidated world **without** removing the per-line
flexibility the estimate gave up. The invoice becomes seedable from either the job's
actual atoms or the accepted estimate, but every line stays hand-editable, and an
accepted estimate's adjustment reaches the invoice without being applied twice.

## Background / current state

- The **estimate Client View** is now a pure projection of Plan atoms: no direct base-line
  authoring (POST line-items → 405), reorder + adjustments only.
- The **invoice was deliberately left on the old model**: `InvoiceViewSet` still mixes in
  the full `LineItemMixin` (direct line authoring works), already has
  `line_items_from_atoms` (a wizard projection) and the adjustment surfaces
  (`adjustment_lines`, `agreement_adjustments` backed by `compose_agreement`).
- The adjustment panel (`AgreementAdjustmentsPanel.svelte` on the draft invoice) surfaces
  the accepted estimate's adjustments and lets the user add them; dedup keys on
  `adjustment_service` per invoice (`already_added`).

## In scope

1. **Two seed buttons** on a draft invoice (§3, §4).
2. **Retain full per-line editing** on the invoice (§5).
3. **Adjustments stay as-is** behaviorally (§6) — *except* we must resolve the
   joined-line/category problem (§6, open).
4. **Progress / partial billing** behavior for repeat invoices (§3).

## Out of scope (explicitly not doing here)

- **Job-scoped adjustments** (the old Phase 8 — auto-apply at job level). Deferred; the
  user is no longer sure job-scope is the right home. Adjustments remain per-document.
- **Locking down invoice line authoring** (no estimate-style 405). The invoice keeps direct
  add/edit/delete of lines on purpose.
- **Removing the shared `inventory_item` line-item field** (the old Phase 7-invoice half).
  Still read on the invoice; leave it.

## 3. Button: "Apply everything"

The invoice analogue of the estimate's "Show Client View" / send-all-atoms.

- Gathers **all billable Job atoms** (Tasks + Materials + Expenses) and lands them
  **one atom per line** (via `InvoiceWizardService`, single-atom line per atom — *not*
  joined; joining is a deliberate later hand-edit, see §5/§6).
- **Progress billing:** on a job that already has a prior invoice, some atoms are already
  claimed by that invoice's line sources. Apply-everything bills only the **remaining,
  unclaimed** atoms (skip already-claimed rather than raising `ClaimConflict`).
- Adjustments are **not** atoms, so Apply-everything brings base lines only; the user adds
  any adjustment from the agreement panel (§6).

## 4. Button: "Copy from estimate"

- **Ignores atoms entirely.** Copies the agreement-of-record — the accepted estimate's
  lines as amended by accepted change-order deltas — i.e. exactly what
  `compose_agreement(job)` returns, including its adjustment line(s).
- Each copied line is a plain invoice line (no atom source). Adjustment lines are copied
  **with `adjustment_service` set**, so the agreement panel sees them as `already_added`
  and won't offer a second copy (dedup, already tested in
  `tests/test_invoice_agreement_adjustment_dedup.py`).
- **Availability:** only when this is effectively the first/only invoice for the job (no
  other invoices exist). Once a prior invoice exists, Copy-from-estimate is **disabled**
  (copying the full agreement would double-bill what an earlier invoice already covered).

## 4a. Button availability rules (both)

- Both buttons are **starting points**: disabled the moment the invoice has **any** line.
- They are **mutually exclusive** — pick one on a fresh draft. To switch approaches after
  seeding, **delete the draft and start over** (no in-place "switch").
- First invoice on a job: both available (subject to the empty-invoice rule).
- A prior invoice exists: Apply-everything bills remaining atoms; Copy-from-estimate is
  disabled.

## 5. Retained per-line editing

- The invoice keeps `LineItemMixin` — add, edit, delete, reorder lines freely after
  seeding. This is the flexibility intentionally removed from the estimate but kept here.
- Joining/grouping atoms into one line remains available on the invoice (it is how the
  customer-facing line gets composed). See §6 for the consequence on adjustments.

## 6. Adjustments — and the OPEN joined-line/category decision

**Settled:** the adjustment mechanism stays per-document and unchanged in shape — a
percentage `RateScheme` adjustment line on the invoice, surfaced/carried from the accepted
estimate by the agreement panel, dedup-keyed on `adjustment_service`. *Copy from estimate*
brings adjustments along automatically; *Apply everything* leaves them to the panel.

**OPEN — must decide before implementation:** how a category-targeted adjustment treats a
**joined line**. The shared wizard join (`apps/core/wizard.py` `add_atoms_to_new_line_item`,
~lines 228-229) sets a joined line's `accounting_category` to its atoms' single shared
category, or **`None` when the atoms span more than one category**.
`compute_adjustment_amount` (`apps/core/adjustments.py`, ~line 52) excludes any line whose
`accounting_category_id` is not in the adjustment's target set, and `None` never matches —
so a mixed-category joined line silently drops out of every category-targeted adjustment's
base. (An empty target set — "apply to all" — still includes it.) Lives in `core`, so it
affects the estimate Client View **and** the invoice. (Tracked in `docs/designs/LATER.md`.)

**This is bigger than adjustments — QBO/tax also breaks on a `None`-category line** (checked
2026-06-28). `accounting_category` is nullable on `BaseLineItem` (`apps/core/models.py:341`;
the "make required after data migration" comment was never acted on). For a category-less
line:
- `TaxCalculationService.get_effective_taxability` (`apps/core/services.py:1127`) returns
  **`False` (non-taxable)** when there's no `taxable_override` and no category → the line
  silently bills **no tax**.
- `InvoiceGroupingService.group_for_qbo` buckets it as "Uncategorized" with
  `qbo_item_id = ''`, so the QBO `SalesItemLine` gets **no `ItemRef`** and
  `TaxCodeRef = 'NON'` (`apps/qbo/services.py:357-362`). A QBO invoice line normally
  requires an `ItemRef` (income account/item) — so the push is rejected or posts against
  nothing useful.

So **no sendable invoice line may have a `None` category**, independent of adjustments. That
collapses the realistic options to "give every line exactly one category."

Candidate resolutions (tradeoffs):

- **(A) Manual line targeting** — replace category targeting with a user-chosen set of
  *lines* the adjustment applies to.
  - *Pro:* simplest for adjustments; full per-invoice control.
  - *Con:* breaks automatic estimate→invoice carry-forward (line identities don't survive
    the jump), so the user re-selects per document — reintroduces the "forgot the rush"
    risk. **Does not address the QBO/tax `None`-category problem at all.**

- **(B) Keep categories; attribute joined lines from their atom sources.** **RULED OUT** —
  proportional/atom attribution is opaque to the user, and it can't cleanly handle
  *overridden* or *copied* (source-less) lines. (Copy-from-estimate still carries the
  adjustment *line* fine; the gap was only the base computation, which B can't do.)

- **(C) Forbid cross-category joins** — the wizard refuses to join atoms of differing
  accounting categories into one line.
  - *Pro:* every line always has exactly one category; targeting, carry-forward, tax, and
    QBO ItemRef all keep working; smallest change.
  - *Con:* you cannot merge a labor line and a material line into one customer-facing line.

- **(D) Require a mixed-category join to be assigned a single category** *(current lean)* —
  allow cross-category joins, but the user must pick one accounting category for the merged
  line (no `None` allowed).
  - *Pro:* fixes adjustments **and** tax **and** the QBO ItemRef in one move (one category
    per line); keeps cross-category merging (unlike C); the attribution is a conscious,
    visible user choice, not opaque math.
  - *Tax consequence:* a hand-assigned joined line takes its chosen category's taxability
    for the whole line; `taxable_override` is the manual escape hatch if the merged line
    needs a different tax treatment.

### Decision (2026-06-28): (D) with hand-edited category + Send-gate

Joins are **not** constrained — you may merge across categories. The resulting line may be
left without a category in draft; the user **assigns/changes the accounting category by hand**
on the line, and **Send is gated** until every line has one. Concretely:

1. **Joins unconstrained.** No cross-category restriction in the wizard; a mixed-category
   join lands with `accounting_category = None`.
2. **Category is hand-editable on the line.** `accounting_category` is already writable on
   `InvoiceLineItemSerializer` (only `line_item_id` is read-only) and edits route through
   `LineItemService.save_line_item`, which recomputes adjustments — so a hand-set category
   immediately re-includes the line in any category-targeted adjustment. The work is mainly
   **frontend**: expose an editable category control on the line (the line view already
   *displays* `accounting_category_name`).
3. **Flag a missing category.** A line with no `accounting_category` is visibly flagged in
   the line-item view.
4. **Send-gate.** The invoice **Send** button is suppressed/blocked until **every** line has
   an `accounting_category`. This also discharges the standalone tax/QBO hazard (no `None`
   line can be sent) — see §9.
5. **Default suggestion = later refinement.** Optionally pre-suggest a category for a mixed
   join (e.g. the dominant-amount atom's category), but that is out of scope for the first
   cut; the user assigns by hand for now.

*Tax stance:* the chosen category governs the whole merged line's taxability;
`taxable_override` remains the per-line escape hatch. (We are deliberately not splitting tax
within a merged line — the user will evaluate whether that's good enough while working
through it.)

Category targeting on adjustments is **kept** as-is; because every *sent* line has a
category, targeting and estimate→invoice carry-forward keep working.

## 7. Migration / data

Pre-production. No data migration; existing per-document adjustments and lines regenerate
from seed. (Consistent with the consolidation's "regen from spreadsheets" stance.)

## 8. Testing notes

- Apply-everything: lands one line per billable atom; on a second invoice, only unclaimed
  atoms; claimed atoms skipped (no `ClaimConflict` surfaced to the user).
- Copy-from-estimate: lines match `compose_agreement`; adjustment lines carry
  `adjustment_service`; agreement panel reports `already_added` (extend the existing dedup
  test); disabled when a prior invoice exists.
- Button availability: both disabled once the invoice has a line; copy disabled with a
  prior invoice.
- Adjustments (§6 = D): assigning a hand-picked category to a mixed-category joined line
  re-includes it in a category-targeted adjustment's base (recompute fires on save).
- Category flag + Send-gate: a line with `accounting_category = None` is flagged; **Send is
  blocked** until no line is `None`. (Covers the standalone tax/QBO hazard.)
- Hand-edit: PATCHing a line's `accounting_category` persists and recomputes adjustments.

## 9. Open questions (blocking → must answer before plan)

_None remaining — §6 decided (D + hand-edit + Send-gate, 2026-06-28). The former item 2
(no `None` category on a sent line) is absorbed by the Send-gate. Ready to graduate to an
implementation plan._

## 10. Open questions (non-blocking → can default)

- Default category suggestion for a mixed join (e.g. dominant-amount atom's category) —
  deferred refinement; hand-assign for the first cut.

- Should Apply-everything land each atom as its own line, or auto-group same-category atoms
  by default? (Default: one line per atom; grouping is a hand-edit.)
- Does Copy-from-estimate need a confirm, or is the empty-invoice + disabled-when-prior rule
  enough? (Default: no confirm; the availability rules guard it.)
