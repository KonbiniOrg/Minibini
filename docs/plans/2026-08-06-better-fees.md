# Better Fees — lines, work, and reconciliation

**Status:** draft for RM review. Disposable plan doc; the durable record lands
in `docs/designs/` (estimates-and-prices, jobs-and-tasks,
invoicing-and-expenses, data-constraints, schedule) when implemented.

**Branch:** `feature/better-fees` (based on main). Supersedes the
`feature/fees` branch's Phases 2 and 4; adopts its Phases 1, 3, and 5 (§2).
Design conversation: 2026-08-06 session.

## Problem

An estimate line is a **commercial** statement (what the customer buys, at
what estimated price). A Task or Material is an **operational** one (what the
shop does or consumes). Sometimes they coincide — hourly labor, where the
task is the sellable unit — and the atoms-and-lenses architecture is built on
that coinciding case. When they don't coincide, the system forces the
commercial unit to masquerade as an operational type:

- On main, a typed hand-line ("3 chairs @ $500") crystallizes into a
  `Fee(quantity=3, unit_rate=500, task=NULL)` — a pure money row with no
  units, no lifecycle, no schedule presence, and no connection to the
  Deliverables that those same chairs must also (separately, manually)
  become. The work to build the chairs is entered as Tasks with no relation
  to any of it.
- On `feature/fees`, the same line became a flat work Task, and Phase 4 built
  parent×per-unit-subtask quantity structures so real work could hang under
  it. That made a Task simultaneously a billing container and a work item,
  and the price-derivation between them is where it broke: a per-minute CNC
  parent with a "go buy a bit" subtask has no intuitive invoice shape —
  either the parent's unit rate wobbles to absorb the child (the shipped
  behavior; judgment item #6) or the child bills as its own weird line.
- At invoice time there is no view of what the estimate said.
  `copy_from_estimate` replays agreement lines as bare values and claims only
  the crystallized Fees; task- and material-backed lines arrive with no
  source rows, so the wizard cannot reconcile them against actuals
  (`apps/invoicing/services.py:282-290`). §7 owns this problem outright
  (it was briefly a LATER.md entry; removed — this spec is its fix).

## Principles

1. **A sell price is stamped, never derived.** The money on a bag of
   heterogeneous work does not sum to a customer-facing price; a price is a
   decision informed by costs. Any container whose price is derived from its
   contents will confuse (this is the generalization of feature/fees
   Phase 1's stamp-don't-derive, and the lesson of Phase 4).
2. **Crystallization means becoming work.** Acceptance turns a line into a
   job-side object only where the line genuinely describes an operational
   thing the job needs: a Task from a service item, a Material from catalog
   or a bare material line. Lines that were never work (charges, outcomes)
   crystallize into nothing.
3. **Every line price is an estimate.** There is no fixed-price mode. Work is
   tracked precisely so the invoicer can bill more or less than estimated,
   with evidence. Invoicing is therefore *reconciliation, always*: what did
   we say, what did we do, what do we charge.
4. **Document money lives on documents.** A charge that is not work (rush
   fee, disposal, credit) exists as a line on the estimate and transits to a
   line on the invoice. It never takes up residence on the Job.
5. **Structural guarantees where they're cheap; an informed human where they
   aren't.** Atoms stay exactly-once-claimable. Agreement lines get a
   quantity-sum invariant. The remaining seam — knowing that a given pile of
   work "is" a given hand line — is closed by the invoicer declaring it at
   reconcile time, which is the one moment anyone actually knows.

## 1. What this changes, in one breath

Subtasks are removed from main. The outcome hand-line stops crystallizing
into a Fee and gains a make-a-deliverable button (at authoring, before
send). Fee lines dissolve into plain lines that ride the invoice
skeleton; the `Fee` model is deleted outright. Invoices start from the
agreement skeleton: claim-mirroring for backed lines, invoicer-driven
atom attachment for plain lines, whole-line references (one live invoice
per agreement line), a backing model where attachment recalculates
immediately, and advance money in exactly two shapes — deposit lines on
the existing credit rail, and completed atoms billed finally. Both
documents get the settled three-mode surface (§9). Adopted from
`feature/fees`: task-owned money + supersession deletion + flat tasks
(Phase 1), nullable AC + fallback stamping (Phase 3), outsourced-work PO
reconciliation (Phase 5), and the negative-total invoice send gate.

## 2. Adopted from feature/fees

