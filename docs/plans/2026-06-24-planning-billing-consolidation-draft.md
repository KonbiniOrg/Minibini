# Planning → Billing Consolidation — DESIGN DRAFT

> **Status:** design draft for discussion. Not a spec, not implementation-ready.
> Created 2026-06-24; revised 2026-06-25 (one-object/two-views framing); **revised
> 2026-06-26** — the initial build is now deliberately **minimal**: both the
> one-off **Fee** atom and **billing groups** are moved to *Maybe Later* (§15),
> each with its full "if we do it, here's how." We ship the consolidation without
> them to learn whether either gap actually hurts. Open questions remain (§13).
> *Later 2026-06-26 decisions:* the UI picker is **"Price List"**; the Plan and
> Client View stay **separate** objects (one Plan → many Client Views, with
> superseding); all object/db-table **renames are deferred** — build on the existing
> backend names and decide renames at the end.
> *Final UI vocabulary (2026-06-26):* **Estimate** = the whole pillar/object;
> **Plan** = the build view; **Client View** = the send view; **Price List** = the
> add picker. The Estimate pillar shows **one view at a time** (a `[Plan | Client
> View]` toggle, lifecycle-defaulted — §8); the job overview's Tasks + Materials
> (+ Expenses) collapse into **one** pillar.

## 1. The problem (why we're here)

Pricing and authoring sprawl. Adding the planned "ServiceItem → line item" path
revealed there are **three ways to put a charge on a document** (InventoryItem,
TaskTemplate, ServiceItem) — and that's only the symptom. The disease:

- **Two authoring surfaces.** You can build the plan (Worksheet of PlanTasks /
  PlanMaterials) *or* author the Estimate's line items directly (manual / "From
  Price List"). So "what's in the quote" has two sources of truth.
- **A back-channel to reconcile them.** Because a direct estimate has no atoms,
  acceptance needs a *second* carry-over (line item → Task/Material, the dormant
  `carry_over.py` Phase B) that reconstructs live atoms from frozen line items.
  That back-channel is the *only* reason a line item would need to carry
  `service_item` + qty + modifiers — i.e. the only reason to make "the frozen
  version of the thing" pretend to be the live thing.

This is the same shape as the RateScheme complaint: an object asked to be two
things at once. The fix is the same: give each concept one job.

## 2. The reframe: the Estimate, and its two views

The **Estimate** is one thing — the quote for a job — that you look at through
**two views**:

- **Plan (the build view)** — the internal surface where you assemble the quote out
  of **atoms**: PlanTasks (from ServiceItems / templates) and PlanMaterials (from
  InventoryItems). Cheap, mutable, never seen by the customer. The name is no
  accident: this view *holds the PlanTasks and PlanMaterials*. Backend:
  `EstWorksheet`.
- **Client View (the send view)** — what the customer sees and signs: a list of
  priced lines (the frozen projection of the atoms) plus any adjustments. It's the
  **contract**, so it carries the state machine. Backend: `Estimate`.

One Plan can produce **several** Client Views over time (revisions that supersede,
and — allowed — multiple open at once); the pillar shows the live one (§2.1). While
we keep the current code names, mind the deliberate backend↔UI mapping: backend
`EstWorksheet` = **Plan**, backend `Estimate` = **Client View**, and "Estimate" in
the UI means the whole pillar (§13).

The **wizard** is just the mechanism that projects the Plan into the Client View.
"Wizard" is a *backend* word; in the UI it never appears. The user-facing verbs:

| Today (backend / old UI) | New UI verb | What it does |
|---|---|---|
| "Send all atoms to estimate" | **Show Client View** | Cheap default: project every atom to one line each |
| "Open wizard to group atoms" | **Customize Client View** | Project with grouping/bundling control |

So the flow: build the **Plan** (atoms) → **Show / Customize Client View** →
review/tweak the Client View → **Send**. You must Show the Client View before you
can send — sending a quote you've never seen the way the customer will is not a
thing.

**In the overview these are one "Estimate" pillar showing one view at a time** (not
both at once) — defaulting to the Plan while drafting and the Client View once
sent/frozen, with a toggle between them. Full pillar behavior in §8.

