# Service Price List & Percentage Adjustments — Design Spec

> **Status:** design spec (pre-implementation). Captures the agreed design from the
> 2026-06-23 pricing discussion. This is the durable design record for the change;
> a bite-sized executable task plan should be derived from it once the design is
> locked. Disposable per `docs/plans/` convention.

**Goal:** Give the shop *one obvious place to set what it charges* by reframing
`RateScheme` into a service price list, removing pricing from `TaskTemplate`, and
adding percentage-based adjustment lines (rush fees, discounts) scoped by
accounting category.

---

## 1. Motivation

Pricing in Minibini currently originates in three differently-shaped places, and
`RateScheme` half-owns price in a way that confuses users:

- **`RateScheme`** (`apps/jobs/models.py`) is the price authority for
  `elapsed_time` and `entered_qty` schemes (`rate` × a quantity sourced from
  Bleps or `actual_qty`). But for `flat_fee` schemes it carries **no price** —
  the per-unit price rides on the *atom* in `active_modifiers['flat_fee_price']`,
  and one shared "Flat Fee" scheme is reused across many differently-priced
  services.
- **`InventoryItem`** (`apps/inventory/models.py`) holds goods pricing
  (`purchase_price` / `selling_price`).
- **`TaskTemplate`** (`apps/estimates/models.py`) is where fixed-price services
  actually keep their price today (`default_active_modifiers` →
  `flat_fee_price`), making it a price list in disguise.

Symptoms confirming the seam:

- `active_modifiers` carries **two incompatible shapes** — a list of modifier
  keys for time/qty schemes, a dict `{'flat_fee_price': str}` for flat-fee.
  `copy_active_modifiers()` and `RateScheme._flat_fee_price()` exist only to
  manage that overload (`apps/jobs/models.py:38`, `:534`).
- `TaskTemplate.clean()` (`apps/estimates/models.py:493`) has to validate a
  *price* (`flat_fee_price > 0`) on a template — pricing logic living in the
  wrong model.

The asking question — *"how do we just say what our prices are?"* — has three
answers today (Inventory, Rate Schemes, Task Templates). This spec collapses the
service side to one.

### Why reframe rather than add a model

Stripping price out of `RateScheme` leaves only `algorithm` (a three-value
enum) as non-pricing — too thin to justify its own catalog row. `RateScheme` is
already ~80% a price-list entry (name, rate, unit, AC, modifiers). So the service
price list **is** `RateScheme`, reframed — not a new model layered on top of or
beneath it.

---

## 2. Scope

**In scope**

0. **Rename `RateScheme`** to the chosen service-price name (model, `db_table`,
   FK field names, API routes, frontend) as a pure mechanical refactor, done
   **up front** before any behavioral change (see §2.1 and §12).
1. Reframe the renamed model into the service price list: relocate flat-fee price
   onto `rate`, let flat-fee entries proliferate, restore `active_modifiers` to a
   pure list.
2. Decouple `TaskTemplate` from pricing (no dollar amounts on templates).
3. Add a `percentage` algorithm: adjustment lines (rush / discount) scoped by a
   multi-select set of accounting categories, emitting a frozen-on-finalize
   derived line, with an explicit Recalculate action and agreement→invoice
   surfacing via the wizard.
4. Update `apps/core/management/commands/validate_data.py` and the `nealsdata/`
   converter **after** the model changes settle, so generated/validated datasets
   use one-service-per-priced-item and pure-list `active_modifiers`.

**Deferred (explicitly out of scope — see §9)**

- Live recompute of adjustment lines on accepted/sent documents.
- Adjustment-on-adjustment stacking.
- A coarse "kind" grouping on `AccountingCategory` (only if multi-select AC
  later proves painful — the user expects not to need it).
- A cost-of-labor concept (labor remains sell-only; only goods model cost+sell).

### 2.1 Naming (decision needed before Phase 0)

The model is renamed in this work. Candidates:

- **`Service`** / `service` / `services` — matches the user-facing concept, but
  overloads the codebase's "service layer" vocabulary (`apps/*/services.py`,
  `XxxService` classes).
- **`ServicePrice`** / `service_price` / `service_prices` — unambiguous against
  the service-layer convention; UI still labels it "Services".

Recommendation: `ServicePrice` (clarity), UI label "Services". Final name is a
user decision and gates Phase 0. Throughout this spec, "the service" / "service
price entry" refers to the renamed model.

