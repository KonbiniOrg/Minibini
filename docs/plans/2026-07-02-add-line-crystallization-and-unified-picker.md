# Resolve the job-owns-atoms "Add line" drifts — crystallization timing + the unified picker

> **Status: follow-on plan (starter).** The job-owns-atoms / documents-as-lenses refactor
> shipped; this plan closes the two behavioral drifts that remain between the original design
> and the built code. It **replaces** the two now-executed plan docs
> (`2026-06-29-job-owns-atoms-documents-as-lenses.md` and `-implementation-plan.md`, deleted —
> the durable record is `docs/designs/`). Design-level, not a TDD task plan. Tags
> **[SETTLED]** (agreed), **[DEFAULT]** (chosen here; flag to change), **[OPEN]** (resolve when
> this is fully specced). Current code **works** — this is deliberate follow-on, not a bug fix.
>
> Scope note: a **third** original-design drift — the job overview being restructured (read-only
> overview + authoring on the task-list page, the Plan/Client-View toggle and "Client View"
> concept dropped) — is **accepted as final**. It needs no work here; `docs/designs/` are being
> updated to match it. Separately, change-orders-drive-atoms, freeform-material procurement, and
> the schedule pass have their own follow-on plans.

## Background: what drifted, and the direction chosen

Two "Add line" affordances on the estimate disagree about **when a pick becomes a Job atom**:

- **Inventory** picks are **deferred** (**atom-on-approval**): `add_line_item_from_pli`
  (`apps/estimates/services.py:289`) makes a *document row* carrying `inventory_item`, and the
  `Material` is minted only at **acceptance** (the `inventory_item → Material` branch in
  `apps/estimates/acceptance.py:55`). Pure hand-lines are likewise deferred (→ `Fee` at acceptance).
- **Service** picks are **immediate** (**atom-on-add**): the `AddServiceItemModal` →
  `add-from-template` (`apps/api/jobs/views.py:449`) creates a `Task` *now*, then
  `line-items-from-atoms` links the line to it. This is the odd one out.
- The **unified picker** was **torn out** with the worksheet/Plan side and never rebuilt; today
  the affordances are split (Part 2 rebuilds it).

**Decision (2026-07-02): unify on _atom-on-approval_ (deferred).** An estimate is a document; its
lines stay pure document rows while the estimate is `draft`, and **acceptance** is the single moment
work crystallizes onto the Job. This keeps the speculative (quote) and committed (job) worlds cleanly
separated, means deleting a draft line strands nothing (no atom ever existed), and dovetails with the
freeform-material procurement plan, whose lot/earmark machinery is *itself* only minted at acceptance
for pre-approval jobs (`2026-06-30-freeform-material-procurement-inventory.md` → Mint timing). So the
inventory + hand paths are already correct; the work is to **make the service pick deferred too** and
give acceptance a symmetric three-way crystallization.

**Rejected alternative (atom-on-add).** Making inventory/hand immediate like service was the earlier
lean, but: it needs orphan-atom cleanup + provenance (deleting a draft line must collect a stranded
atom); it can mint duplicate speculative atoms across concurrent draft estimates; and — decisively —
it does **not** actually unlock pre-approval procurement, because the freeform plan withholds the
procurement *lot* until acceptance regardless, leaving an early-born atom in an un-procurable dead
zone. Atom-on-approval avoids all three.

> **Note — direct job authoring is unaffected.** "Add Task" and "Add Material" **directly on the
> job** (the task-list authoring surface) still create **real atoms immediately, including
> pre-approval**, for the rare genuine cases (a long-lead material you must order before the quote is
> signed; work that legitimately starts early). That path is *job* authoring, not an estimate-line
> pick — it is intentionally kept. Such a pre-approval atom can still be pulled onto an estimate line
> via the wizard ("Show Tasks & Materials"), producing an ordinary atom-backed line. What changes here
> is only the estimate's **pick** affordances, which mint no atoms until acceptance.

---

## Part 1 — Unify add-line crystallization on atom-on-approval (defer the service pick)

**[SETTLED direction]** Make the **service** pick deferred, to match the inventory + hand paths.
An estimate line records *what was picked* as a descriptor and crystallizes to the matching atom at
acceptance. The estimate stays a pure document until accepted.