### 2.1 Two objects, not one (one Plan → many Client Views)

"One Estimate, two views" is the **UI presentation**, not a 1:1 data fact. The Plan
and the Client View **stay two genuinely different objects** (`EstWorksheet` and
`Estimate`) — *no merge* — because the relationship isn't 1:1:

- the **Plan** is the one durable build surface, holding **live, mutable atoms**
  (PlanTasks / PlanMaterials);
- it can back **many Client Views** over its life — a revision projects a new Client
  View that **supersedes** the prior one, and multiple may be **open at once** (the
  existing invariant). Each Client View holds **frozen lines + its own state
  machine**.

Frozen-vs-live and one-vs-many are both real boundaries, so the two tables stay
distinct; the consolidation is the overview, the naming, and removing the *second*
authoring surface — never a table merge.

## 3. Principles (the invariants that trim it)

- **P1 — Atoms are the only authored, live, mutable unit of work.** PlanTask /
  PlanMaterial on the Plan; Task / Material on the Job. They hold quantities,
  modifiers, and the ServiceItem/InventoryItem reference.
- **P2 — The Client View is a frozen projection of atoms.** Its lines are
  produced *from* atoms; they are never authored into existence as work and never
  reverse-engineered back into atoms. Two bounded exceptions — adjustments and
  change-order deltas (§6).
- **P3 — Two priced primitives.** `ServiceItem` (services/labor) and
  `InventoryItem` (goods) carry catalog prices; everything billable derives its
  price from one of them.
- **P4 — Templates are presets, not a primitive.** `TaskTemplate` and
  `WorkTemplate` *expand into atoms*. They own **structure + pricing method +
  defaults**, never **magnitude** (§9).
- **P5 — One carry-over.** Plan atoms → Job atoms (PlanTask→Task,
  PlanMaterial→Material). **There is no line-item→atom path, and no
  line-item→Task generation.** (We are dropping the line-item→Task idea entirely —
  see §5.)

The single sentence: **everything flows atom → document, never document → atom.**

## 4. The one ladder

```
Catalogs            Plan (atoms)               Client View (frozen)     Execution
─────────           ────────────               ────────────────────     ─────────
ServiceItem  ─┐
InventoryItem ─┤→  Plan (build):           ──→  Client View            ──accept──┐
WorkTemplate ─┘     PlanTasks,                  (lines + adjustments)            │
   (preset)         PlanMaterials                = the contract                  │
                          ▲                          │ (state machine)           ▼
                          └─────── carry-over (atoms→atoms) ───────────  Job (Tasks,
                                                                            Materials)
                                                                               │
                                                                  Show / Customize
                                                                  (same wizard)
                                                                               ▼
                                                                       Invoice (lines)
                                                                       + adjustments → QBO
```