- **Phase 1 wholesale** (task-owned money): `Task` gains `qty_source`,
  `rate`, `unit_label`, nullable `accounting_category`, resolved-modifier
  snapshots; `source_scheme` is provenance-only (invariant: no compute path
  reads it); RateScheme becomes a freely editable preset with `is_active`
  retirement and a default-preset Configuration key; the supersession
  apparatus (frozen fields, `replaced_by` chains, `(vN)` renames, the
  409/`supersede_url` dance) is deleted; adjustment lines snapshot their
  percent (`adjustment_percent`). **Flat tasks** — scheme-less, typed rate,
  entered qty — are the shape for work-backed charges: setup, delivery, site
  visits. Plan: cherry-pick the Phase 1 commit range from `feature/fees`
  (`73ac97cf..8acc4d10` plus the applicable post-close-out fixes); expect
  doc conflicts, resolve toward this spec.
- **Phase 3** (nullable AC + fallback): task AC optional end-to-end;
  `fallback_accounting_category` Configuration key; invoice compose stamps
  the fallback **on the line** (never back on the atom) and flags it in the
  wizard; QBO push guard against null AC. May need re-implementation rather
  than clean cherry-pick (its commits touch Phase 2 code).
- **Phase 5** (outsourced work): PO-level reconciliation (`bill_total`,
  `vendor_invoice_ref`, per-line `final_price`, `invoice_only` lines,
  REPLACE semantics), rate prompts from `default_material_markup_percent`,
  `linked_po_variances` job costing. The sell side is a flat task; nothing
  in this spec disturbs it. Same cherry-pick caveat as Phase 3.
- **Phase 2, only these fragments:** the negative-total invoice send gate
  (QBO rejects negative-total invoices) and negative-money rendering in
  `frontend/src/lib/format.js`. The rest of Phase 2 (Fee re-scope, signed
  Fee atoms, `freeform_kind`) is superseded — see §4, §5.

**Not adopted:** Phase 4 in its entirety (quantity structures,
`qty_scales_with_parent`, `derived_unit_price`, non-startable parents,
pool child-exclusions, the deliverables `source_task` bridge), and
Phase 2's `freeform_kind` migration chain.

## 3. Subtasks removed — at the code level; the field sleeps

Subtask behavior is removed from the UI and backend code, but
`Task.parent_task` **stays in the model, dormant** (RM, 2026-08-06: this
area is being redesigned for the second time; no confidence there won't
be a third — keep the structural option open). One level of task in
practice; if work needs sequencing or reference to another task, the user
says so in the description and/or reorders. Scope:

- **Model:** `parent_task` field retained, no schema migration. Annotate
  it in `models.py`: dormant since 2026-08, no code may read or write it,
  see this spec. Add a `validate_data` check that the field is NULL
  everywhere (a non-null value means some path is still writing it).
- **Data:** a data migration **flattens** existing subtask rows to
  top-level (`parent_task = NULL`; dev data: 26 rows). This matters
  beyond tidiness — the field is `on_delete=CASCADE`, so stale child
  pointers would let a task deletion silently cascade into tasks the UI
  no longer shows as related. NULLing makes the dormant field truly
  inert.
- **Backend:** ~18 uses across `apps/jobs/services.py`,
  `apps/schedule/services.py`, `apps/api/tasks/` — remove each;
  scheduling simplifies (no parent dereference in
  `expected_worker_time`). Serializers stop exposing the field.
- **Frontend:** `TasksPanel.svelte` tree rendering and
  `TaskDetailPage.svelte` parent affordances → flat list.
- The "materials on subtasks?" open question (memory, 2026-08-04)
  dissolves: with no code-level hierarchy, materials attach to tasks,
  period.

Contrast with Fee (§5), which is deleted **wholesale, model included**:
Fee is recent, and RM's confidence in its removal is high; `parent_task`
predates everything (2025-08-13 initial structure) and its *shape* may
yet be wanted by a third design.

## 4. Line taxonomy: material or plain

The **only** behavioral distinction on an unbacked line is whether it
describes a material, because that changes crystallization. Main's
`is_material` flag already encodes it — no `freeform_kind` migration, no
fee kind, no work kind. The system does not need to know a line "is a fee":
fee-ness is just a fact about a plain line (nobody will ever attach work to
it), not a model property.

Line shapes on an estimate, post-change:

| Line | Backed by | At acceptance |
|---|---|---|
| Wizard-composed | ≥1 `EstimateLineItemSource` (task/material) | nothing (atoms already on job) |
| Service line | `service_item` FK | crystallizes → Task (incl. flat tasks: setup, delivery) |
| Catalog material | `inventory_item` FK | crystallizes → Material |
| Bare material | `is_material=True` | crystallizes → established Material (reverse-markup cost, earmark) — unchanged from main |
| Adjustment | `adjustment_service` (+ snapshot percent) | nothing; document-only, recomputes per document |
| **Plain** | nothing | **nothing** |