### The service descriptor (parallel to the existing `inventory_item`)

Today `BaseLineItem.inventory_item` (`apps/core/models.py:332`) is exactly this kind of deferred
descriptor — an estimate line "remembers" a picked `InventoryItem` without a `Material` existing yet.
Give the service pick the same treatment:

- **[DEFAULT]** Add a `service_item` FK on **`EstimateLineItem`** (→ `estimates.ServiceItem`, the
  Task-template class with `generate_task(container, est_qty, …)` at `apps/estimates/models.py:423`),
  parallel to `inventory_item`. Scope it to `EstimateLineItem` rather than `BaseLineItem`: only
  estimates crystallize a service pick into a `Task` (invoices bill actuals; they never generate work
  — see Part 2 Q on invoice parity). The line's existing `qty` (`BaseLineItem`) carries the `est_qty`.
- **Change the service-pick affordance to set the descriptor, not create a Task.** Replace the
  `AddServiceItemModal → add-from-template → line-items-from-atoms` chain with an
  `add_line_item_from_service(estimate_pk, service_item_pk, qty)` service method that mints a draft
  document line carrying `service_item` + `qty` **and snapshots the priced values at instantiation**
  (`price`, `accounting_category`, `description`, `units`) — byte-for-byte the same shape as
  `add_line_item_from_pli` does for inventory (see next section). No `Task`, no source link, until
  acceptance.

### Symmetric three-way crystallization at acceptance

`EstimateAcceptanceService.on_accept` (`apps/estimates/acceptance.py`) already walks every hand-line
(no source, not an adjustment) and branches on `inventory_item`. Extend it to a clean three-way,
discriminating on which descriptor the line carries:

```
on_accept, per hand-line (no source, not an adjustment):
    has service_item   → ServiceItem.generate_task(job, est_qty=li.qty,
                            allow_superseded_scheme=True)                     → Task
    has inventory_item → MaterialService.create_on_job(…)                     → Material   (unchanged)
    neither            → Fee.objects.create(…)                               → Fee        (unchanged)
  …then source-link the line to the atom it created (SOURCE_TASK / SOURCE_MATERIAL / SOURCE_FEE),
     and finally InventoryService.create_earmarks_for_job(job) as today.
```

This *keeps* the inventory→Material branch (it was going to be retired under the rejected
atom-on-add plan; under atom-on-approval it stays) and *adds* the service→Task branch. `on_accept`
grows from two branches to three — the accepted, bounded cost of this direction.

### How a deferred service line behaves before acceptance — snapshot at instantiation

A service line **snapshots its priced values at instantiation**, exactly as the inventory descriptor
already does (`add_line_item_from_pli` copies `description`/`units`/`price`/`accounting_category` off the
`InventoryItem`). This is the "documents are self-contained records" principle: the line owns its
numbers and never re-derives them from the catalog afterward.

- **Price [SETTLED — snapshot].** At pick, `add_line_item_from_service` computes the effective unit rate
  `service_item.rate_scheme.effective_rate(service_item.default_active_modifiers)` (e.g. base $40 + a
  10% modifier → **$44**; pricing is linear, so a single unit rate fully captures it) and stores it as
  `line.price`. The line's amount is then plain `qty × price` — self-contained, no live scheme lookup,
  no pinned-scheme FK. `service_item` remains on the line purely as the **crystallization target**
  (which template to `generate_task` from), not as a live price source.
- **Accounting category [SETTLED — snapshot].** `line.accounting_category` is set at pick from
  `service_item.effective_accounting_category` (= `rate_scheme.accounting_category`). So the line
  simply **has** an AC and passes `assert_all_hand_lines_have_ac` like any other populated line — no
  special exemption, uniform with inventory.
- **Crystallization derives the atom fresh.** At acceptance, `generate_task` builds the Task from the
  ServiceItem's **then-current** scheme. Absent any price change this equals the line's snapshot; if a
  rate changed in between, the Task reflects the new rate and **differs** from the snapshot — see below.

### Price changes are a human/organizational event — no software guards [SETTLED]

