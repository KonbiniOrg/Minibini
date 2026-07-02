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

## Background: what drifted

The original design had **one "Add line" picker** over the job's catalogs that turned a pick
into a **live Job atom immediately**: pick an `InventoryItem` → a `Material` on the Job; pick a
Service (`ServiceItem`) → a `Task`; pure free-text → a hand-line that crystallizes to a `Fee` at
acceptance. As built, that split two ways:

- **Service** picks *are* immediate (the `AddServiceItemModal` built 2026-07-02 → `add-from-template`
  creates a Task → `line-items-from-atoms` links it). **Matches the design.**
- **Inventory** picks are **deferred**: `add_line_item_from_pli` makes a *hand-line* carrying
  `inventory_item`, and the `Material` is minted only at **acceptance** (the
  `inventory_item → Material` branch in `apps/estimates/acceptance.py`). **Drifted.**
- The **unified picker** was **torn out** with the worksheet/Plan side and never rebuilt; today
  the affordances are split (job task-list: Add Task/Material/Fee → immediate atoms; estimate
  detail: Add Line Item [manual/inventory, deferred] + Add from Service + Add Adjustment).

Both drifts are cosmetically fine today but leave the model inconsistent. This plan resolves them.

---

## Part 1 — Unify add-line crystallization timing (make inventory immediate too)

**[SETTLED direction]** Bring the **inventory** pick to parity with the service pick: picking an
`InventoryItem` in an Add-line flow creates a **`Material` on the Job immediately** and links the
document line as **atom-backed** — matching the original design and the service pick. Once both
are immediate, the `inventory_item → Material` crystallization branch in `acceptance.py` can be
**retired** (acceptance goes back to only crystallizing pure hand-lines → `Fee`, as the original
`on_accept` did). **[DEFAULT]**

Why immediate over "make service deferred too": the immediate model is what the design always
described, it removes the acceptance special-case, and it means a picked material is a real,
schedulable/earmarkable/COGS-able atom from the moment you pick it — consistent with job-owns-atoms.

### The orphan-atom cleanup problem (inherited from the immediate model)

Immediate creation means deleting the document line can leave the created atom stranded on the Job
(as already true for the immediate **service** pick). The `EstimateLineItemSource` link cascades on
line delete (the *link* is cleaned up) but the atom is not, and it can't be safely auto-deleted by
"walking the source back," because:

1. the source row for a picker-created atom is **indistinguishable** from one for an atom that
   pre-existed on the Job and was merely *claimed* (via the wizard) — no provenance field, so a
   blanket delete would destroy legitimate pre-existing work;
2. it would violate the documents-as-lenses invariant that unlinking an atom never deletes it
   (`remove_atoms_from_line_item` in `apps/core/wizard.py` deletes only the source/line, never the
   atom);
3. `JobService.delete_task` refuses when the Task is `in_progress`/`complete` or has bleps.

**[DEFAULT]** Safe cleanup needs **provenance** — mark atoms created by an Add-line pick — plus a
no-bleps/no-actuals/no-other-claims check before removing one on line-delete. A picked-then-deleted
atom that's untouched should be collectible; anything worked/claimed stays.

_Narrowing constraint:_ a document line is only deletable while its estimate is `draft`, which in
the **primary** flow means the Job is still pre-approval (`draft`/`submitted`) — uncommitted
planning work, lower stakes. **But not universally:** the estimate→job status sync is forward-only
(`apps/estimates/signals.py`), so a draft estimate can also sit on an already-`approved` Job (a
sibling estimate, or a revision after a prior acceptance). So cleanup must still gate on the atom's
actual state, not merely "estimate is draft."

### Open questions [OPEN]

1. **Provenance mechanism** — a flag/field on the atom, or on the source row, marking "created by an
   Add-line pick" (vs. pulled-in pre-existing work).
2. **Invoice-side parity** — the invoice `LineItemModal` also has an inventory pick; decide whether
   it, too, mints an immediate `Material`, or whether invoices only ever pull *already-worked* atoms
   (invoices bill actuals — a fresh zero-actual Material may be meaningless, mirroring why "Add from
   Service" is estimate-only).
3. **Migration/regeneration** — no dev-DB migration (regenerate); the converter/seed generator must
   emit picked materials as immediate atoms consistently.

---

## Part 2 — Rebuild the single/unified "Add line" picker

**[SETTLED intent]** Rebuild the **one** Add-line picker the design called for — a single affordance
that searches the job's catalogs and turns a pick into the right atom: **Service** (`ServiceItem`) →
`Task`, **Material** (`InventoryItem`, or freeform) → `Material`, **free-text / (future) `FeeItem`** →
a hand-line → `Fee`. It was **over-aggressively removed** when the Plan side was torn out; the search
backends survived (`/api/service-items/?search=`, the inventory catalog filter), only the unified UI
was lost.

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
  Material-vs-Fee choice in the picker (not accounting-category inference) gives a freeform material
  its atom type. Fold that concern in here.
- Part 1 (immediate crystallization) should land first or together — the picker's Material/Service
  branches assume the immediate model.

### Open questions [OPEN]

1. **Scope of surfaces** — one picker shared by job overview + estimate + invoice, or per-surface
   variants (invoice may differ — see Part 1 Q2).
2. **Freeform material path** — how the picker mints a freeform (non-catalog) `Material` and its
   transient lot (ties to the freeform-material-procurement follow-on plan).
3. **Relationship to the wizard** ("Show Tasks & Materials") — the picker creates *new* atoms; the
   wizard pulls *existing* job atoms. Keep both, or does the picker subsume the pull?

---

## Non-goals / relationship to other plans

- **Overview restructure / Client-View removal (Drift C)** — accepted as final; docs updated, no work.
- **Change-orders-drive-atoms** — separate follow-on (`2026-07-02-change-orders-drive-atoms.md`);
  its "CO line authoring gets inventory + service picks" reuses whatever this plan settles.
- **Freeform-material procurement** (`2026-06-30-…`) — the freeform `Material` + transient-lot minting
  the picker's freeform branch will lean on.
- **Schedule pre-approval pass** (`2026-06-29-…`) — unrelated; separate.

## Rollout / testing (when built)

No dev-DB migration (regenerate). TDD. Part 1: picking inventory on an estimate creates a Material
immediately (atom-backed line), acceptance no longer mints a Material from it, orphan cleanup on
line-delete respects bleps/actuals/claims. Part 2: the unified picker routes Service→Task,
Material→Material, freeform→Fee, across the intended surfaces.