A plain line covers: outcomes ("3 chairs @ $500"), charges (rush, disposal,
government), credits (negative price — sign rules per the adopted Phase 2
fragments). Its price is an estimate like every other line's. Entry-time AC
requirement on hand-lines is unchanged (`assert_all_hand_lines_have_ac`).

The four-way acceptance discriminator in `acceptance.py` loses its default
branch: service → Task, inventory → Material, bare material → Material,
**else → skip** (no source row is written; the line stays a document line).
Idempotency is unaffected (crystallized lines still gain source rows; plain
lines are simply never candidates). Earmarks step unchanged. CO acceptance
(`co_acceptance.py`) simplifies identically: its crystallizing branches keep
service/inventory/material; its Fee fallback and work-line branches die, and
with them the `claiming_kind` threading — a CO's add/replace of a plain line
is document-level composition only, and adjusting the *work* to match an
accepted CO is the planner's job, same as post-acceptance planning (§8).

## 5. Fee is deleted

With estimate-side charges living as plain lines (§4) and transiting to the
invoice via the skeleton (§7), and with the ad-hoc case handled by "start a
draft invoice and add a hand line" (RM decision, 2026-08-06), the Fee atom
has no remaining territory. Delete:

- `jobs.Fee` model + migration (existing Fee rows: crystallize-in-reverse —
  see Migration, §10), `FeeService`, the `/api/jobs/{id}/fees/` endpoints,
  `FeeModal.svelte`, the "Add fee" affordance on the work surface.
- `SOURCE_FEE` in `EstimateLineItemSource`, `ChangeOrderLineItemSource`,
  `InvoiceLineItemSource` (+ serializer branches, `resolve()` arms).
- The invoice wizard's "Fees" group and always-billable carve-out.
- Fee checks in `validate_data`; Fee references in docs.

There is no pure-money atom. Pure money lives on documents.

## 6. Make-a-Deliverable button

A per-line **button** on the estimate — "Make a deliverable from this"
(shorter label TBD at the §9 wireframes) — that **immediately** copies the
line's description / qty / units into a new `Deliverable` on the job and
remembers the linkage. It is an authoring-time action, not a flag that
acts later: **deliverables must exist before the estimate is sent**, since
the customer approves them as part of the quote, and the send-time
deliverables snapshot/freeze machinery is untouched. Acceptance creates no
deliverables (see §8). Availability follows the existing deliverable
editability rules (`DeliverableService.is_editable`) — in practice, the
draft estimate before send, and draft COs.

- Available on **any** line, not just plain lines: on an MQ44-type job the
  estimator may spawn the "100× MQ44" deliverable from the backed cutting
  line, or type deliverables directly as today. The button is a
  convenience wherever a line happens to correspond to a shippable thing —
  never a classification.
- Linkage is a provenance FK (`Deliverable.source_line` → EstimateLineItem,
  SET_NULL) in the `source_scheme` pattern: display and mismatch-badging
  only, **no compute path, no sync**. CO changes qty 10 → 12: a human
  updates the deliverable; at most a passive mismatch badge (line qty vs
  `qty_ordered`). This re-affirms the feature/fees walk-through decision
  (no live sync, no auto-generation at acceptance, no deliverables driving
  task structure).
- Deliverables otherwise unchanged: unpriced, contract scope, ship-tracked,
  send-gate (≥1 deliverable to send an estimate) intact. **No price field
  is ever added to Deliverable.**

## 7. The invoice: agreement skeleton + reconciliation

The wizard's job changes from "compose lines from a pool of atoms" to
"reconcile the agreement against the actuals." Both sources remain visible;
the skeleton leads.

### 7.1 Agreement-line references

New provenance on `InvoiceLineItem`: a reference to the agreement line it
bills — an EstimateLineItem or ChangeOrderLineItem (nullable; hand lines
on the invoice have none). References are **whole-line, always**: partial
per-line pulls were designed, then deliberately cut (wireframe session
2026-08-08 — see §7.4), so no qty rides on the reference.

**Invariant:** an agreement line is referenced by **at most one live
(non-cancelled) invoice**. Enforced in the service under a row lock.
Removing the line from a draft releases the reference (and its mirrored
claims); cancelling an invoice releases all of its references (mirrors
`release_estimate_claims`). A CO remove/replace of an agreement line with
a live reference is blocked, same family as the
can't-retire-invoiced-atoms guard — surfaced as disabled actions with the
reason ("billed on INV-NNNN"), no new machinery.