We deliberately build **no** superseded-scheme pre-flight guard, soft-flag, or honor/block decision.
Per shop reality: **any price change is a big, rare, org-wide-known event** — everyone is aware it
happened and is already watching jobs near that time for adjustments. So if a service line's snapshot
and its crystallized Task diverge because the underlying rate moved, that divergence **surfaces on the
Task** (and again at invoice, which bills actuals), exactly where a human is already looking, and is
reconciled there. Software does not need to detect or prevent it.

The only code concession is defensive, not "handling": crystallize with
`generate_task(..., allow_superseded_scheme=True)` (bypass exists, `apps/jobs/services.py:761`) so that
a superseded scheme yields a Task instead of **aborting acceptance** with `SchemeSupersededError`. No
flag, no guard, no re-pick prompt.

> **⚠️ Verify before building (added at RM's request; partially confirmed by reading `supersede()`):**
> `RateScheme.supersede()` (`apps/jobs/models.py:538`) renames the old scheme, mints the new one, and
> sets `old.replaced_by` — it does **not** repoint `ServiceItem.rate_scheme` (or `Task.rate_scheme`).
> RM recalls supersession *used to* "update all its catalog users." **Confirm whether any
> catalog-repoint mechanism still exists and is test-covered.** This only affects *which benign path*
> runs — either way we build no handling: if catalog users are repointed, the crystallized Task simply
> reflects the new rate (human reconciles); if not, the `allow_superseded_scheme=True` bypass keeps
> acceptance from aborting. (Search: `replaced_by` / `supersede` on `RateScheme` and its `ServiceItem`
> users.)

### Orphan-atom cleanup — no longer a problem

Because draft lines create **no atoms**, deleting a draft estimate line strands nothing — the whole
provenance / safe-delete-gate machinery the atom-on-add plan needed simply **evaporates** on the
estimate side. Line delete removes a document row; there is no atom to walk back. The only atom
lifecycle left is the ordinary **direct job authoring** one (`JobService.delete_task` /
material delete), which already exists and already refuses to delete worked/blep-bearing atoms —
unchanged by this plan.

### Settled decisions

1. **No override capture [SETTLED].** The service pick captures `service_item` + `qty` plus the
   snapshot values (`price`/`accounting_category`/`description`/`units`), but **no** modifier/name/time
   *overrides* — `name` / `active_modifiers` / `est_worker_time` take template defaults at
   crystallization. Users edit the resulting Task freely afterward, so there's no need to freeze
   picked-time overrides on the estimate line. (The snapshot `price` is derived from those same
   template defaults at pick, so the quoted line and the default-built Task agree.)
2. **Invoices do not get a service descriptor [SETTLED].** The invoice `LineItemModal` inventory pick
   stays as-is; invoices bill *actuals* and never generate work, so a service pick there is
   meaningless. Service deferral is estimate-only (mirrors why "Add from Service" was estimate-only).

### Open questions [OPEN]

1. **One-open-chain assumption.** Deferred crystallization leans on a job not having concurrent draft
   estimates that would each crystallize the same pick. We believe one live estimate chain per job is
   the rule (then change orders) — confirm it's actually enforced server-side, not just in the UI
   (tracked in `docs/designs/LATER.md`).
2. **Migration/regeneration** — no dev-DB migration (regenerate); the converter/seed generator must
   emit service picks as **deferred descriptors** on draft estimates (and as crystallized Tasks on
   accepted ones), consistently with inventory.

---

## Part 2 — Rebuild the single/unified "Add line" picker

**[SETTLED intent]** Rebuild the **one** Add-line picker the design called for — a single affordance
that searches the job's catalogs and turns a pick into the right **descriptor** (which then
crystallizes at acceptance, per Part 1): **Service** (`ServiceItem`) → `service_item` line → `Task`,
**Material** (`InventoryItem`, or freeform) → `inventory_item`/freeform line → `Material`,
**free-text / (future) `FeeItem`** → bare hand-line → `Fee`. It was **over-aggressively removed** when
the Plan side was torn out; the search backends survived (`/api/service-items/?search=`, the inventory
catalog filter), only the unified UI was lost.