---

## 3. Design — Service price list (reframed RateScheme)

### 3.1 Pricing rules

- **One service = one price.** A service row carries exactly one price in
  `rate`. Price changes over time go through the existing `supersede()` flow,
  which gives price history for free and freezes historical references.
- **Flat-fee price moves onto `rate`.** `flat_fee` services stop borrowing
  `active_modifiers`. `RateScheme.rate` becomes the unit price for *all three*
  rated algorithms. The "share one Flat Fee scheme" convention is dropped:
  "Tap a hole — $1.00" and "Coat plywood — $30.00" each become their own service
  row, exactly like "CNC Router — $85.00/hr" already is.
- **`active_modifiers` reverts to a pure list** of modifier keys on every
  atom/template, for every algorithm. `copy_active_modifiers()`'s dict branch and
  `RateScheme._flat_fee_price()` are removed.
- **Modifiers retained.** The per-atom "rate modifier" menu (e.g. "messy +10%")
  is unchanged: defined on a service, selected per atom, baked into that atom's
  unit rate. This is the *intra-atom* percentage scope and stays exactly as-is.
- **Freezing unifies.** Today flat-fee history is frozen by copying the price
  onto each atom; time/qty history is frozen by supersession of the referenced
  scheme. After this change, supersession freezes all three algorithms
  uniformly — the per-atom price copy disappears.

### 3.2 Two distinct scopes of "percentage" (vocabulary discipline)

To avoid recreating the `active_modifiers` overload, the two percentage features
are kept separate and named distinctly:

| Concept | Scope | Where defined | Where selected | Effect |
|---|---|---|---|---|
| **Rate modifier** (existing) | one atom | service's `modifiers` menu | per atom (`active_modifiers` list) | adjusts that atom's unit rate |
| **Document adjustment** (new) | a set of lines | a `percentage` service | per document (target AC set on the emitted line) | emits its own line = percent × matching subtotal |

Same arithmetic, different blast radius. They coexist; neither shares the other's
storage.

### 3.3 Algorithm applicability — one catalog, two consumer surfaces

The service price list is consumed in two ways:

- **As a Task's billing definition.** `Task` / `PlanTask` / `TaskTemplate` keep
  their existing FK to the service. A Task *is* an instance of performing a priced
  service: it reads measurement method (`algorithm`), `rate`, `unit_label`, AC,
  and the modifier menu from the service, and **computes** its amount
  (`rate × resolved qty`) — money is never stored on the Task. Unchanged by this
  work.
- **As a line-item price source.** A service's price flows directly onto an
  estimate/invoice line.

Algorithms split by which surfaces they're valid on:

| Algorithm | Backs a Task/Template? | Produces a line item? |
|---|---|---|
| `elapsed_time` | yes | yes |
| `entered_qty` | yes | yes |
| `flat_fee` | yes | yes |
| `percentage` | **no** (document adjustment, not a unit of work) | yes (adjustment only) |

`percentage` services are **excluded from every task/worksheet/template scheme
picker** and from being set as a Task/PlanTask/TaskTemplate `rate_scheme`
(enforced in the serializers/services that assign a service to those models).
They appear only in the documents' "add adjustment" affordance.

---

## 4. Design — Percentage adjustments

### 4.1 The service entry

- New algorithm constant `RateScheme.PERCENTAGE = 'percentage'`, added to
  `ALGORITHM_CHOICES` with label e.g. `'Percentage of other lines'`.
- `rate` holds the percent value: `15.00` = +15% rush, `-10.00` = −10% discount.
  Negative is permitted for `percentage` services (model `clean()` must allow it;
  other algorithms keep their existing constraints).
- `accounting_category` is its own — rush fees book to an expedite income
  account, discounts to a contra-revenue account. This is a feature, not
  overhead: the shop decides where adjustment money lands, once, on the catalog
  entry.
- `unit_label` is cosmetic for this algorithm (e.g. `'%'`); it takes no rate
  modifiers (parallel to `flat_fee`).

### 4.2 Targeting — multi-select accounting categories

- The adjustment is scoped by a **set of `AccountingCategory`** values. Stored on
  the *emitted line item*, not on the service (a service is reusable across
  documents; the target set is a per-application choice).
- **Empty set ⇒ "all non-adjustment lines"** — the common whole-order case, zero
  category-picking.