### 7.2 Skeleton creation — automatic, delete-to-defer

**There is no "start from agreement" button — every invoice on a job with
an agreement starts from it automatically.** *(Provisional — RM
2026-08-06: "not SURE about this but I want to try it and see." Revisit
after real use; the fallback is the same seeding behind an explicit
gesture.)* Creating an invoice seeds one line per **remaining**
`compose_agreement` line — lines fully billed or settled don't reappear;
partially billed lines arrive at their remaining qty — each carrying the
agreement's description / qty / units / price as starting values plus the
§7.1 reference. Per-line, at seeding:

- **Backed agreement line** → the copy is born with invoice-side claims on
  the same atoms (`InvoiceLineItemSource` rows mirroring the estimate's
  source rows), subject to billability gates: an incomplete task or
  unconsumed material arrives *referenced but unclaimed*, flagged, and
  claimable when ready. This is the piece that lets the wizard populate
  estimate copy-lines with atoms rather than duplicate them.
- **Plain agreement line** → the copy arrives with no claims. The
  reconcile act is the invoicer pulling the relevant atoms *into* it
  (existing add-atoms gesture). This closes the double-billing seam at the
  moment someone actually knows which work was sold by which line.
- **Adjustment line** → copies with its snapshot percent; recomputes
  against this invoice's lines (existing behavior).

**Delete-to-defer:** a line the invoicer isn't billing this time —
actuals not in yet, customer negotiation, whatever — is simply deleted.
Deletion releases its reference and mirrored claims, so the line
reappears (at remaining qty) on the next invoice's seeding. A
complementary **"add from agreement"** picker restores a deleted line to
the current draft (mis-deletes, changed minds) — it lists exactly the
remaining agreement lines not already on this draft. Hand lines and
direct atom pulls from the pool remain available as today.

Interactions worth naming: estimate-less jobs seed empty (pool-driven
billing as today). The one-draft-per-job constraint
(`invoicing/0008_unique_draft_invoice_per_job`) composes well with
auto-seeding — the §5 parking-lot flow (draft invoice holding an ad-hoc
charge) just means the draft carries its skeleton lines alongside the
parked hand line until the invoicer prunes and sends.

**The deposit path** (RM, 2026-08-06/08: "progress billing is against the
job as a whole" — invoicers will write "Progress billing $2,500" and must
never be asked to hang it on a part number, task, or material; the
backing is called **"deposit" in all cases** — no "draw" vocabulary
anywhere). A deposit line is a line on the deposit-flagged accounting
category (`AccountingCategory.is_deposit`); once its invoice is paid, it
surfaces as a pullable **credit** on later invoices, deduction locked to
its source — all existing machinery, unchanged. A "progress billing" is
simply a deposit taken mid-job; the line's *description* tells the
customer the story ("Progress billing — one chair ready for pickup"),
the mechanism stays a plain deposit, and the amount is the invoicer's
judgment.

**The button writes the deposit for you.** The existing three-state "Add
Deposit Invoice" affordance (`InvoicePanel.svelte` /
`DepositInvoiceModal`) is retained with one relabel: **no live invoice**
→ "Add Deposit Invoice"; **≥1 live invoice** → "Add Progress Invoice".
Both are the same gesture — prompt for an amount, create an **unseeded**
draft with one deposit line on `default_deposit_accounting_category`
(both variants, for now — RM is asking the accountant whether progress
billings need their own category; if so, add a parallel key coached like
`_resolve_deposit_category`). Neither path stores an invoice type:
"unseeded" is only how the draft was born; a derived "Progress billing"
label on the customer document computes from the content being all
deposit lines — the no-invoice-mode principle (§7.4) holds.

The settlement invoice pulls paid deposits from the **"Deposit credits"**
group (the existing name and machinery), kept prominent so nothing paid
in advance is forgotten. Edge already decided: under auto-seeding a
fresh regular draft is never zero-line on an agreement job, so the old
"Make this a deposit invoice" state only arises after the invoicer
clears a seeded draft — and one-draft-per-job means wanting a deposit
invoice while a seeded draft exists requires clearing it first.

### 7.3 Backing — actuals by default

Every line carries a **backing** (the chip column, both documents): what
its amount stands on. On the invoice: `estimate` (seeded values, nothing
attached), `actuals`, `edited`, plus the quiet `actuals = estimate ✓`
variant, `deposit`, and `deposit credit`.