Plan→Client-View and Job→Invoice are the **same operation** ("freeze atoms into a
customer document") run twice. That symmetry is the whole point: one projection
pattern, used at quote time and at bill time.

## 5. What changes from today

1. **The Plan always exists.** Creating an Estimate creates its Plan; there is no
   "direct estimate" with hand-authored lines.
2. **Remove the second authoring surface.** The Client View's "Add Line Item"
   (manual + "From Price List") goes away. Client-View lines come only from atoms
   (Show / Customize) plus adjustments (§6).
3. **Remove Phase B carry-over** (`carry_over.py` line-item→Task/Material).
   Carry-over is atoms→atoms only, keyed by `source_plan_task` /
   `source_plan_material`.
4. **Drop the line-item→Task idea entirely.** Earlier we floated "a line item
   backed by a ServiceItem could generate a Task." We are *not* doing this — it's
   another document→atom back-channel, exactly the thing P5 forbids. Work
   originates as an atom on the Plan, period.
5. **Lines slim to pure frozen rows.** Drop `source_template` and the
   authoring/carry-over use of `inventory_item` on `EstimateLineItem` /
   `InvoiceLineItem`. Keep: description, qty, units, price, accounting_category,
   tax overrides, line_number, the `…LineItemSource` claim back to the atom (for
   traceability/sync), and `adjustment_service` + target categories (§6). No
   modifiers, no service/template provenance.
6. **The "missing input" becomes a Plan action.** Adding to the Plan collapses to
   **two actions** — *Add from template* and *Add from Price List* (the unified
   primitives picker) — instead of one button per source. Full UI in §8.
7. **Express = scaffold-then-adjust, not zero-touch** (§9).

## 6. The two bounded exceptions to "documents are projections"

There are two things on a customer document that are **not** a straight projection
of a unit of work — both deliberate, bounded exceptions to P2.

*(A third category — true **one-off charges** with no work or goods behind them, a
lumber surcharge or a "just charge $X" — has no dedicated home in the initial
build. That is a deliberate gap: we want to find out how often it actually bites
before paying for a solution. The fallback, if a one-off genuinely must bill, is a
`flat_fee` ServiceItem carried as a Task — clutter, but it works. The clean
solution, the **Fee** atom, is parked in Maybe Later, §15.1.)*

### 6.1 Percentage adjustments (built)

`adjustment_service` → a percentage `ServiceItem`. A rush fee / discount is a
percent of *other lines* — it has no atom and cannot. It lives on the document and
never carries to a Task. Authored by picking a percentage ServiceItem from the
same price list as everything else (users look for "rush fee" there — keep it
there). It is **job-scoped** and **auto-applies** to the job's documents (client
views and invoices), re-evaluated per document and removable/adjustable per
document (§10).

### 6.2 Change-order deltas (and how they square with "uneditable")

This is the part that felt inconsistent, so here it is in full.

**The tension:** if an accepted Client View is the frozen contract and can't be
edited, how can a Change Order edit it?

**The resolution:** a CO does **not** edit the Client View. It is a *separate,
small, customer-facing document* that records **deltas** against the accepted
Client View — `add` / `remove` / `replace` lines. The signed Client View stays
byte-for-byte frozen as "what was first sold"; the **agreement-of-record** is then
*the accepted Client View composed with each accepted CO's deltas*
(`compose_agreement`). Think of a CO as "a tiny Client View containing only the
changes" — which fits the framing perfectly: a CO is just *another customer-facing
contract artifact*, a delta-shaped one.

**Why a CO is direct-authored (the principled exception to atom→document):** by
the time you need a CO, the Client View is accepted and frozen and the Job is
*already executing*. There is no live Plan feeding that contract anymore — nothing
to regenerate from. A small, negotiated change to a signed document is authored
*as a delta*, by hand, because there is no atom stream behind it. That is
fundamentally different from quoting (where atoms exist and projection is the
right move). So:

- **Small change → CO.** Direct-authored deltas. Bounded: "less than a job's worth
  of change." Authored only while the Job is `on_hold` (the isolation room).
  Accepting it advances the Job and folds the deltas into the agreement-of-record.
  No automated Task/Material changes — the human edits the live Job atoms by hand
  afterward, because Tasks are the record of what *actually* happened.
- **Large change → new job** (`cancelled-with-invoice` to close the current one),
  which *does* get a fresh Plan and full atom→document flow.

So the CO is not a hole in the rule; it's the deliberate boundary where the rule
*stops applying* — once a contract is signed and work is underway, there are no
atoms to project, so amendments are direct deltas, kept small on purpose.

**UI placement in the new world:** the accepted Client View and its COs live
together under the Estimate pillar (or on the Job), and the agreement-of-record
(their composition) is what the Invoice bills against — not the raw Client View.

## 7. The catalogs (two primitives + presets)

| Concept | Is | Backs | Holds price? |
|---|---|---|---|
| **ServiceItem** | priced service/labor | PlanTask / Task | yes (rate + algorithm + modifier menu + AC) |
| **InventoryItem** | priced goods | PlanMaterial / Material | yes (cost + sell + AC) |
| **TaskTemplate** | preset | expands → PlanTask | no (ServiceItem + default qty + default modifiers + name) |
| **WorkTemplate** | preset bundle | expands → PlanTasks + PlanMaterials | no |