- Targeting reads each line's `accounting_category` and is therefore uniform
  across atom-backed, PLI, and manual lines (all carry an AC). No dependence on
  line provenance.
- **Adjustment lines are never targets.** The recompute sums only lines whose
  `algorithm`/kind is not `percentage`, so a rush fee and a discount on the same
  document each compute off the base lines and never off each other (this is what
  enforces the deferred "no stacking" rule).

### 4.3 The emitted line item

When a `percentage` service is applied to an estimate or invoice:

1. A normal line item is created: `qty = 1`, `description` from the service,
   `accounting_category` from the service.
2. Its amount lands in `price` (since `qty = 1`):
   `price = (percent / 100) × Σ(matching base-line amounts)`, where a base line's
   amount is `qty × price` (`BaseLineItem.total_amount`).
3. It sorts **after** all base lines (highest `line_number`).
4. Negative results flow through `total_amount`, grand total, and tax with no
   special-casing (a discount is just a negative line).

### 4.4 Recalculate + freeze

- The emitted line stores its formula inputs — the `percentage` service reference
  and the target AC set — so it can be recomputed and re-displayed.
- While the document is **editable** (estimate `draft`, invoice `draft`), the
  line shows an explicit **Recalculate** action that re-runs
  `(percent/100) × Σ(current matching subtotals)` and updates the stored amount.
  This is an explicit user action, consistent with the "saves are explicit"
  convention — no implicit blur/auto recompute.
- On **finalize** (estimate sent/accepted, invoice sent), the amount is frozen
  and the Recalculate action disappears. `compose_agreement` and the invoice/PDF
  paths only ever see a frozen dollar amount, so they need no awareness of
  percentages.

### 4.5 Agreement → invoice surfacing (path-independent)

The invoice may be built straight from Task/Material atoms via the wizard,
**without ever touching the estimate**. So carryover must not hook the
estimate-driven creation path — it must be sourced from the job's
agreement-of-record, which exists regardless of how the invoice is assembled.

- **Source of truth: `compose_agreement(job)`** (`apps/estimates/agreement.py`)
  — "the single source of truth for what the customer owes" (accepted Estimate +
  accepted COs). Percentage adjustments, being `EstimateLineItem`s, are already
  in it.