**This part deserves deeper design before building** — the current split affordances *work*, so
there's no rush, and the picker's UX (one control spanning three catalogs + a freeform escape, its
placement on the overview vs. estimate vs. invoice, and how it supersedes today's `LineItemModal`
toggle + `AddServiceItemModal` + inventory picker) wants thinking-through, not a mechanical rebuild.

### Notes toward the design

- The search UX to revive already lives in main as `frontend/src/components/PriceListPicker.svelte`
  (+ `frontend/tests/components/PriceListPicker.test.js`) — the evolved descendant of the original
  worksheet-era three-catalog picker. Use it as the reference; its backends are
  `/api/rate-schemes/?search=` and the inventory `is_catalog` catalog filter.
- Consolidate today's separate estimate affordances (Add Line Item + Add from Service + inventory
  toggle) behind the one picker; keep the freeform/manual escape (hand-line → Fee).
- **This picker is where the "which atom type" signal lives** — which resolves the standing
  `LATER` item *"Hand-typed estimate material lines can't crystallize into Materials"*: an explicit
  Material-vs-Fee choice in the picker (not accounting-category inference) sets the line's
  descriptor (`inventory_item` / freeform-material marker vs. bare hand-line), which then drives the
  three-way crystallization at acceptance. Fold that concern in here.
- Part 1 (deferred service descriptor + three-way crystallization) should land first — the picker
  routes a pick to the right **descriptor** (service → `service_item`, material → `inventory_item` or
  freeform marker, free-text → bare hand-line), all of which resolve to atoms at acceptance, not on
  add.

### Open questions [OPEN]

1. **Scope of surfaces** — one picker shared by job overview + estimate + invoice, or per-surface
   variants (invoice may differ — see Part 1 Q2).
2. **Freeform material path** — how the picker mints a freeform (non-catalog) `Material` and its
   transient lot (ties to the freeform-material-procurement follow-on plan).
3. **Relationship to the wizard** ("Show Tasks & Materials") — the picker adds a *new* line (a
   descriptor that crystallizes at acceptance); the wizard pulls an *existing* job atom onto a line
   (atom-backed immediately). Keep both, or does the picker subsume the pull?

---

## Non-goals / relationship to other plans

- **Overview restructure / Client-View removal (Drift C)** — accepted as final; docs updated, no work.
- **Change-orders-drive-atoms** — separate follow-on (`2026-07-02-change-orders-drive-atoms.md`);
  its "CO line authoring gets inventory + service picks" reuses whatever this plan settles.
- **Freeform-material procurement** (`2026-06-30-…`) — the freeform `Material` + transient-lot minting
  the picker's freeform branch will lean on.
- **Schedule pre-approval pass** (`2026-06-29-…`) — unrelated; separate.

## Rollout / testing (when built)

No dev-DB migration (regenerate). TDD. Part 1:

- a service pick on a draft estimate creates a document line carrying `service_item` + `qty` and
  **no `Task`**, with `price`/`accounting_category`/`description`/`units` **snapshotted at pick** from
  the ServiceItem (`price = effective_rate(default_modifiers)`);
- the line's amount is plain `qty × price` from the snapshot (self-contained; unaffected by later
  catalog changes), and matches the crystallized Task's amount absent an intervening price change;
- the snapshotted AC populates the line so it passes `assert_all_hand_lines_have_ac` normally (no
  exemption), uniform with inventory;
- acceptance crystallizes the line into a `Task` (alongside inventory→`Material` and hand→`Fee`),
  source-links it, and earmarks — using `generate_task(..., allow_superseded_scheme=True)` so a
  superseded scheme does **not** abort acceptance (no guard / flag / re-pick prompt — divergence is
  reconciled by humans at invoice time); plus the ⚠️ verification of whether supersession repoints
  catalog users;
- deleting a draft line strands no atom; direct Add Task / Add Material on a pre-approval job still
  create real atoms immediately and remain claimable by an estimate line via the wizard.

Part 2: the unified picker routes a pick to the right descriptor (Service→`service_item`,
Material→`inventory_item`/freeform, free-text→bare hand-line), each crystallizing at acceptance, across
the intended surfaces.