The "three ways to charge" collapse: inputs are to the **Plan (atoms)**, and they
are two primitives + a bundle — `ServiceItem→PlanTask`,
`InventoryItem→PlanMaterial`, `WorkTemplate→both`. Nothing is added to a
Client-View line directly.

## 8. UI surfaces (concrete, so nothing's missed)

**The Plan (build view) = the authoring page.** The add surface has **two
levels**, and that's the whole organizing idea:

- **Presets** — one pick expands into *one or more* atoms.
- **Primitives** — one pick becomes *exactly one* atom.

So there are **two add actions**, not one-per-source:

- **Add from template** *(presets level)* — pick a `TaskTemplate` (→ one PlanTask,
  with modifier selection) or a `WorkTemplate` (→ several PlanTasks + PlanMaterials).
- **Add from Price List** *(primitives level)* — **one unified picker** over both
  primitive catalogs (ServiceItems + InventoryItems), tagged by type and
  searchable. Selection creates the right atom, with the type-specific follow-up:
  - ServiceItem → `PlanTask` (+ qty, + modifier selection, + optional
    name/description override). A hand-built PlanTask *must* reference a ServiceItem
    (no priceless tasks). The modifier menu lives on the ServiceItem; the selection
    lands on the PlanTask's `active_modifiers`.
  - InventoryItem → `PlanMaterial` (+ qty).

This is the answer to "three is already a lot": the primitives collapse behind one
picker. It's a **front-end consolidation, not a backend merge** — ServiceItem and
InventoryItem stay separate models (different fields and behavior); the picker is a
convenience layer over them. (And if we ever add the **Fee** atom, §15.1, it slots
into this same picker as another type with *no new button* — part of why deferring
it is low-risk.) **Label decided: "Price List"** — it's the more common,
recognizable user term, even though the *model* moved from `PriceListItem` to
`InventoryItem`. The label is a UI-only string; it does not resurrect the old
model.

- **Show Client View** (cheap default) / **Customize Client View** (grouping).

**Client View (the send view):** the frozen projection + status actions + Send +
**Add Adjustment**. **While draft, its lines are editable** — re-price, rename,
regroup — *trust the user* (§13). What you cannot do here is originate a unit of
work (that's an atom on the Plan). Re-running Show/Customize re-projects from the
atoms with **three line states**:

1. **In sync** — line still matches its atom; re-projection updates it automatically.
2. **Overridden, atom unchanged** — you hand-edited it and the atom hasn't moved
   since; left untouched.
3. **Overridden, *and* atom changed since** — your edit and the source have
   diverged; the line is **never silently overwritten or silently ignored**. It
   gets a visible **"underlying changed — review"** marker so you can reconcile.

The marker is computed by comparing the atom's **billing-relevant** fields
(description, qty, price, price-affecting modifiers, AC) against a **sync-point**
snapshot stored on the line (or its `…LineItemSource`) at projection time. So it
surfaces **passively** whenever you view the Client View — not only on re-Show —
and a change to a non-projected atom field (e.g. `est_worker_time`, assignee)
won't raise a false flag. Reconcile actions: **re-pull** (discard my edit, take the
fresh projection) or **keep mine** (dismiss, re-baselining the sync-point). A
deleted underlying atom shows an analogous **"underlying removed"** marker. Once
**accepted**, the Client View is frozen and only a CO changes it.

**The Estimate pillar (overview) — one view at a time.** The pillar shows a
*single* view, never both crammed together, with a **`[ Plan | Client View ]`
toggle** and a single **Open** link (opens the full page of whichever is active):

- *While drafting* → defaults to **Plan**. Toggle to **Client View** to preview what
  the customer will see; **Open** goes to the full Plan (build) page.
- *Once sent / frozen* → defaults to **Client View**. Toggle to **Plan** to see how
  it was built; **Open** goes to the full Client View page (the customer-faithful
  render).

The lifecycle sets only the *default* side; the toggle always lets you flip. With
one Plan backing many Client Views (§2.1), the Client View side shows the **live**
one; superseded / sibling Client Views and a Client View's COs are reached from the
full page, not the pillar.