**Attachment recalculates immediately** (RM, 2026-08-08 — reversing the
earlier attachment-never-moves-money position): attaching actuals flips
the line to the actuals backing and re-derives it on the spot, using the
existing in-sync presentation rule (price = Σ actuals ÷ qty, e.g.
3 ea × $680.25). The estimate stays visible as the reference figure
("est was $1,500.00 · +$540.75"). Backing flips freely — **Use
estimate** ⇄ (then "Use actuals" appears) ⇄ **Edit** by hand — and while
on a non-actuals backing, attaching or removing atoms only updates the
reference figure. This is the existing in-sync/override machinery with
actuals as the arrival state; consequences: seeded backed lines arrive
already on actuals (case 1 — the task-backed estimate that went to plan
— is *genuinely* boring: read and send), and the invoice total moves
when work attaches, visibly and reversibly, because attachment IS a
billing decision.

If part of a line's backing work was already final-billed on an earlier
invoice, the reference figure sums only the atoms attachable now — the
billed work shows in the pool with its INVOICED state rather than
inflating the comparison.

The **pool** ("Job actuals not on this invoice") is reframed, not
removed: it is evidence, never a checklist — unbilled actuals are the
invoicer's call and the section never nags (Option-D rejection, RM
2026-08-08). Provenance marking in the pool is **positive-only**: a
"descoped by CO-N" chip where an accepted-document claim was removed by
a CO (queryable from retained source rows — no new schema); an unmarked
row means nothing, since hand-line agreements legitimately cover work
with no task-level claim. Atoms remain whole-claim; there is no per-unit
atom slicing. Unreferenced pool billing (T&M jobs, estimate-less jobs)
works exactly as today, via "Bill as its own line".

### 7.4 Advance money: two shapes only

**No invoice-level mode.** An invoice has no progress-vs-final identity;
the derived "Progress billing" customer-document label computes from
content (all deposit lines), never from a stored type.

Advance money comes in exactly **two permitted shapes** (RM, 2026-08-08):

1. **Deposit lines** — against the job, on the deposit rail (§7.2).
   Subtracted later as deposit credits on the settlement invoice.
2. **Work-based progress billing** — completed atoms billed as their own
   lines mid-job ("Bill as its own line"). This is *final* billing, not
   an advance: the atoms are claimed exactly-once, **no credit ever
   exists**, and the settlement is smaller *by their absence* — they
   cannot attach or re-bill (RM confirmed 2026-08-08).

**Per-line partial pulls are deliberately NOT built.** The design existed
(quantified references, a Σ-qty invariant, family arithmetic, a
settle-whole vs bill-remainder question, auto-minted deduction rows) and
was cut in the wireframe session: billing "1 of 3" of an agreement line
implies an identity the system does not have — it cannot know *which*
chair that unit is, or how it relates to a deliverable — and the
machinery existed only to serve that fiction. The pickup-cabinet case is
served by a deposit line whose description names the event. Revisit only
after the rest is real and in use.

**Line taxonomy** — every invoice line is one of:

| Line | Advance or final | Later subtraction |
|---|---|---|
| Agreement line (seeded or restored; whole, one live invoice) | final | — (it *is* the accounting) |
| Deposit line (deposit-flagged AC; deposit or progress billing) | advance (against the job) | deposit-credit pull |
| Atom billed as its own line (pool) | final | — (claimed exactly-once) |
| Hand line (manual, no ref, no atoms, ordinary AC) | **final** | — (bills something outside the agreement; exists only here) |
| Deposit credit (pulled onto the settlement) | the subtraction itself | — |

Hand lines and atom pulls are final content and suppress the
Progress-billing label; deposit lines produce it. The "people will type
'progress billing $2,500' as a hand line" hazard is answered by making
the right way the easy way: the §7.2 button mints exactly that line on
the deposit rail. A plain hand line on an ordinary AC remains a
declaration that its charge is final. (The inverse mistake — hand-typing
a charge that duplicates an agreement line — is shrunk by auto-seeding:
the real line is already on the draft, so the duplicate sits visibly
beside it.) QBO: everything pushes as ordinary lines; the adopted
negative-total send gate still applies.

### 7.5 What stays structural vs. human

Structural: atoms exactly-once (existing claims); an agreement line on at
most one live invoice (§7.1); deposit credits locked to their source
line (existing machinery); billed-elsewhere work excluded from reference
figures (§7.3). Human, by design: deciding that a given set of atoms
"is" a plain line's work (declared at reconcile time, with full context
on screen); the amount of every deposit; the final price of every line
(principle 3).

## 8. Acceptance and planning