- **Surface in the invoice wizard as a dedicated "Agreement adjustments"
  panel** — *not* through the atom source pool. Atoms feed grouping /
  summarization / in-sync machinery; an adjustment must never be grouped with
  task atoms (it's its own line computed from the others), so routing it through
  the atom abstraction would mean special-casing every atom path to forbid
  grouping. The panel lists each agreement percentage line (e.g. "Estimate:
  +15% rush on Labor") with an **Add** action that creates the adjustment line on
  the invoice and recalculates it against the invoice's *actual* category
  subtotals.
- **"Already added vs not"** state on the panel gives the same available/claimed
  affordance treating them as atoms would have — the reminder ("don't forget the
  rush fee") is hard to miss, and works for both the estimate-driven and
  wizard-driven invoice paths.
- The added line behaves like any §4.3/§4.4 adjustment: editable Recalculate
  while the invoice is a draft, frozen on send.

---

## 5. Data model changes

### 5.1 `RateScheme` (`apps/jobs/models.py`)

- Add `PERCENTAGE = 'percentage'` constant + choice.
- `clean()`: allow negative `rate` only when `algorithm == PERCENTAGE`; keep
  `accounting_category` required; keep `FROZEN_FIELDS` / supersession behavior.
- Remove `_flat_fee_price()` (no longer needed) and the `effective_rate()`
  flat-fee branch that reads it; `effective_rate()` for `flat_fee` returns `rate`.
- `effective_rate()` for `percentage` is not a per-unit rate in the usual sense;
  percentage amount is computed at the document layer (see §5.4), not via
  `compute_charge`. Guard `compute_charge`/`get_actual_qty` against being called
  for `percentage` atoms (percentage services are not attached to Tasks/atoms).

### 5.2 `copy_active_modifiers` (`apps/jobs/models.py:38`)

- Reduce to `list(value or [])`. Remove the dict branch.

### 5.3 `TaskTemplate` (`apps/estimates/models.py:461`)

- `default_active_modifiers` keeps meaning **only** "pre-checked modifier keys"
  (pure list). Remove the `flat_fee_price` validation in `clean()`
  (`apps/estimates/models.py:493-506`). Templates hold **no** dollar amounts; the
  price is read through `rate_scheme.rate` at generation time.
- `default_billable_qty` stays (it's a quantity default, not a price).
- A `flat_fee` template now simply references the specific flat-fee *service* (one
  service per priced item), so its generated atoms inherit the price from the
  service like every other algorithm.

### 5.4 Percentage adjustment line storage

The emitted line is an ordinary `BaseLineItem` subclass row
(`EstimateLineItem` / `InvoiceLineItem`) plus a small amount of adjustment
metadata. Two options for storing the metadata — pick during implementation:

- **(A) Fields on the line-item subclasses:** add nullable
  `adjustment_service` (FK → `RateScheme`, the percentage service) and a
  `adjustment_target_categories` (M2M → `AccountingCategory`) to
  `EstimateLineItem` and `InvoiceLineItem`. Most explicit; localized.
- **(B) A small companion model** keyed 1:1 to the line item, carrying the
  service FK + target-category M2M. Keeps `BaseLineItem` subclasses lean.

Recommendation: **(A)** — the data is small, the line item is the natural owner,
and it mirrors the existing `source_template` / `price_list_item` provenance
fields already on line items. A line is an adjustment iff `adjustment_service_id`
is set (and that service's `algorithm == percentage`).

A shared helper (e.g. `apps/core/wizard.py` or a new
`apps/core/adjustments.py`) computes
`compute_adjustment_amount(line) -> Decimal` =
`(service.rate / 100) × Σ(total_amount for non-adjustment sibling lines whose
accounting_category ∈ target set, or all non-adjustment siblings if the set is
empty)`, quantized to cents. Both the estimate and invoice Recalculate endpoints
call it.

---

## 6. API surface

New/changed endpoints (final shapes TBD during implementation; mirror existing
line-item action conventions, all returning 200 + JSON body):

- `POST /api/estimates/{id}/adjustment-lines/` — add a percentage adjustment line
  (body: `{adjustment_service, target_category_ids: [...]}`); server computes and
  stores the initial amount.
- `POST /api/estimates/{id}/line-items/{lid}/recalculate/` — recompute an
  adjustment line; rejected (409) when the estimate is no longer a draft.
- Parallel add/recalculate pair on `InvoiceViewSet`.
- `GET /api/jobs/{id}/agreement-adjustments/` (or a field on an existing invoice
  wizard payload) — the agreement's `percentage` lines from `compose_agreement`,
  each annotated with whether it's already on the invoice (see §4.5).
- The service serializer exposes the `percentage` algorithm; the manager UI gains
  a percentage type. The serializers/services that assign a service to
  `Task`/`PlanTask`/`TaskTemplate` reject `percentage` services (§3.3).

Permissions unchanged from the surrounding endpoints: estimate adjustment writes
require `can_manage_jobs`; invoice adjustment writes require
`can_manage_financials`; service (RateScheme) writes require `can_manage_config`.

---

## 7. Frontend

- **Services manager** (was Rate Scheme manager): relabel to "Services"; add the
  percentage type (single percent field, negative allowed, AC required, no
  modifier menu).
- **Estimate detail / Invoice detail:** an "Add adjustment" affordance that picks
  a percentage service and multi-selects target accounting categories (empty =
  all). Adjustment lines render distinctly (e.g. "+15% rush on Labor, Welding")
  with a **Recalculate** button visible only while the document is editable.
- **Wizard line cards:** adjustment lines are not atom-backed; they appear as
  ordinary lines with the adjustment badge + Recalculate.
- Component touch points: `frontend/src/components/LineItemModal.svelte`,
  estimate/invoice detail pages, and the rate-scheme/services manager component.

---

## 8. Migration — best-effort

Pre-production: drop/recreate freedom means "good enough + a printed worklist"
beats a perfect, exhaustive migration. The migration must **not** be all-or-
nothing and must **not** block on the agent reading the dev DB (see `CLAUDE.md`).

1. **Mint flat-fee services for the confidently-resolvable cases.** For every
   `flat_fee` atom/template carrying `active_modifiers['flat_fee_price']`, group
   by identical `(price, unit_label, accounting_category)` tuple, mint one
   `flat_fee` service per distinct tuple (`rate` = that price), and repoint the
   atom/template at it. Preserve history: existing superseded references keep
   pointing at the version they were created with.
2. **Strip `flat_fee_price`** out of every `active_modifiers` /
   `default_active_modifiers`, leaving a pure list.
3. **Log, don't fail, the ambiguous cases.** Anything the migration can't cleanly
   resolve (missing/zero price, conflicting metadata) is **logged to a worklist**
   for the user to hand-add/fix afterward — not raised. The user can drop and
   recreate as needed.
4. **Verify** no remaining dict-shaped `active_modifiers` exist for the migrated
   rows; the worklist captures the rest.

### 8.1 Post-settle script updates (after model changes are stable)

- **`apps/core/management/commands/validate_data.py`** — `check_rate_schemes`
  (currently at `:477`) updates for the renamed model, the `percentage`
  algorithm, the negative-`rate`-only-for-percentage rule, pure-list
  `active_modifiers` (no dict shape), and per-priced-item flat-fee services.
- **`nealsdata/` converter** (`build.py`, `loaders.py`, `orchestrator.py`,
  `reconcile.py`) — generate one service per priced flat-fee item and pure-list
  `active_modifiers`, so freshly generated datasets are correct by construction.

---

## 9. Deferred / explicitly not now

- **Live recompute on finalized documents.** Freeze on finalize, full stop. No
  cascading recomputation through change orders; agreement changes carry their own
  adjustment deltas.
- **Stacking** (adjustment on adjustment). Enforced out by excluding
  percentage-algorithm lines from the targeted sum.
- **AC grouping / coarse "kind".** User does not expect to need it; revisit only
  if multi-select AC proves painful.
- **Full `RateScheme` → `Service` model/db rename.** UI relabel only for now.
- **Cost-of-labor.** Labor stays sell-only.

---

## 10. Risks & open questions

- **AC nullability.** `BaseLineItem.accounting_category` is still nullable
  (project-wide AC-NOT-NULL migration pending). A line with null AC matches no
  target set; the empty-set ("all") path includes it. Acceptable interim; the
  pending AC-NOT-NULL work removes the edge.
- **Percentage services vs the task surfaces.** Percentage services are
  document-only (§3.3); ensure they're excluded from task/worksheet/template
  scheme pickers and rejected when assigning a service to a Task/PlanTask/
  TaskTemplate. `is_referenced()` will report zero task references for them by
  nature (they're never on a Task), so deletion of an unused percentage service
  stays possible.
- **Ordering with change orders.** A CO that adds/removes base lines doesn't
  retro-recompute a frozen adjustment; if the agreement needs a different
  adjustment, the CO carries its own. Confirm this matches expectation.

---

## 11. Docs to update on completion

- `docs/designs/estimates-and-prices.md` — RateScheme reframe, the `percentage`
  algorithm, flat-fee price relocation, `active_modifiers` pure-list, adjustment
  lines, carryover, Services relabel.
- `docs/designs/invoicing-and-expenses.md` — adjustment lines on invoices,
  carryover, Recalculate.
- `docs/designs/data-constraints.md` — `rate` sign rule for percentage services;
  adjustment line fields.
- `MEMORY.md` / memory files — note the rename, the Services label, and the
  flat-fee-price-on-`rate` change so future sessions don't look for `RateScheme`
  or `flat_fee_price`.
- `apps/core/management/commands/validate_data.py` and `nealsdata/` — updated as
  the §8.1 post-settle task (these are code, not docs, but listed here so the
  completion checklist is complete).

---

## 12. Suggested sequencing

Each phase should land green on its own.

0. **Phase 0 — Rename (mechanical).** Rename the model, `db_table`, FK fields,
   API routes, and frontend to the chosen name (§2.1) against the current stable
   codebase. No behavior change. Tests green, committed. Doing this first means
   Phases 1–2 are authored natively against the new name and never re-touched by
   a late rename.
1. **Phase 1 — Service price list reframe.** Flat-fee price → `rate`, drop shared
   flat-fee convention, `active_modifiers` pure list, `TaskTemplate` price
   decoupling, UI "Services" label, the §8 best-effort migration. Self-contained
   and shippable; delivers the "one place to set service prices" win on its own.
2. **Phase 2 — Percentage adjustments.** The `percentage` algorithm + §3.3
   applicability rule, AC multi-select targeting, emitted line + Recalculate +
   freeze, agreement→invoice wizard panel. Depends on Phase 1's framing.
3. **Post-settle — Scripts (§8.1).** Update `validate_data.py` and `nealsdata/`
   once the model changes are stable.

A bite-sized TDD task plan should be generated per phase before coding.
</content>
</invoke>
