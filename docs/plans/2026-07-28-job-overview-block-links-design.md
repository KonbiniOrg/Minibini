# Job overview — block links (design)

_2026-07-28 · closes the "Block-internal specific-document links" entry in
`docs/designs/LATER.md`_

## Goal

The six job-overview lifecycle blocks shipped deliberately linkless (2026-07-09
redesign, `jobs-and-tasks.md` §9.1a: "No block-level links or actions this
pass"). RM now wants each block to be a link. **The whole block is the click
target** — anywhere on the card — and it targets **the specific document the
block is about** when the block names exactly one, otherwise the relevant
section page.

Reversal of the 2026-07-09 "no links" decision is deliberate and RM-directed;
§9.1a must be rewritten, not merely appended to.

## The link map

| Block | Target | Rule |
|---|---|---|
| **Scope** | `#/jobs/:id/change-order/:coId` | when a draft/open CO is live — it's the lead stat and the reason the block is warm |
| | `#/jobs/:id/estimate/:estimateId` | otherwise, the current estimate (incl. frozen: `v3 accepted 7/2` → that estimate) |
| | `#/jobs/:id/estimate` | dormant — no estimate exists yet; lands where you'd create one |
| **Work** | `#/jobs/:id/tasks` | names no document |
| **Materials** | `#/jobs/:id/pos` | **always**, even with exactly one open PO — the PO detail page (`#/purchase-orders/:po_id`) lives outside the job umbrella and ejecting from the workspace is worse than one extra click (RM) |
| **Spend** | `#/jobs/:id/history` | names no document; placeholder target — see "Deferred" |
| **Invoicing** | `#/jobs/:id/invoice/:invoiceId` | exactly one live invoice |
| | `#/jobs/:id/invoice` | two or more live invoices |
| **Delivery** | `#/jobs/:id/shipments` | names no document |

"Current estimate" and "live invoice" keep the meanings `jobOverview.js`
already gives them: `currentEstimate()` (highest version among non-superseded,
falling back to the full set) and the `INVOICE_DEAD_STATUSES` filter
(cancelled/superseded excluded). The links reuse those, never re-decide them.

**Disambiguation principle.** One named document → link to it. Two or more →
link to the section index. The index is not a consolation prize:
`#/jobs/:id/invoice` lands on the remembered-or-latest invoice with the
`DocSubnav` pill strip listing all of them. So the ambiguous case costs one
extra click and never guesses wrong on a target that spans the whole card.
Rejected alternative: always pick the "most actionable" document (oldest unpaid
invoice) — cleverer, but it guesses silently, and a wrong guess on a
whole-card target is worse than a neutral landing.

**All three temperatures link.** Active, frozen, and dormant blocks are all
clickable, falling back to the section index when they name no document. A
dormant Scope reads "no estimate yet" and lands on the Estimates section. Never
a dead end; the whole-card target stays uniform.

## Where the rule lives

`lib/jobOverview.js` — the pure view-model. Its contract is explicit ("Every
block rule, clock, temperature, and copy string lives HERE; the Svelte
components are dumb renderers"), and "which document does this block target"
is a rule. Building hrefs in the wrapper components would put a rule in the
renderer layer.

**Return-shape change:** every block function adds `href` (a string, always
present) to its returned model, in all three states.

**Signature changes:** three functions have no job id today and need one.

| Function | Change |
|---|---|
| `scopeBlock` | add `jobId` |
| `materialsBlock` | add `jobId` |
| `invoicingBlock` | add `jobId` |
| `workBlock`, `spendBlock`, `deliveryBlock` | already take `job` — read `job.job_id` |

The three wrapper components (`ScopeBlock`, `MaterialsBlock`, `InvoicingBlock`)
gain a `jobId` prop, threaded from `JobDetail.svelte`, which already has `job`.

Edge case: if the id needed for a deep link is missing from the payload, fall
back to that block's section index rather than emitting a broken href.

## Rendering

`SummaryBlock.svelte` renders the card as an `<a href={model.href}>` instead of
a `<div>`, for all three states.

This is valid HTML — `<a>`'s content model is transparent and admits flow
content — because after RM's simplification the card has **no interactive
descendants**. It renders only divs and spans. That's what makes the plain
anchor possible and lets us skip the stretched-link overlay we'd otherwise need
for nested links, which in turn means **text selection inside the card still
works**.

Per CLAUDE.md UI Decisions ("Links navigate; buttons act"), these are
navigations, so `<a href>` is correct and no confirmation applies.

### CSS (`css/app.css`, the `.summary-block` family)

- `.summary-block { display: block; text-decoration: none; color: inherit; }` —
  an `<a>` is inline by default and `.active` relies on block layout.
  `.frozen`/`.dormant` already set `display: flex` and their own `color`, and
  are declared later in the file, so they continue to win.
- Hover affordance on all three temperatures.
- `:focus-visible` outline — the card is now a tab stop, six per overview.

## Deferred (not this pass)

Spend's real destination is a **job-profitability analysis** that does not
exist. RM's direction: point Spend at `#/jobs/:id/history` for now and fold the
rest into LATER's existing "Convert the remaining local-state tab pages to
per-tab routes" entry, since it's blocked on the same work.

Specifically **not** built here — `JobHistorySection.svelte` is untouched:

- per-tab routes for the history section (`activeTab` is local `$state` today,
  so no URL means "Analysis")
- the third **Analysis** tab and its "not yet implemented" placeholder
- retitling the page **History → "History and Analysis"**

`LATER.md`'s routes entry gains these three, noting that Spend's block link is
the caller waiting on them.

## Testing

Per CLAUDE.md TDD — tests first, and e2e is Definition of Done for
user-reachable flows.

1. **`tests/lib/jobOverview.test.js`** — the rule layer, where the real
   coverage belongs. Per block: the href in each of active/frozen/dormant; the
   one-vs-many split for Invoicing; Scope's CO-over-estimate precedence and its
   dormant fallback; Materials always `/pos` even with a single open PO; the
   missing-id fallback.
2. **`tests/components/jobs/overview/SummaryBlock.test.js`** — renders an
   anchor carrying `model.href` in all three states.
3. **Six block wrapper tests** — each passes its inputs through and surfaces
   an href; `ScopeBlock`/`MaterialsBlock`/`InvoicingBlock` also thread `jobId`.
4. **E2E** (`e2e/specs/`) — from a seeded job's overview, click blocks and
   assert the landed URL, covering at least one deep-link case (Scope or
   Invoicing to a specific document) and one section-index case.

## Doc updates (same session, per CLAUDE.md)

- `docs/designs/jobs-and-tasks.md` §9.1a — rewrite the "No block-level links
  or actions this pass" paragraph; record the link map and the disambiguation
  principle.
- `docs/designs/LATER.md` — delete the "Block-internal specific-document
  links" entry; extend the per-tab-routes entry with the three deferred items.
- `frontend/README.md` / `architecture-and-conventions.md` §5.5a — note that
  `.summary-block` is an anchor and must stay free of interactive descendants,
  or the plain-anchor rendering becomes invalid and needs the overlay pattern.
