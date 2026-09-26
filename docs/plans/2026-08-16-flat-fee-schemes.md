# Flat-fee rate schemes — design (deferred)

**Status: IMPLEMENTED 2026-08-16** (same day — RM pulled it forward
mid-review). Durable record: `docs/designs/estimates-and-prices.md`
§2.2a + `data-constraints.md` §1.7. Disposable plan doc.

## Problem (RM)

There is no flat-fee scheme *type*. Delivery fees, per-machine setup
fees, and rush-fee minimums are one billing behavior at many prices —
but `RateScheme` welds price and behavior together (`rate` lives on the
scheme; `ServiceItem` holds no money), so today each distinct price
requires its own scheme *plus* a wrapping ServiceItem: full duplication.
RM hit this live: created a "Setup fee" scheme ($110, entered_qty) and
found it both unpickable (schemes aren't in catalog search) and
unshareable (the next fee needs a whole new scheme).

## Settled design

**One `flat_fee` algorithm** (a real fourth `ALGORITHM_CHOICES` constant
— RM: must be a separate type, for discoverability and validation), and
**item-side amounts**: the flat-fee scheme is pure behavior (rate locked
to $0, never edited after creation — so scheme supersession churn never
applies to fee-price changes), and each ServiceItem referencing it
carries its own amount in the existing `default_active_modifiers`
JSONField.

**The reinterpretation rule (RM):** on a flat_fee scheme the field's
entries are NOT modifiers — they ARE the fee amount ("instead of adding
a percentage to the existing amount, the entire amount gets
'modified'"). **No mixing**: flat_fee schemes must have an empty
`modifiers` list of their own, and percent entries are invalid in a
flat-fee item's config. The percent-composition question from the
earlier design discussion is thereby dissolved — nothing composes.

**Encapsulation (the load-bearing decision, RM):** the dual use of
`default_active_modifiers` must be entirely hidden inside `RateScheme` —
consumers never learn the field has two shapes. Feasibility was checked
and it works, via one key move:

> **For flat_fee, the amount resolves into `Task.rate` at stamp time.**

Concretely, algorithm-owned interpretation lives in scheme methods
(shapes indicative, refine at build time):

- `RateScheme.resolve_stamp(item_config) -> {rate, unit_label,
  active_modifiers, ...}` — called by `Task.stamp_from_scheme` instead
  of its current inline key-resolution. Percent algorithms return
  today's behavior verbatim (rate = scheme.rate, snapshot dicts from
  keys). flat_fee returns `rate = <the item's amount>`,
  `active_modifiers = []`.
- `RateScheme.effective_rate(...)` (the existing scheme-side method,
  models.py ~633) branches internally for flat_fee — used by the
  catalog-pick price prefill (`add_line_item_from_service` and the
  picker's displayed price).
- `RateScheme.validate_item_config(entries)` — algorithm-owned
  validation called from `ServiceItem.clean()`: keys-into-my-modifiers
  for percent algorithms; exactly-one `{label?, amount}` entry, no
  percent keys, for flat_fee.

Because the amount lands in `Task.rate`, **everything downstream is
untouched**: `Task.effective_rate` (task-owned money, no scheme lookup —
Phase 1 principle preserved), `copy_active_modifiers`,
`validate_active_modifiers`, the money-field permission gates, the
bundle-modal uniform detection, invoicing valuation. The polymorphic
JSON exists only between ServiceItem and RateScheme, interpreted in one
place. This also makes the field's contract per-algorithm by design —
"each scheme can use the modifiers field however it needs" (RM) — so
future algorithms can define their own config shape without touching a
consumer.

**UI (bounded changes):**
- Scheme manager: "Flat fee" appears in the algorithm dropdown; rate
  input hidden/locked at 0; the scheme's own modifiers editor hidden
  for flat_fee.
- ServiceItem editor: when the picked scheme is flat_fee, show an
  **Amount** field (writes the config entry) instead of the modifier
  pre-check UI. The word "modifier" appears nowhere on this path (RM:
  no longer the right term).
- Catalog pickers already display `rate_scheme_detail.rate` — route
  through the scheme-side effective rate so flat-fee items show their
  real price.

**Documented edge (accept knowingly):** a manual task created from a
flat_fee scheme with no ServiceItem has no amount source → stamps at
$0. Acceptable in the claims-by-construction world (task money is
valuation; the fee's money lives on the estimate line, which got its
price from the catalog pick) — document it, don't fight it.

**Also resolves:** most of LATER's "Entering a flat fee is not
intuitive" (2026-08-16) — creating a fee becomes one gesture on the
Service Items tab (pick the shared Flat fee scheme, type the amount).
The scheme-creation-surface discoverability half of that entry stays
open.

## Companion task (RM reminder, same effort or before it)

**The nealsdata converter must source its RateSchemes internally** —
generate them inside the converter instead of reading them out of
`nealseed`/`nealsmall` (those stay RM-managed and shouldn't be the
converter's scheme source, and a new algorithm type must not require
touching them). Standing converter rules apply:
`tests.test_neals_builders` mandatory; nealseed/nealsmall never
regenerated; `converted.json` is the regenerable artifact.

## Out of scope

- Mixing percent modifiers onto flat fees (explicitly rejected — no
  composition).
- Any change to hand-line flat fees (a plain line stays the one-off
  path; this design covers the repeatable/catalog path).
- Migrating RM's interim "Setup fee" scheme (#10, entered_qty $110) —
  RM regenerates/adjusts dev data at will; pre-production.