**The Tasks & Materials pillar (overview) — the job's live atoms.** Combine today's
separate Tasks and Materials (and Expenses) pillars into **one** pillar that mirrors
the main Task View layout. Conceptually this *is* the job's billable-atom family —
Tasks (work) + Materials (goods) + Expenses (costs) — i.e. exactly what the Invoice
projects from. Keep the label "Tasks & Materials" if you like; Expenses ride along
inside it. (If the **Fee** atom ever lands, §15.1, it slots in here too, beside
Expenses — this pillar is its natural home.) This is low-risk and separable from the
Estimate-pillar work — its own task in the plan — but worth doing in the same
overview pass.

**Job creation:** auto-create the Plan; offer the Express template path.

**Invoice:** built from Job atoms via Show/Customize + **Add Adjustment**. No
direct line authoring beyond adjustments. (Invoicing detail is deliberately
under-specified — §10.)

**Catalog managers:** ServiceItem manager (Settings → Catalog, exists),
InventoryItem manager (Inventory page, exists), Template managers.

## 9. Templates, magnitude, and Express

The user's discomfort: even when two jobs use the *same* three tasks built from
the *same* three ServiceItems, the **quantities and times differ** ("cut MDF
shapes" takes a different amount of time on every job). So a template can never be
"done."

**The reframe that resolves it:** a template owns **structure + pricing method +
defaults**, never **magnitude**.

- *Durable, template-owned:* which ServiceItem(s), descriptions, modifier
  defaults, accounting category, the *shape* of the job.
- *Per-job, always set by the estimator:* `qty`, `est_worker_time`. These are
  starting estimates at best; the template's default is a convenience, not a
  claim.

This makes the TaskTemplate problem not-a-problem: the template saves you from
re-picking the ServiceItems and re-typing the structure; you *always* set the
magnitudes, because magnitude is inherently per-job. (For `elapsed_time` /
`entered_qty` services, the quoted magnitude is only an estimate anyway — actuals
drive the invoice. Only `flat_fee` pins the charge at the estimated number.)

**Express, reframed.** Zero-touch "create from template → generate → send" is
indeed rare — you're right that nearly every quote needs the magnitudes adjusted.
So Express is **not** "skip the review." It's **"scaffold the entire Plan from a
template in one click, then set the per-job quantities/times and Send."** The
cheapness is *front-loading structure*, not eliminating the estimator's pass. That
keeps "always a Plan" from being a tax (you're never starting from a blank page for
a familiar job) without pretending estimating is hands-off.

## 10. Invoicing (same principle — detail deferred, but not separated)

Invoice lines = frozen projection of Job `Task` / `Material` / `Expense` atoms via
Show/Customize + adjustments. No direct authoring except adjustments. Invoices
never generate atoms (they're downstream of work). The agreement-of-record
(accepted Client View + accepted COs) is unchanged; `compose_agreement` still
feeds the "agreement adjustments" panel.

**Process constraint (from the user):** do **not** build a parallel estimate-only
path and leave invoicing untouched. Anything that touches *both* sides — the
projection mechanism, line-item field slimming, adjustments — gets changed on
*both* in the same work. We accept that invoicing needs more thought later; we do
**not** accept a temporary fork.

**The one known invoicing requirement — adjustments must reach the invoice —
resolved: adjustments are job-scoped and auto-apply.** A rush fee / discount is a
*job-level* item (joining the family of Expenses today, and the deferred Fee,
§15.1): you define "this job has a 10% rush on category X" once — authored from the
price list while building the estimate's client view, but attaching to the **Job** —
and it then **auto-applies to every document of that job**, client views *and*
invoices.

Because an adjustment is a **percentage rule, not a fixed amount** (10% of a
$1,000 estimate is $100; 10% of a $400 partial invoice is $40), the Job stores the
*rule* and each document **re-evaluates it against its own lines**. Auto-apply is
the deliberate default: the real risk is *forgetting to add* a rush, not having one
appear where you can see and remove it — the user can always **remove or adjust**
it on any given invoice.

Anything finer (an invoice-only adjustment that never touches the job, more
granular per-document controls) is **deferred** until there's a working instance to
play with. The estimate-side build just needs to attach adjustments at the Job
level and re-evaluate per document.

## 11. Inventory (unchanged mechanics, clarified role)

`InventoryItem` is one of the two primitives. PlanMaterial/Material reference it;
QOH / earmarks / consumption / expense-driven cost are unchanged. The only delta:
goods reach a document as a **PlanMaterial/Material atom**, never as a "From Price
List" line authored on the document. The PLI-on-line-item add path is removed.

## 12. Carry-over, est-time, migration

**Carry-over (simplified).** On accept: `PlanTask→Task`, `PlanMaterial→Material`
only, idempotent via the `source_*` keys, then earmarks. Delete Phase B and the
line-item provenance it depended on. Adjustments need **no** carry-over step —
they're **job-scoped** (§10), so they already live on the Job and auto-apply to its
documents.

**Estimated worker time is optional on the Plan.** Don't require `est_worker_time`
on a PlanTask. Everything works without it — *the only cost is that the schedule
can't place that task*, and users who don't want to estimate can live with that.
Require/prompt for est time **when a Task is assigned** on the live Job (that's when
the schedule needs it). So: PlanTask time optional; Task time required at assignment
time; schedule degrades gracefully (un-timed work simply doesn't appear on the time
axis).

**Migration: none.** We will **drop the current data and regenerate from the
source spreadsheets**. The `nealsdata/` seed scripts get updated to the new shape
— atom-only authoring, slimmed line items, the renamed views — rather than writing
data migrations. (This removes the "backfill a worksheet for direct estimates"
question entirely.)

## 13. Open questions / what's still genuinely undecided

- **Add-surface (§8) — decided: "Add from Price List."** More common/recognizable
  than "Catalog," despite the `PriceListItem`→`InventoryItem` history (UI-only
  label). Minor open: one tagged searchable list vs. a type filter — lean one
  tagged list.
- **Plan vs. Client View — decided: stay separate (§2.1).** Two different objects
  (`EstWorksheet`, `Estimate`); one Plan backs *many* Client Views (revisions that
  supersede; multiple open allowed). No merge.
- **The Estimate pillar — decided: one view at a time (§8).** A `[Plan | Client
  View]` toggle, default by lifecycle (Plan while drafting, Client View once
  sent/frozen), plus an Open link to the full page. One route, not two.
- **Re-Show after hand-editing a line — resolved (§8).** Three line states:
  in-sync (auto-updates), overridden-atom-unchanged (left alone), and
  overridden-atom-changed-since (gets a visible **"underlying changed — review"**
  marker — never silently overwritten or ignored). Driven by a billing-relevant
  sync-point snapshot on the line, so the marker surfaces passively and ignores
  non-billing atom edits; a deleted atom shows "underlying removed." Big changes
  spawn a new, superseding Client View instead (§2.1).
- **Adjustments — resolved (§10): job-scoped + auto-apply.** A percentage *rule* on
  the Job, re-evaluated per document, auto-applied to all the job's client views and
  invoices, removable/adjustable per document. Anything finer (invoice-only
  adjustments, more granular controls) is deferred until there's a working instance
  to try.
- **One-off charges / the Fee atom (§15.1).** *Deferred — not in the initial
  build.* We ship without a one-off home and watch for real pain; revisit only if
  the gap bites. If it does, §15.1 has the design.
- **Billing groups (§15.2).** *Deferred.* Same stance — revisit only after living
  with the simpler model.
- **`flat_fee` ServiceItem's role.** Today `flat_fee` is the only home for
  fixed-price things — including any one-off you shoehorn in while the Fee atom is
  deferred. If the Fee atom later lands, `flat_fee` can shrink to genuine
  fixed-price *work*. Note, don't decide.
- **Every entry point routes through a Plan.** Audit every place an Estimate is
  created today (email-to-job, "Create Estimate" on the job overview, API) so all go
  through Plan-creation. List them before removing the direct path.
- **Removal scope / sweep.** Deleting Phase B, `source_template` /
  `inventory_item` on line items, and the PLI/manual-line modal touches estimates,
  invoicing, carry-over, serializers, fixtures, and the UI-flow docs. Grep for
  readers of those fields before removing.
- **Naming rollout — decided: defer all object/db-table renames.** Build the whole
  change on the **existing backend names** (`EstWorksheet`, `Estimate`,
  `EstimateLineItem`, the wizard, …); decide at the *end* whether to rename objects
  and tables. UI vocabulary (decided): **Estimate** = the whole pillar/object;
  **Plan** = the build view; **Client View** = the send view; **Price List** = the
  add picker. Mind the backend↔UI mapping during the build: backend `EstWorksheet`
  = UI **Plan**, backend `Estimate` = UI **Client View**.

## 14. Rough sequencing (if we proceed — not bite-sized)

1. **Unified "Add from Price List" picker + "Add from template"** on the Plan
   (Service → PlanTask with modifiers; Material → PlanMaterial). The missing input;
   net-new, low-risk, useful immediately.
2. **Auto-create the Plan when an Estimate is created** + the **Express**
   scaffold-from-template path. Makes "always a Plan" cheap before removing the
   alternative.
3. **Apply the UI vocabulary** (Plan / Client View / Estimate pillar / Price List)
   and rebuild the **Estimate pillar** as a single-view `[Plan | Client View]`
   toggle (default by lifecycle) + Open; rename the projection verbs (Show /
   Customize Client View).
4. **Combine the Tasks & Materials pillar** (Tasks + Materials + Expenses, in the
   main-Task-View layout). Separable and low-risk; done in the same overview pass.
5. **Remove the second authoring surface** (Client-View "Add Line Item") and
   **Phase B carry-over**; drop the line-item→Task idea.
6. **Slim line-item fields** (drop carry-over provenance) once nothing authors or
   reconstructs from them — **on both estimate and invoice together**.
7. **Invoice parity**: projection from Job atoms (Task / Material / Expense);
   adjustment carry-over panel (§10).
8. **Seed scripts**: update `nealsdata/` to the new shape (no data migration).
9. **Docs**: rewrite `estimates-and-prices.md`, `jobs-tasks-and-worksheets.md`,
   `invoicing-and-expenses.md`, and the `ui-flows/` docs to the new model.

## 15. Maybe Later (DEFERRED — not in the initial build)

Both of these are **explicitly out of the first build.** The goal is
simplification; each is net-new complexity that must earn its place by *real pain*
felt after we've lived with the simpler model. They're written up so that **if** we
decide to do them, the *how* is already settled — but the default is that we don't,
until proven otherwise.

### 15.1 The Fee atom — one-off charges (Expense's revenue twin)

**The need.** A flat charge entered at quote time (or discovered during work) that
is **neither a catalog service nor a good**, often with **no work/time** behind it
— lumber surcharge, delivery fee on a material order, special tax assessment, "we
decided to charge $X." It must be able to reach **both** the estimate and the
invoice.

**What we do without it (the experiment).** No dedicated home. If a one-off
genuinely must bill, the fallback is a `flat_fee` ServiceItem carried as a Task
(it works, but it puts non-work in the task list), or it simply isn't supported.
We defer precisely to learn how often this actually comes up — maybe rarely enough
that the fallback is fine.

**If we build it — the shape.** A Fee is **not a work atom**; it's a **billable
atom**, the revenue-side twin of `Expense`. The codebase already has a billable-atom
family — `Task` / `Material` / `Expense` all implement `compute_amount()` and the
invoice projects from all of them — and `Expense` is already a *non-work* member
(job-attached, `amount` + `accounting_category`, never on the task list or
schedule). A Fee is the same shape as Expense, minus the cost/receipt/reimbursement
semantics: pure revenue we invented rather than a cost we incurred.

- **Visible where:** in the combined **Tasks & Materials pillar**, beside the
  **Expenses** — *not* the schedule or board. Quiet until invoice time.
- **Two origination points** (this is the one way Fee exceeds Expense, which is
  job-only):
  - *Quote time* → on the Plan → projects into the Client View → frozen on accept →
    copied to a **Job Fee** in the Big Copy (alongside Task/Material).
  - *Work time* → straight onto the Job, exactly like an Expense ("turns out we
    need a $200 assessment").
  - Both converge on a Job Fee the invoice reads via `compute_amount`. "Addable
    while a job is in progress" falls out for free — it's the Expense path.
- **Plan-side representation (sub-decision).** Mirror the twin pattern (`PlanFee` ↔
  `Fee`, like PlanTask/Task) for Big-Copy uniformity, **or** a single trivial `Fee`
  model with nullable Plan + Job FKs (copied Plan→Job on accept). *Lean: single
  model* — a Fee is flat with no plan-vs-actual divergence to justify a twin, and
  `Expense` is itself a single job-only model, so a one-model Fee sits naturally
  beside it.
- **Catalog is optional.** A reusable "Fee" catalog (e.g. a saved "Delivery fee")
  is just convenience sugar; the Job Fee *instance* is the real new thing —
  Expenses need no catalog and neither does this.
- **UI cost is tiny and additive:** it slots into the §8 "Add from Price List"
  picker as another type — no new button — which is why deferring it now costs us
  nothing later.

### 15.2 Billing groups — N work atoms → 1 line

**The need.** A charge that has *real work* behind it but bills as *one fixed
line*, where the work is actually several activities done by **different people at
different times**. Canonical example: the shop's **Setup fee** — quoted flat
(~$X, ~1 hr) but covering *coding* and *machine setup*, done by different people at
different times. Distinct from a one-off Fee (no work) and from a normal PlanTask
(one activity, one line). It's the N-work-atoms → 1-fixed-line case.

**Why not ServiceItem.** ServiceItem prices *one* line. Teaching it to also own a
multi-activity work decomposition makes it do two jobs at once — the RateScheme
overload, re-created. The bundling does **not** belong on ServiceItem.

**What we do without it (and probably keep doing).** Leave the Setup fee exactly as
today: one `flat_fee` ServiceItem → one Task, flat price. More than one person can
*already* log time against it — bleps are per-worker. The only thing you give up is
**scheduling/assigning the sub-activities independently.** For now that's
acceptable.

**If we ever build it — a "billing group":** a named, reusable link from N atoms to
one line.

- A small record carrying a **label**, a **price rule**, and its **member atoms**;
  plus an optional `billing_group` FK on atoms.
- **Price rules:** *flat* (the line shows one fixed amount, sourced from a
  `flat_fee` ServiceItem — or a Fee, if §15.1 also exists; the member atoms' own
  prices are **suppressed** on the customer document but retained internally for
  cost/margin) or *rollup* (the line shows the **sum** of its members as one line).
- The wizard **always** collapses same-group atoms to one line — that's the
  difference from today's *ad-hoc* manual grouping: it's persistent, named, and
  price-bearing.
- **Reuse lives in a WorkTemplate**, not in ServiceItem: a "Setup fee" WorkTemplate
  expands the "coding setup" + "machine setup" *work* atoms and links them into a
  flat billing group priced by the Setup-fee ServiceItem. The flat_fee ServiceItem
  keeps its single honest job (price one line); the work atoms do the work; the
  template stamps the bundle.
- **Carries to the invoice for free:** `billing_group` rides PlanTask→Task, so the
  invoice collapses the same atoms into the same one line even when the actual hours
  differ (the flat price still wins).

**Build criterion:** do this only if independent scheduling/assignment of
sub-activities matters across **more than one** real case. If Setup fee is the lone
example and per-worker bleps on a single Task suffice, skip it.

---

*Draft ends. Review targets for the initial build: the §8 two-action add surface +
the Estimate-pillar toggle + the combined Tasks-&-Materials pillar, the §6.2
change-order explanation, the §9 Express/template reframe, and the §10 adjustment
decision. Deferred (decide later, design already captured): the §15.1 Fee atom and
§15.2 billing groups.*