On a hand-line-heavy job, acceptance now produces an approved job —
possibly with few or no tasks. (Not deliverables: those were created at
authoring time — §6 — and frozen at send, so the customer approved them
with the quote.) That is the honest shape: winning the work and planning the work are
different acts, and the **Approved → In Progress** transition has always
existed to hold that gap (planning happens in Approved; releasing to the
floor means it's set up enough to start). No new mechanism; at most a
UI-clarity pass on the Approved state (out of scope here; LATER.md
candidate if it stings in practice).

## 9. The settled surface (wireframe session 2026-08-08)

The reconcile-UI wireframes were built and reviewed with RM on
2026-08-08 (fourteen revisions; the visual record with annotated
rationale lives at
https://claude.ai/code/artifact/9e73a22a-b0e2-4cc4-bc9d-816653364fc9).
This section records the settled shape; the artifact is the picture.

### 9.1 Shared shape, both documents

- **Three modes, flipped in place** at the same URL (the existing
  `stores/jobWorkspace.js` per-document mode-memory idiom, vocabulary
  grown by one): **Edit / Customer / Reorder**. Never a modal for a
  mode — modals are reserved for editing forms (the per-line Edit).
- **Customer view** is read-only and collapsed to exactly the outgoing
  document (renumbered, no backing, no atoms, no struck rows).
  **Reorder view is the customer view plus an arrows column** —
  identical rows, so ↑↓ carries no sub-line ambiguity. Line numbers are
  the document's own (`line_number` + existing renumber service);
  provenance small-text preserves the estimate-line correspondence.
- **One editing view**: lines above (each with its backing nested as
  indented atom rows), the uncovered work/actuals section below.
  On the ESTIMATE this **merges today's two modes** (lines view +
  reconcile mode) into one surface. Authoring buttons above the table:
  "Add line" (unified picker) and "Add adjustment" (estimate and
  invoice; never on COs — adjustments are estimate-only).
- **Object-first composition**: checkboxes on the work/actuals rows;
  while anything is ticked, every line offers **"Add selected here"**
  (no count in the label) and the table's foot shows the dashed
  **"＋ New line from selected"** placeholder row — creating the line
  derives its values (single-atom copy, or the uniform-bundle/blanks
  rule) and opens its Edit form immediately. Unticked rows keep
  **"Bill as its own line"** / "Add as its own line". (The
  task-material Move gesture is NOT the model — RM: it is
  destination-first, i.e. backwards, and slated for its own fix.)
- **Per-line actions**: **Edit** (modal — description, qty, units,
  price; editing price flips backing to `edited`), **Remove** — the
  word "delete" does not exist on document surfaces. On the estimate,
  Remove releases backing work untouched; on the invoice, "Remove from
  invoice" leaves a struck in-place row ("on the estimate, not this
  invoice", amount parenthesized and excluded) with one-click
  **Restore**; either way the line reseeds on the next invoice. The
  restore picker ("add from agreement") lists remaining lines not on
  the draft — whole lines only.
- **"→ Deliverable"** per line on the estimate (spec §6's
  make-a-deliverable button; label wording is RM's to finalize).

### 9.2 Backing chips

The column is **"Backing"** on both documents. Invoice: `estimate` /
`actuals` / `edited` / `actuals = estimate ✓` / `deposit` /
`deposit credit`. Estimate (no actuals exist yet): **`planned work`**
(tasks, or tasks + materials), **`planned materials`** (materials
only), **`from catalog`** (service items AND catalog inventory items
not yet on the job as a Material — the two deferred crystallization
kinds), **`hand line`**, **`edited`** (shows "work totals $X" as the
reference — today's ⚠ out-of-sync made a first-class chip).

### 9.3 Change orders: amend the agreement in place

The CO editing view is **one table: the agreement as it will read if
accepted**, CO-authored rows tinted and numbered CO 1, CO 2…:

- Untouched agreement lines carry **"Remove via CO"** / **"Replace…"**;
  acting strikes the original in place (Undo un-amends). A removal is
  the strike — it gets no row of its own. Struck amounts are
  parenthesized and excluded.
- **"Replace…"** opens the edit modal prefilled from the original, and
  the replacement **inherits the original's backing** — the claims move
  to it (the `revise_estimate` move-the-source-rows pattern applied to
  one line), marked "inherited from line N"; further work attaches
  normally. Ordinary backing rules apply afterward (a typed price over
  a work total reads `edited` with the reference).
- CO add-lines compose exactly like estimate lines (same work section,
  same placeholder, same chips). No "Add adjustment".
- An agreement line with a live invoice reference shows both actions
  disabled with the reason ("billed on INV-NNNN") — §7.1's guard,
  rendered.
- Footer: **original / this CO / revised** totals; the revised figure
  is what invoice seeding draws from after acceptance (CO-origin lines
  seed with provenance "CO-N line M").
- Customer view is the conventional delta document (revised lines with
  delta amounts, removals negative, change total, revised agreement
  total); reorder covers the CO's own lines only.
- Downstream: work whose accepted-document claim a CO removed shows a
  **"descoped by CO-N"** chip in billing's pool (positive-only marking,
  §7.3) — "we were supposed to do this and there was a CO" at the
  moment the invoicer decides whether to bill it.

### 9.4 Complexity checkpoints (acceptance criteria)

1. **"3 chairs" is one gesture:** type the line. "→ Deliverable" is one
   optional click. No kind pickers beyond the existing material
   checkbox, no "priced deliverable" concept anywhere.
2. **The estimator's flow is unchanged** on both archetype jobs (chairs
   and MQ44), and one surface replaces two estimate modes.
3. **The common invoice is boring:** create invoice → skeleton is just
   *there* (no button), backed lines pre-claimed and already on
   actuals → remove what's not being billed → send. Case 1 (estimate
   went to plan) is read-and-send.
4. **The invoicer never meets** reference rows or claim mirroring by
   name — they see backing chips, est-vs-actual references, struck
   rows, and a pool that never nags.
5. **The boring case renders as nothing but an invoice** — every
   mechanism above appears only when the job's shape summons it.

**UI work is a first-class workstream.** The wireframes ARE the design
(ground-up; the old two-column `ReconcileMode` is retired as a
presentation — claims plumbing and in-sync services survive
underneath). Build to the artifact; deviations go back through RM.

## 10. Migration and sequencing

Phased, each phase leaving main green:

1. **Cherry-pick Phase 1** from `feature/fees` (task money, preset
   RateScheme, flat tasks, adjustment snapshots). Fresh-DB suite run
   (house rule after migration changes).
2. **Subtask removal** (§3): flatten data (NULL migration), field stays
   dormant with comment + validate_data NULL check, simplify services/UI.
3. **Skeleton + references** (§7): reference schema (one live invoice
   per agreement line), auto-seeding, claim mirroring, backing model,
   the three-mode surface for both documents per §9 — the wireframes
   were settled with RM 2026-08-08; build to the artifact.
4. **Deposit path** (§7.2/§7.4): the relabeled button, unseeded drafts,
   deposit-credit prominence. Small — the rail already exists.
   *(LANDED 2026-08-09: live-invoice-keyed relabel + progress-billing line
   description, and the all-deposit draft withholds uncovered work / Add
   from agreement per RM's review note.)*
5. **Crystallization narrowing + Fee deletion** (§4, §5): acceptance/CO
   discriminator change; delete Fee. Existing Fee rows: those claimed by a
   live estimate line become nothing (the line is already the record —
   drop the fee source rows; the line reverts to plain); those claimed by
   invoice lines have already been billed (drop source rows, keep the
   invoice lines' stored values); unclaimed job fees are surfaced to RM
   for manual disposition before the migration (expected count: small).
   `validate_data` sweep updated in the same phase.
   *(LANDED 2026-08-09: acceptance/CO discriminator narrowed to
   service_item → Task, inventory_item → Material, is_material →
   Material, else → nothing; `Fee` model deleted (migrations
   `estimates/0045`, `invoicing/0024`, `jobs/0062`); plain hand-lines
   never crystallize and stay document lines, transiting to invoices via
   agreement-line references instead of a Fee atom.)*
6. **Phase 3 + Phase 5 adoption** (re-implement or cherry-pick per §2).
7. **Docs pass**: estimates-and-prices, jobs-and-tasks,
   invoicing-and-expenses, data-constraints, schedule.

Each phase: TDD, targeted backend modules + Vitest per task, full suite at
final verification, e2e for user-reachable flows in the same phase.

## 11. Open questions

**CO-surface decisions (RM, 2026-08-09 session — settled for the CO
amend-in-place phase):**

1. **Backing inheritance moves at ACCEPTANCE, not authoring.** Drafts
   stay side-effect-free; the draft view derives the inherited-backing
   preview through `ChangeOrderLineItem.target_line_item` (which already
   exists — nothing new to remember). Abandoning/rejecting a draft CO
   therefore costs nothing. At acceptance the claims move to the
   replacement line (revise_estimate move-the-source-rows pattern,
   applied per line).
2. **The amended-agreement view is composed SERVER-SIDE** (a
   compose_agreement variant applying the draft CO), so interrupted work
   isn't lost and the footer's revised total, seeding, and the view can
   never disagree.
3. **Descope provenance is STORED, not derived** — stamped at acceptance
   (schema isn't stable anyway; stored is safer than deriving from
   struck_atom_keys walks). Feeds the billing pool's "descoped by CO-N"
   chip.
4. **COs can change adjustment lines**: Remove-via-CO (discount
   rescinded) and Replace (rush fee lowered — the Replace modal gets an
   adjustment variant editing the percent, not qty/price). Adjustments
   carry no claims, so no inheritance mechanics apply. "Add adjustment"
   stays absent from COs.
5. **Single CO per job for now.** Multi-CO chaining (parent/version)
   stays in the model but the surface scopes to one CO; don't build the
   chain view.
6. **"→ Deliverable" button deferred to the cycle after the CO surface.**
   Post-acceptance readability unchanged: the CO tab in the estimates
   area is the record; the original estimate stays visible as-was with
   the "amended" badge.

- §7.1 implementation shape: nullable FK pair on `InvoiceLineItem` vs. a
  reference-row table — simpler now that references are whole-line; pick
  at implementation time.
- CO replacing an agreement line referenced by a live invoice: blocked
  (§7.1, rendered per §9.3) — is "block" right, or should it force
  removing it from the draft first? Ship the block; decide when a real
  case appears.
- Where the draft-invoice-as-charge-parking-lot flow (§5) needs UI help,
  if anywhere.
- Whether progress billings need their own accounting category or share
  the deposit one — RM asking the accountant; until answered, both
  button variants use `default_deposit_accounting_category` (§7.2).
- Auto-seeding (§7.2) is a **trial decision** — RM wants to live with
  "every invoice starts as the remaining agreement, remove to defer"
  before committing. The worst friction cases are routed around it
  (deposit/progress invoices never seed) — watch whether any *regular*
  invoice still hits remove-most-of-a-large-skeleton in practice.
- "→ Deliverable" button label wording (§9.1) — RM's to pick.

**Deferred, deliberately:** per-line partial pulls and everything they
required — quantified references, Σ-qty, family arithmetic, the
settlement question, auto-deduction rows (§7.4, cut 2026-08-08).
Revisit only if real use demands billing part of an agreement line as
an advance.

*(Resolved 2026-08-08, wireframe session: attachment recalculates
immediately — attachment IS a billing decision, reversible per line
(§7.3). Reorder is a page mode, not a modal. Replacements inherit
backing (§9.3). Provenance marking is positive-only. "Deposit" is the
universal advance vocabulary; work-based progress billing earns no
credit. Earlier resolutions 2026-08-06: settlement family arithmetic
and the atoms-only-on-final restriction — both now moot with per-line
pulls deferred.)*

## 12. Acceptance walkthrough — the fifteen items

The RM list (2026-08-02 session; compressed record in the feature/fees
spec). Every item must have a defined shape here:

| # | Item | Shape under this design |
|---|---|---|
| 1 | N finished items we manufacture | Plain line ("3 chairs @ $500") + make-a-deliverable button before send. Work planned as ordinary flat/preset tasks in Approved. Invoice: skeleton line, invoicer attaches the chair-work atoms, est-vs-actual, bill. |
| 2 | Resale material (after cutting parts) | Catalog/bare material line → Material (unchanged). |
| 3 | N parts from a material | Cutting task(s) (preset, machine-minutes) + material line; deliverable via gesture or typed. |
| 4 | Setup fee | Service line → **flat task** (it's work). |
| 5 | Delivery | Flat task (work) — or plain line if nobody tracks it. |
| 6 | CAD/design time | Hourly preset task (unchanged). |
| 7 | Engraving | Preset task, modifiers (unchanged). |
| 8 | Cutting charges | Preset tasks in machine-minutes; wizard translates to per-piece on the document (existing bundle presentation). |
| 9 | Jigs kept for re-use | Ordinary tasks + materials; no asset registry (standing RM decision). |
| 10 | Customer-funded specialized tools | Same as 9. |
| 11 | Outsourced work | Phase 5: flat task sell side, PO link, reconciliation (adopted, §2). |
| 12 | Site visits | Flat task (work, priced up front). |
| 13 | Untracked consumables | Plain line, or percentage adjustment, or absorbed — the policy choice remains open and nothing here forecloses any option. |
| 14 | Deposits | Already built; deposit credits unchanged (§7.4 notes the shape kinship). |
| 15 | Credits | Plain line with negative price on estimate or invoice; negative-total send gate. |
