# Neal's data converter — what it does and how to update it

`convert_neals_data.py` turns Neal's CNC shop data into a Django `loaddata`
fixture (`nealsdata/datasets/converted.json`) for use as realistic dev/test
data. This document is for the next person — possibly you, a few months out —
who needs to update the script because something in Minibini or in Neal's
exports changed.

The script is **read-only on the source data and write-only to the JSON
fixture**: it never touches a database. It is a pure transformation.

## 1. Inputs

Two files, both placed in `nealsdata/datasets/` (the script auto-discovers
them and errors out if there is more than one of either):

| File | Source | Role |
|---|---|---|
| `*.xlsx` | FreeAgent "Company Export" | Contacts, Projects, Invoices, Estimates, Bills, Price List Items |
| `*.csv`  | Kanban board export (tab- or comma-delimited; `KanbanCsvLoader` sniffs) | The **spine** — defines which Jobs we build |

**FreeAgent has no column configuration**, so the Excel export shape is what
it is. The converter consumes only these sheets and ignores the rest:
`Contacts`, `Projects`, `Estimates`, `Invoices`, `Bills`, `Price List Items`.
(The old `Tasks` and `Timeslips` sheets are deliberately ignored — Tasks now
come from the Kanban Checklist column or from estimate line items.)

### The Kanban CSV columns we consume

The Kanban export **is** configurable. When re-exporting from the board, make
sure these 14 columns are included (exact header names, in any order):

```
Swimlane            Stage               Name                Description
Due date            External ID         Notes               est *cut* time
est ASS time        est $               Created at          Archived at
Checklist           Block reason
```

Notes on individual columns:

- **External ID** is the FreeAgent estimate number — a digit run like
  `07754`, optionally with a letter revision suffix (`03024b` = v2 of
  `03024`) or a tag (`03077-SOLID`). It is the join key against the Excel
  `Estimates` sheet's `Reference` column. `parsing.base_reference` strips
  to the leading digit run for grouping; the version chain is
  reconstructed by Date order within the group. **It is also used
  verbatim as the Job's `job_number`** — no synthesised `J{year}-counter`
  numbering anymore.
- **Name** is `Business` or `Business (Contact)` — parsed in
  `parse_kanban_name`. It is the join key against the FreeAgent Contacts
  sheet's `Organization`.
- **Description** is used as the Job's `name` (truncated to 50 chars) and,
  with `Notes` appended, as the Job's `description`. FreeAgent has no notion
  of a "job name".
- **Stage** drives the Job's status (see the table below). `Swimlane`
  refines the `Estimate` stage only: `Neal's do` → draft, anything else
  → submitted.
- **est *cut* time**, **est ASS time**, and **est $** are **no longer
  consumed** — worker times are now invented per-task (see §4). The columns may
  still be present in the export; they are simply ignored.
- **Created at** / **Archived at** drive Job dates.
- **Checklist** is multi-line text where each line is `[ ] some task` or
  `[x] some completed task`. Each line becomes a `jobs.task` (with two
  important exceptions — see §4). A leading space/tab makes a line a
  subtask of the preceding top-level item.
- **Block reason** is currently not consumed.

### Stage → Job status

| Kanban Stage | Minibini status | Note |
|---|---|---|
| `Estimate` + Swimlane `Neal's do` | `draft` | estimate not yet sent |
| `Estimate` + other swimlane | `submitted` | estimate sent to customer |
| `In Progress` | `in_progress` | |
| `Invoice` | `work_complete` | work done, invoicing in flight |
| `Done or Rejected` | `completed` | terminal; can be downgraded to `rejected` in reconcile (§5) |
| anything else / blank | `draft` | safety default |

If Neal renames a stage on the board, update `_STAGE_TO_JOB_STATUS` in
`build.py`.

## 2. Running it

```bash
python nealsdata/convert_neals_data.py [--limit N] [--all-vendors] [--verbose]
```

The default `--limit 100` caps how many Jobs are built from the most recent
matched Kanban cards — except that **non-archived cards in an active stage
(In Progress / Invoice) are always included**, whatever their age (live
board work must never silently age out; the 2026-07-13 Barbara Freeman
regression). Actives consume limit slots; the total exceeds the limit only
when the actives alone do. The output is `nealsdata/datasets/converted.json`
(the file is git-ignored — regenerate it whenever inputs change).

`--all-vendors` also imports the newest `--limit` vendor orgs from the Bills
sheet (§7a). Without it, a vendor Business appears in the output only because
one of its Bills synthesized a PO (§4a) — so no vendor is left with neither a
job nor a PO.

Loading the result into Minibini is the user's job — the script never writes
to a database, and it always emits **one** self-contained dataset file.
Tests load it into the auto-created test DB via
`call_command('loaddata', ...)`. (Hand-curated extras — config, catalog
service items, manual shifts — live in separate RM-managed fixture files
loaded after the dataset; they are not the converter's concern.)

**The output is not byte-stable across days.** The archive rule (§4,
"Archived jobs") compares each job's `completed_date` to a cutoff of six
calendar months before the run's clock (`NealsDataConverter(..., now=None)`
defaults to the current UTC time, stored as `c.now`), so the same inputs
produce different `archived` sets as time passes. Tests therefore assert
the rule, not fixed counts, and inject `now` where they need a known
boundary. With the real clock and the default `--limit 100` the regenerated
dataset currently holds very few archived jobs:
the spine is the newest 100 cards, and old cards compete for those same
slots by design. Raise `--limit` to get more archives.

## 3. Pipeline at a glance

`orchestrator.NealsDataConverter.convert()` runs these phases in order:

1. **Load**: Excel sheets into memory; Kanban CSV into a list of dicts.
2. **Select spine**: pair each recent Kanban card with the Estimates-sheet
   rows whose `Reference` base matches the card's `External ID`. All
   non-archived active-stage matches plus the newest other matches (up to
   `--limit` total) become the Jobs we'll build (§2).
3. **`build_seed`**: copies users, accounting categories and rate schemes
   verbatim from `fixtures/large_datasets/nealseed.json`. (Fixed charges need
   no "Flat Fee" scheme — there is no Fee model; they stay plain estimate
   document lines, see `derive_atoms`.) **Assigns
   explicit pks to the (otherwise pk-less) seed users** and builds
   `c.user_by_username`, the blep-rotation pool `c.rotation_user_pks` (every
   active seed user except `system`), and `c.scheme_fields_by_pk` (each
   seeded RateScheme's full fields dict, for stamping the money block onto
   every Task — §4). Records a seed worker's fields as the clone template
   for minting extra users (§4).
4. **`build_configuration`**: emits the `core.configuration` entries the
   app needs at runtime (numbering patterns + counters, `units_list`,
   retention windows, `default_material_markup_percent` = `20`).
5. **`build_inventory_items`**: copies the FreeAgent Price List Items
   sheet. Every inventory item is just an item — there is no catalog/lot
   distinction; retirement is manual via `is_active`. Materials that match no
   existing item later mint a **transient lot** (code `LOT-*`) in
   `derive_atoms` via `_mint_transient_lot`, so every Material ends up
   item-backed.
6. **`build_contacts_and_businesses`**: emits the **customers** referenced by
   spine cards, reconciled against the canonical FreeAgent Contacts sheet. Each
   card's customer org (priority Projects `Client Organisation` → Bills
   `Contact Organisation` → parsed card `Name`) is run through
   **`resolve_contact`**, which:
   - **canonicalizes** noisy kanban spellings onto one FreeAgent record —
     exact → normalized (case/punctuation/company-suffix/parenthetical, via
     `parsing.normalize_name`) → fuzzy (`difflib` ≥ `_ORG_FUZZY_THRESHOLD`,
     0.82). `_FORCE_DISTINCT` blocks the one confirmed false positive
     (`BWC Architects` ≠ `HMC Architects`). So `Boxbot`/`BoxBot` and
     `Apple`/`Apple Inc.` fold to one Business (a "Class B" merge).
   - splits **individuals from businesses**: a Contacts-sheet row with a blank
     `Organisation` (e.g. James Sandersfeld) is a person → emitted as a
     **Contact with `business=None`**, no Business manufactured. Absent names
     use `parsing.looks_like_person` (2–3 alphabetic tokens, no business
     tokens) to guess individual vs business.
   - collects **multiple contacts per Business**: FreeAgent has one contact per
     org, but kanban `Business (Person)` cards name different people across
     jobs; every distinct person attaches to the one Business (Minibini allows
     many), `default_contact` = the FreeAgent representative (else the first
     person, else synthesized).

   Emission goes through `_emit_business` / `_emit_individual` / `_emit_contact`
   (emails + phones anonymized, §6). Sets `c.entity_map` (canonical key →
   resolved entity) and `c.entry_contact` (base_ref → (key, person_norm)) so
   `build_jobs` links each Job to the exact Contact. Only entities referenced by
   a spine job (or, later, a Bill) are created — the Contacts sheet at large is
   never imported wholesale.
7. **`build_jobs`**: one Job per spine entry, named from the card
   Description, status from Stage + Swimlane. The Job's **contact** comes from
   `c.entry_contact[base_ref]` (set in step 6): a business Job links to the
   Contact matching its card's named person, falling back to the Business
   `default_contact`; an individual Job links to its standalone Contact. (This
   single shared resolution removes the old "discard wrinkle" where customers
   and jobs resolved the org differently.) Job number is the FreeAgent
   estimate base reference (the digit run, e.g. `03024`) — the same
   identifier used to join Kanban cards to Estimates rows. **`created_date` is
   the earliest container estimate's `Date` minus one day** (the job object
   exists a day before its first estimate); `start_date` is filled later by
   reconcile from the *latest* estimate's date, so `created_date < start_date`.
   Accent color is round-robined through `JOB_ACCENT_COLOR_PALETTE` (mirrored
   from `apps.jobs.models`) so loaddata-emitted jobs render with the colored
   bars the SPA board expects.
7a. **`build_vendors`** (only with `--all-vendors`; otherwise skipped, and
    vendors enter the output solely through PO synthesis in §4a): emits
    Businesses/Contacts for **vendors**, drawn
    *wholly* from the FreeAgent `Bills` sheet (the Kanban source has no
    concept of bills or vendors). Groups bill container rows by
    `Contact Organisation` (rows with a blank organisation — line items and
    name-only one-offs — are skipped; the skipped name-only count lands on
    `c.vendor_skipped_name_only`), ranks orgs by their most recent bill
    `Date` newest-first, and imports the first `--limit` distinct orgs
    (recorded on `c.vendor_selected_orgs`). Each selected org goes through the
    same **`resolve_contact`** as customers, so vendors canonicalize the same
    way. Runs **after `build_jobs`** so a vendor org can never be mistaken for a
    job's client; a vendor that resolves to an entity already in `c.entity_map`
    (an existing customer) is **reused**, and for an existing Business the
    bill's `Contact Name` is attached as another Contact if new. (No `Bill`/`PO`
    records are emitted — vendors only.)
8. **`build_estimates`**: emits the Estimate + its line items for every
   revision in the chain. Estimate number is `{job_number}-{version}` — the
   canon form `EstimateService.create_estimate` would have produced. Each
   estimate also gets a fresh `public_token` via `secrets.token_urlsafe(32)`
   so the customer-portal URL (`/portal/?token=…`) works for seeded data.
   Estimate line items are **kept**; downstream atoms (Task, Material,
   Deliverable) are *copies*, not moves.
9. **`derive_atoms`**: for each Job, builds Tasks, Materials, and
   Deliverables from the Kanban Checklist and/or the estimate line items.
   Atoms live **directly on the Job at every status** (draft included) —
   there is no plan layer (the app's job-owns-atoms model; EstWorksheet /
   PlanTask / PlanMaterial no longer exist). A task-classified estimate
   line that bills as a fixed charge emits no atom at all: it stays a plain
   document line (price included, already emitted by `build_estimates`).
   Materials get a `unit_cost` and an
   `inventory_item` link via fuzzy matching (§4). This is where most of
   the interesting logic lives — see §4.
9a. **`assign_worker_times`**: gives every Task an invented per-task
    `est_worker_time` — random in `[0.5, 4.0]` hours, 2 sig figs,
    minute granularity (§4).
9b. **`assign_est_quantities`**: fills `est_qty` on every Task by its own
    `qty_source` (hourly = worker hours; entered_qty = piece count tied to
    worker time) — §4.
10. **`build_invoices`**: emits Invoices + line items. An Invoice joins a
    Job through the **Estimates sheet's `Invoice Reference` column**: each
    spine job's estimate rows contribute their `Invoice Reference` values,
    and an Invoices-sheet row whose `Reference` matches one of them belongs
    to that job. Invoices no spine estimate points at are skipped. (The
    FreeAgent `Project` column is not used here — it only feeds vendor
    discovery in `build_contacts_and_businesses`.) Stashes each emitted line's classification (`task`,
    `material`, `lineitem`, `skip`) on `c.invoice_line_kinds` for the
    next phase. Sets `sent_date` on `open`/`paid` invoices (= the FreeAgent
    invoice Date) and `qbo_amount_paid` on `paid` invoices (= that invoice's
    own line-item total; `draft` invoices stay null-dated — §8).
11. **`reconcile`**: cross-model fixups in a fixed order — see §5.
11a. **`archive_old_jobs`**: runs right after reconcile, before anything
    else that reads final job state. Reshapes completed / rejected /
    cancelled Jobs whose reconciled `completed_date` is on or before
    `archive_cutoff(c.now)` (now minus `_ARCHIVE_AFTER_MONTHS = 6` calendar
    months) into `archived` Jobs carrying only translated data — see "Archived
    jobs" in §4. Every later builder skips them.
12. **`build_shipments`**: runs *after* reconcile so it can see final Job
    status / dates. Builds a Shipment + ShipmentItems for any card whose
    checklist has a checked `Picked up/Delivered` line OR for any Job that
    landed in `completed` status without a marker (synthesised — see §4).
12a. **`assign_project_managers`**: runs *after* reconcile (needs final job
    status). Assigns a random `project_manager` from the seed rotation pool to
    every Job beyond `draft`; draft jobs keep a null PM.
13. **`build_bleps_and_shifts`**: runs *after* reconcile (needs final task
    statuses + job dates). Emits one Blep per complete Task **within a three-week
    horizon**, the Shifts that enclose them, and `actual_qty` for complete
    `entered_qty` tasks (§4).
13a. **`assign_current_work`**: runs *after* `build_bleps_and_shifts`. Gives each
    rotation worker up to three random **pending** Tasks drawn from
    **in_progress** Jobs (assignee + `worker_queue`), so the board and schedule
    show current work (§4).
13b. **`build_purchasing`**: runs *after* reconcile (needs final job/task status)
    and *before* `build_history`. Reconciles the **inventory side of Materials**
    and synthesizes **POs/Bills** — see §4a.
13c. **`build_invoice_line_item_sources`**: heuristic source-link wiring
    — for each Invoice, claim Tasks/Materials on the Job in deterministic
    order against the invoice's line items so the SPA shows them as
    "billed" rather than orphaned. Runs *after* reconcile AND
    `build_purchasing`: **only settled work links to an invoice** — the
    task pool is `complete` tasks only, the material pool `consumed`
    materials only (the app's terminal-billability line; converter
    cancelled tasks carry no actuals, so they never claim). Honours the
    model's global `unique_together(source_type, source_pk)`. Leftover
    lines stay freeform.
14. **`build_history`**: last — emits a created/transition entry per tracked
    object. (Reads each Material's `consumption_state`, set in 13b, to narrate
    the consume event.)

The RNG is seeded with a fixed constant at the top of `convert()` so the
invented worker times and blep placement are stable across regenerations
unless the inputs change, for a given run clock (the output as a whole is not
byte-stable across days; see the §2 note on the archive cutoff).

## 4. Building Tasks, Materials, and Deliverables

This is the most-rewritten part of the script and the part most likely to
need tweaking again.

### Atoms live on the Job (no plan layer)

`derive_atoms` emits every atom **directly on the Job**, whatever its
status — the app's job-owns-atoms model (the old EstWorksheet / PlanTask /
PlanMaterial plan layer is gone from Minibini and from the converter).
Checklist subtask hierarchy and `[X]`/`[ ]` status are preserved; each
LI-derived atom gets an `estimates.estimatelineitemsource` row linking back
to its source line so the estimate lens projects it.

A Job that later expires and is rejected by the reconcile pass simply keeps
its atoms (its tasks get cancelled by reconcile pass 7) — the historical
record of "we estimated this; the customer never accepted."

### Tasks

Tasks come from two sources:

1. **Kanban Checklist (preferred).** Each `[ ]`/`[x]` line becomes one
   `jobs.task`. Indented lines become subtasks. Two exceptions:
   - `Picked up/Delivered` markers are consumed by the Shipments builder
     instead (`_is_pickup_marker`).
   - Board status-markers are dropped entirely (`_is_dropped_checklist_line`,
     prefix match, case-insensitive). The current drop-list:
     - `invoice sent`     — FreeAgent invoice data is more accurate
     - `payment received` — same; FreeAgent has the real payment data
     - `jan take photos`  — recurring reminder, not work
     - `packing slip`     — not real work
   - **`(track time)` marker overrides the drop-list.** A checklist line
     containing `(track time)` always becomes a Task. That marker, on Neal's
     board, explicitly flags a real time-tracked task.

2. **Estimate line items (fallback).** When the card has no Checklist, the
   estimate's labour-classified line items become Tasks. Material-keyword
   lines that look like labour (`prepare …`, `apply …`, `glue …`,
   `engrave …` — see `_LABOR_VERB_PREFIXES`) also become Tasks, even when a
   Checklist is present.

Every task resolves a RateScheme and **stamps its money block from it**
(`_stamp_money_block`, mirroring `Task.stamp_from_scheme`): the scheme's `pk`
lands on `source_scheme` (provenance only — never read for money math), and
`qty_source` (= the scheme's `algorithm`), `rate`, `unit_label` and
`accounting_category` are copied onto the task as its own permanent values.
`active_modifiers` resolves any modifier keys against the scheme's
`modifiers` into full `{key, label, percent}` snapshot dicts — the
converter never activates any, so it's always `[]` in practice, but the
resolution path is real (matches `_line_billing`'s `active_modifiers`
return, currently always an empty key list).

- Checklist tasks: keyword-matched (`checklist_scheme_name`):
  - `cut`        → `CNC Routing`
  - `laser`      → `Laser`
  - `draw` / `cad` / `model` → `CAD`
  - everything else → `Shop labor`
- Line-item tasks: same keyword rule first (a `cut`/`laser`/`cad` line is
  always work); otherwise `_line_billing` infers the billing shape — a
  line with a time/quantity signal matches a seeded scheme by
  `(algorithm, rate)` (`_match_seed_scheme`), and a line with **no**
  time/quantity signal is a **fixed charge → it stays a plain document
  line, no atom and no source row** (`_build_line_item_tasks`; there is no
  Fee model and the retired flat-fee RateScheme is gone).

If the named scheme isn't in nealseed, the closest match is used (see
`_match_seed_scheme`). When you add new schemes to nealseed, this will pick
them up automatically.

### Estimated worker time

Every Task gets an invented per-task `est_worker_time` in a single pass
(`assign_worker_times`, run after `derive_atoms`): a random value uniform
in `[0.5, 4.0]` hours, rounded to 2 significant figures and stored at
minute granularity. The pass iterates in pk order with the seeded RNG, so
output is deterministic.

The old `est *cut*`/`est ASS` Kanban columns are **no longer consumed** — they
were rare *whole-job* estimates wrongly stamped onto a single task, which made
no sense once every task carries its own per-task estimate. The checklist holds
no per-task time data, so a real estimate isn't derivable from it anyway.

### Estimated quantity (real Tasks)

`assign_est_quantities` (after `assign_worker_times`) fills `est_qty` on every
Task by its rate-scheme algorithm. `est_qty` is optional on `Task` (nullable
at the DB level and unenforced), but the dataset wants it populated:

- **elapsed_time** (hourly, the most common): `est_qty` = the worker-time
  estimate in hours (`02:30:00` → `2.50`), set always — so estimated billable
  hours equal the estimated worker time.
- **entered_qty** (piece counts): tied to the worker time — `round(worker_hours
  × pieces_per_hour)`, `pieces_per_hour` random 2–6 (min 1) — unless a source
  line set a qty. This also feeds the `entered_qty` actuals.

(Fixed charges are plain document lines, not Tasks, so there is no flat-fee
case.)

### Bleps, Shifts, and entered_qty actuals

`build_bleps_and_shifts` (after reconcile) gives the dataset time-tracking data:

- **One Blep per complete Task** (real-side only), **within a three-week
  horizon** — `horizon = _dataset_now − 3 weeks`. Length =
  `est_worker_time × {1.0, 1.10, 0.95}` on a deterministic ⅓-rotation index
  (`P.thirds_factor`), floored to whole minutes. The task's **`assignee`** is set
  to the blep's user (the worker who logged the time).
- **Scope invariant**: every complete Task on a **current** job — *unfinished*
  (no `completed_date`: in_progress / work_complete / on_hold) **or** *finished
  within the horizon* (`completed_date ≥ horizon`) — always gets a blep. Only a
  **finished** job whose `completed_date` is older than the horizon is dropped (it
  is out of scope; its complete Tasks may be blep-less). This is enforced by the
  window's upper bound (next bullet): an unfinished job's window runs to
  `_dataset_now`, so it can never fall before the horizon.
- **Placement** satisfies two invariants at once: each blep falls inside its
  **job's active window** `[start_date or created_date → completed_date (finished)
  or _dataset_now (unfinished)]`, clamped to ≤ `_dataset_now` (no future bleps)
  and to ≥ the horizon (when that clamp would collapse the window — a job
  completed right at the boundary — it backs off to the job's final local
  workday instead); and **no user's bleps overlap**. The synthetic workday is
  defined in the shop's **local timezone** (`_WORKDAY_TZ`, mirrors
  `settings.TIME_ZONE`) and converted to UTC per calendar day: shifts open at
  **09:00 local**, bleps pack from **09:15** (a clock-in lead-in), close at
  **17:00** (weekends allowed). **One worker per job**: a job's tasks go to the
  same user (rotation advances per job, not per blep), packed back-to-back
  with a deterministic 5–30-minute gap between bleps — which is what makes
  worker-days carry several bleps. If that worker (then everyone) is booked
  across a job's window, a new worker is **minted** (`_mint_user`) as the
  pressure valve.
- **Shifts**: one `core.shift` per (user, local calendar day) with bleps — a
  realistic workday span, not a band coterminal with the bleps: `start` =
  09:00 local, `end` = 17:00 local clamped to `_dataset_now` and never before
  the last blep end, so the shift↔blep enclosure invariant holds with slack.
  `loaddata` bypasses `Blep.save()`/`Shift.save()`, so all timestamps are
  emitted pre-floored to the minute.
- **entered_qty actuals**: a complete task on an `entered_qty` scheme gets an
  `actual_qty = est_qty × {thirds}` (fallback base `1` when `est_qty` is null)
  so it doesn't invoice at zero. This is set for **every** complete task — even
  ones too old for a blep under the horizon — so historical work never invoices
  at zero. `elapsed_time` tasks derive qty from their bleps and need no
  explicit actual (fixed charges are plain document lines with no actuals at all).

`assign_current_work` (after `build_bleps_and_shifts`) then populates **current**
work: each rotation worker (excludes `system` + minted users) gets up to three
random **pending** Tasks drawn from **in_progress** Jobs, with `assignee` and a
per-worker `worker_queue` (0,1,2). The Tasks stay `pending` — assigned, not yet
started — so they appear as forecast bars on the schedule (ScheduleService
includes pending assigned tasks) and as queued cards on the job board. Only Tasks
with an `est_worker_time` are eligible (`Task.clean()` requires it on an assigned
Task). Deterministic given the seeded RNG.

### Purchasing & inventory state (`build_purchasing`)

Runs after reconcile (final job/task status) and before `build_history`. It makes
the Materials consistent with the inventory
model and synthesizes Purchase Orders + Bills. See
`docs/designs/materials-inventory-and-purchasing.md` for the model it mirrors.

- **Consumption is task-driven and universal.** A Material is `consumed` iff its
  work happened — a task-attached Material when its Task is `complete`, a
  task-less Material when its Job reached `in_progress`/`work_complete`/
  `completed`. There are no completed tasks with unconsumed materials.
- **Consumed ⇒ assumed acquired.** Since the source data is incomplete (many real
  purchases have no surviving Bill), a consumed Material is modelled as having
  come in and gone out: **net-zero `qty_on_hand`, `qty_sold += quantity`** —
  whether or not a Bill is found. A Bill, when found, only adds the paper trail;
  it never changes the inventory end-state.
- **Earmarks + QOH for pending Materials.** A pending Material holds an
  `Earmark` (one row per `(inventory_item, job)`, summed) while its Job is
  **active** (none on terminal jobs `work_complete`/`completed`/`cancelled`/
  `rejected`, none for consumed Materials — matching the app's
  `release_earmarks_for_job` + consume behavior). A pending Material on a
  bill-matched Job is treated as **received** (`qty_on_hand += quantity`).
- **PO/Bill synthesis (best-effort).** A Job is matched to a Bill when an
  estimate base appears in the Bill's **Comments** (Comments only — the `Project`
  column is too sparse; precision-biased: the Job must exist and have Materials).
  First matched bill/vendor wins per Job. The match emits a `received_in_full`
  `PurchaseOrder` to that Bill's vendor carrying **all** the Job's Materials
  (`PurchaseOrderLineItem` per Material, `qty_received = quantity`,
  `Material.po_line_item` set). (No konbini `Bill` rows — bills live in QBO.)
  The vendor business is created on the spot if it wasn't among the imported
  top-N vendors (and without `--all-vendors` this is the *only* way a vendor is
  emitted). The PO's `contact` is the Bill's **`Contact Name`**, resolved
  against the vendor's existing Contacts by normalized name and attached as a
  further Contact when missing — the business default is used only when the
  Bill names nobody. PO numbers are `PO{n:04d}` and the
  `po_counter` AppState is advanced past them. Coverage is partial by design —
  most Materials have no surviving purchase record, which is expected.

Unmatched Materials (no existing PLI) get a **transient lot** InventoryItem
(code `LOT-*`) at creation (`_mint_transient_lot`), priced from cost via
`default_material_markup_percent`, so the earmark/QOH/consumption rules above
apply uniformly to every Material. There is no catalog/lot flag — every item is
one kind; retirement is manual via `is_active`.

### Materials

`_material_line_kind` splits material-classified estimate line items three
ways. Each line becomes exactly one fixture:

| Description shape | Becomes |
|---|---|
| `… sheet`, `… board feet`, `BF of …`, `Materials: …`, `Estimated materials …` | `inventory.material` (raw stock) |
| starts with one of `prepare`, `apply`, `glue`, `engrave` | `jobs.task` (labour disguised as a material line) |
| anything else | `deliverables.deliverable` |

Materials link to the job's first cut-named task via `c.cut_task` (so the
Material's `task` FK lands on the right Task — there is always at most one
per job).

**Unit cost + PriceListItem link** (`_material_cost_and_pli`): each raw-stock
Material/PlanMaterial is fuzzy-matched to a PriceListItem by material keyword +
thickness (`P.match_pli`). On a match the `inventory_item` FK is set and
`unit_cost` is the PLI's `purchase_price`; on a miss the FK stays null and
`unit_cost = sell_price × _COST_RATIO` (0.8333, the same factor PLIs use). The
match is precision-first — prose with no thickness, or a material family absent
from the price list, is an acceptable miss. Date tokens (`*price as of
7/31/25*`, `10/13/2023`) are stripped before the fraction scan
(`_DATE_RE`): left in, 7/31 read as a 0.226" thickness shared by every
same-family item carrying the same suffix, and the shortest-code tie-break
linked 3/4" MDF to `MDF.5` (33 of 56 dev materials mislinked, found
2026-10-14). As noted above, a miss then mints a
transient lot in `derive_atoms`, so by the time the `inventory.material`
fixture is emitted the FK is never actually null — every Material is
item-backed.

**`cost_source`**: every emitted Material carries `cost_source='entered'` —
never null, since a Material with an `inventory_item` must have a non-null
`cost_source` and (per the point above) every converter Material has one. The
historical PLI/lot pricing is treated as a human-vouched-for figure at import
time, the same status as a user entering a price today. `build_purchasing`
later attaches some Materials to a synthesized PO/Bill (`po_line_item`) as a
retroactive provenance trail over that *same* already-set `unit_cost` — it
doesn't represent the PO introducing a new cost, so it does not upgrade
`cost_source` to `'po'`. The converter models no expense-linked or
customer-supplied flow, so `'expense'`/`'customer_supplied'` never appear, and
no provisional (no-cost, no-lot) Materials are ever emitted, so `'estimated'`
and a null `cost_source` never appear either.

### Deliverables

Every job needs at least one Deliverable. Material-classified lines that
fell through to `deliverable` become Deliverables. A job with none gets a
single synthetic `Fake Deliverable` (`c.fake_deliverable_count` counts
these — the `--verbose` summary reports the number for human review).

### Shipments

`build_shipments` emits exactly one Shipment + ShipmentItems per Job under
two trigger paths:

1. **Pickup-marker present.** The Kanban checklist has a checked
   `Picked up/Delivered` line. Notes left blank.
2. **`completed` Job, no pickup marker.** §2.5 requires a `completed` Job
   to have every Deliverable fully shipped, so the converter synthesises a
   Shipment covering all of them. The Shipment's `notes` carry the string
   `"(Fake shipment)"` if it references at least one real (non-Fake)
   Deliverable; if every covered Deliverable is itself a synthetic
   `Fake Deliverable`, the Deliverable already telegraphs the fakeness so
   notes stay blank.

The shipment's `picked_up_date` comes from the Job's `completed_date`,
falling back to the latest invoice date, then the Job's `created_date`.
Pickup-marker checklist lines never become Tasks. The marker test itself
(`parsing.is_pickup_marker` / `parsing.has_pickup_done`) is shared with
reconcile pass 6.5, which uses it as the "all deliverables shipped" half
of the completion gate.

### Units mapping

`build_configuration` writes `units_list` mirroring
`apps.core.units.DEFAULT_UNITS` so every emitted line-item, Material and
Deliverable row validates against the running app's canonical list.
`parsing.resolve_li_units_and_qty` converts FreeAgent `Item Type` values:

- `Hours` → `units='hour'`, qty unchanged
- `Days`  → `units='hour'`, qty multiplied by 8 (one workday)
- anything else → `units='none'`, qty unchanged

Deliverables default to `units='ea'` (canon form of `each`).

### Archived jobs

`build.archive_old_jobs(c, cutoff)` runs after `reconcile.reconcile(c)`
(`orchestrator.convert()` passes `build.archive_cutoff(self.now)`). It has to
run after reconcile because reconcile is what settles a job's final status
and `completed_date` (pass 3 rejects on expiry, pass 6 downgrades, pass 5
sets the date); classifying earlier would be a guess. A job qualifies when
its status is in `_ARCHIVABLE_JOB_STATUSES` (completed, rejected, cancelled)
and its `completed_date` is at or before the cutoff. A job that pass 6
downgraded to `work_complete` for an unpaid invoice never qualifies. The
pass records `c.archived_job_pks` and `c.archived_outcome` (job pk to its
pre-archive status), and `--verbose` prints an `N jobs archived` summary
line.

The goal is that each archived job looks exactly like one
`ArchiveImportService.create_archived_job` (`apps/jobs/archive.py`, see
`docs/designs/jobs-and-tasks.md` §3.8) would have created, so RM can test
archives on converted data. What that means per record:

- **Job**: `status='archived'`, `project_manager` null. Number, contact,
  name, description, dates as reconciled; `accent_color` is left as the
  converter's round-robin value.
- **Tasks**: kept with their reconciled `complete` / `cancelled` status. The
  money block is plain values (`qty_source='entered_qty'`, rate, unit label,
  accounting category); `source_scheme`, `service_item` and
  `active_modifiers` are cleared. `est_qty` is kept only when it came from an
  estimate line's own quantity; if `assign_est_quantities` invented it (the
  pks are in `c.invented_est_qty`) it is nulled. `est_worker_time`,
  `actual_qty`, `assignee` and `worker_queue` are always null.
- **Materials**: kept, marked `consumed` / `imported`, nothing released, no PO
  line. A link to a converter-minted `LOT-*` transient lot is cleared and the
  lot row removed if nothing else uses it; links to real price-list items stay.
- **Estimates, estimate lines, invoices, invoice lines**: kept as reconciled,
  version chains included. Invoice QBO fields are blanked (`qbo_amount_paid`,
  `qbo_id`, `qbo_payment_status`) because the importer never sets them.
- **Source rows** (`estimatelineitemsource`, `invoicelineitemsource`,
  agreement-line refs): none; the importer cannot express them.
- **Deliverables, shipments, bleps, shifts, earmarks, POs and PO lines**:
  none. Deliverable-shaped estimate lines stay as estimate lines, and a
  `Fake Deliverable` is removed (the verbose count is decremented).

The nine downstream builders that would otherwise add live-job data each
carry an `# archived jobs carry only translated data (spec §6)` guard (the comment
refers to the rule above: archived jobs keep only what the importer would write)
(project managers, shipments, bleps and shifts, current work, purchasing,
invoice line sources, agreement refs, synthetic estimate sources, checklist
declines).

`build_history` emits importer-shaped rows for archived jobs
(`_archived_job_history`): a `_created` audit row per job, task, material,
estimate and invoice at the run's `now`, then action rows on the job
(`Created`, `Started` when there is a start date, the outcome, `Imported from
Kanban`), plus a note row `Picked up/Delivered (Kanban checklist)` when the
card had that marker checked. No transition rows for child records. All
rows have `user=None`.

Design call (RM): where the importer cannot express something, the
converter **drops** it rather than the importer being extended to match. The
one importer change this work needed was estimate version chains (`parent`,
superseded versions).

## 5. Reconciliation passes

`reconcile.reconcile()` runs after all builders, in this order. Its
"today" is the run clock (`c.now.date()`), not `date.today()`, so one run has
one clock (§2).

1. **Estimate version chains** — for any base reference with multiple
   versions, every version below the highest is marked `superseded` and
   linked to the previous via `parent`. The highest keeps the builder's
   status.
1.4. **Invoiced jobs are started** — a draft/submitted Job carrying ANY
   invoice bumps to `approved` (the minimal billable status): the app's
   `BILLABLE_JOB_STATUSES` guard means even a draft invoice can't exist
   pre-approval, so the FreeAgent invoice outranks a stale Kanban Stage.
   Runs before the accept-estimate and expiry passes.
2. **Started jobs accept their estimate** — a Job in `approved`,
   `in_progress`, `work_complete`, or `completed` couldn't have got there
   without an accepted estimate, so its latest estimate is forced to
   `accepted`. (Runs before expiry so a now-accepted estimate isn't
   re-expired.)
3. **Expiry** — `open` estimates older than 30 days become `expired`. If
   the expiring one is the Job's latest estimate **and** the Job is still
   in `draft`/`submitted`, the Job is rejected.
4. **Estimate dates** — sent/expiration/closed dates filled in to match
   each estimate's status.
5. **Job status & dates** — `start_date` for started jobs = the **latest**
   estimate version's date (the job started when its newest estimate was drawn
   up; this is ≥ `created_date`, which `build_jobs` set to the earliest estimate
   − 1 day). `completed_date` for terminal jobs (preferring `Archived at`,
   falling back to the estimate's `closed_date`, finally the job's
   `created_date`).
6. **Downgrade `completed` Jobs with unpaid invoices** — §2.5 says every
   Invoice on a `completed` Job must be `paid`/`cancelled`. FreeAgent
   invoice data is authoritative on payment status; any `completed` Job
   carrying a still-`open`/`draft` Invoice was archived prematurely on
   the Kanban board, so the reconcile pass downgrades it to
   `work_complete` and clears `completed_date`. Must run before
   `build_shipments` so the synthesis branch doesn't fake-ship the
   downgraded job.
6.5. **Promote `work_complete` Jobs the app would have closed** — the
   mirror image of pass 6. Live, `JobService.maybe_complete_if_resolved`
   walks a `work_complete` Job to `completed` when every Invoice is
   resolved and every Deliverable is picked up; the converter writes those
   end states without replaying the cascade, which stranded paid-and-
   collected jobs in the board's Unpaid lane (job 07699, RM 2026-10-14).
   A `work_complete` Job that is not on hold, has **at least one `paid`**
   Invoice and no Invoice outside `{paid, cancelled}`, and whose card has
   a checked `Picked up/Delivered` marker (every Job has ≥1 Deliverable,
   and a `work_complete` Job's Shipment only comes from the marker, so
   marker ⇔ all shipped) is promoted to `completed`, with
   `completed_date` = the latest paid Invoice's `closed_date` (payment
   follows pickup in this data), falling back to the latest Invoice's
   `created_date`. Deliberate departure from the gate: no Invoices, or
   only cancelled ones, does **not** promote — the Kanban `Invoice` stage
   means billing is pending, so those stay visible as Needs Invoice.
   Paid but **no** marker stays `work_complete` too; the board files it
   under Needs Pickup. `build_history` keys "Job closed out" off the final
   status, so the transition entry follows; `build_shipments` ships the
   job via its marker path as before. Consequence: a promoted job is a
   *finished* job for the blep horizon (§4), so one completed more than
   three weeks ago loses its synthetic bleps like any other old completed
   job.
7. **Task status from job** — cancel ALL tasks on cancelled/rejected jobs;
   cancel still-PENDING tasks on work_complete/completed jobs (the app's
   work-complete gate forbids a non-terminal task on a closed job; checked
   items stay complete). Every cancelled task then detaches its materials
   to the job as loose rows (task=None), mirroring the app's cancel_task —
   `build_purchasing`'s job-status rule later consumes loose materials on
   worked jobs, keeping closed jobs free of pending materials.
   Otherwise the per-checklist `[X]`/`[ ]` state is preserved.
8. **Document counters** — the **AppState** counters for jobs/invoices/POs
   (machine state in AppState, not Configuration) are set to
   the number of emitted records so the next number generated by the
   running app doesn't collide. `po_counter` honestly counts zero here
   (build_purchasing runs later and advances it past the POs it
   synthesizes). `estimate_counter` is intentionally excluded — estimate
   numbers now derive from `{job_number}-{version}`, not from a counter.

When the source data disagrees (Kanban Stage vs. Estimate Status), the
"farther along the transition chain" wins — that's what passes 2 and 3
together enforce.

## 6. Anonymization

PII in the FreeAgent data is scrubbed at build time:

- **Emails**: domain replaced with `example.com`, local part kept
  (`_anonymize_email`).
- **Phones**: any three-digit prefix replaced with `555`, separators
  (space, `.`, `-`, `()`) preserved (`_anonymize_phone`).
- **Notes / Description**: regex-scrubbed for both via `_scrub_text`. The
  Checklist column is *not* scrubbed — Neal puts shop talk there, not PII.

If a new export drops PII into a column we don't currently scrub, add it
to the scrub call site or to `_scrub_text`.

## 7. Where things live

```
nealsdata/
  convert_neals_data.py   thin CLI; argparse → orchestrator
  convert.md              ← this document
  datasets/               *.xlsx, *.csv, and the generated converted.json
  converter/
    __init__.py           empty (per CLAUDE.md)
    loaders.py            ExcelDataLoader, KanbanCsvLoader, discover_datasets, load_seed_records
    parsing.py            pure helpers: dates, decimals, names, references,
                          checklist parser, classification of line items
    build.py              all builders; the bulk of the code
    reconcile.py          cross-model fixups (the 9 passes above)
    orchestrator.py       NealsDataConverter — phase wiring + state container
```

The state container (`NealsDataConverter` instance, conventionally `c`)
carries everything between phases: `c.fixture_data` (the output list),
`c.entity_map` (canonical key → resolved customer/vendor entity) and
`c.entry_contact` (base_ref → (entity key, person_norm)) from the contact
resolver, the FreeAgent Contacts indexes it builds (`c.fa_org_by_norm` /
`c.fa_org_display` / `c.fa_org_norms` / `c.fa_person_by_norm`),
`c.job_map`, `c.jobs`, `c.estimates`, `c.line_items`, `c.cut_task`
(the first-cut-task index for
material attach), `c.scheme_by_name`, `c.scheme_fields_by_pk` (full seeded
RateScheme fields, for stamping the task money block),
`c.user_by_username` / `c.rotation_user_pks` (blep
rotation), `c.pli_index` / `c.pli_purchase_by_code` (material→PLI matching),
`c.invoice_line_kinds` (per-line classifications used by
`build_invoice_line_item_sources`), the pk counters, and diagnostics
(`c.discarded_cards`, `c.fake_deliverable_count`, `c.vendor_selected_orgs`,
`c.vendor_skipped_name_only`).

## 8. Common updates you'll likely need

- **The Minibini schema changed.** Look at `docs/designs/data-constraints.md`
  first to see what the model now requires. Then update the relevant
  builder in `build.py`. The fixture-load test
  (`tests/test_neals_fixture.py`) catches FK / field / NOT-NULL drift
  immediately.
- **A Kanban column was added/renamed/removed.** Update `KanbanCsvLoader`
  isn't necessary — it uses `DictReader` and is column-name-driven — but
  any consumer (`build_jobs`, etc.) that names the column directly needs the
  change. Update §1's column table here too.
- **Stage names changed on the board.** `_STAGE_TO_JOB_STATUS` in
  `build.py`. Add the new Stage → Minibini-status mapping.
- **A new "noise" line keeps showing up on every card's checklist.**
  Add its lowercase prefix to `_DROPPED_CHECKLIST_PREFIXES` (in `build.py`,
  next to `_is_dropped_checklist_line`).
- **A new rate scheme appears in production.** Add it to nealseed; the
  matcher (`_match_seed_scheme`, plus the keyword rules in
  `parsing.checklist_scheme_name`) will pick it up automatically. If the
  keyword doesn't catch it, extend `checklist_scheme_name`.
- **`validate_data` reports an issue post-load.** That command
  (`apps/core/management/commands/validate_data.py`) is the canonical
  reference for what counts as a legal fixture; it's what catches drift
  the type-system can't see.

## 9. Fake data, caveats

The script invents data where the sources don't say:

- **Worker time** is a per-task random value in `[0.5, 4.0]` hours (2 sig
  figs). The checklists carry no per-task time data, so this is fully invented
  ("won't be accurate to real life but is likely all we can really do"). The RNG
  is fixed-seeded so regen is stable.
- **Bleps + Shifts** are entirely synthetic — one blep per complete task, its
  length pegged to the (invented) worker-time estimate, placed in the job's date
  window and wrapped in enclosing shifts. Extra worker users are minted if the
  rotation pool can't absorb the load. Real shop time was never in the sources.
- **entered_qty actuals** and **invoice paid amounts** are derived (thirds-rule
  vs est_qty; invoice line-item total), not real.
- **Material unit costs** are the PLI purchase price when matched, else
  `sell_price × 0.8333`; the PLI link itself is a best-effort fuzzy match.
- **Project managers** are random rotation-pool users on every non-draft Job —
  informational only (no business-logic side effects), so any user fits.
- **Fake Deliverables** are synthesised for jobs whose estimate has no
  line item that classifies as a deliverable. The verbose summary counts
  these; review them periodically.
- **Job names** come from the Kanban Description (FreeAgent has no job
  names). They're truncated to 50 characters.
- **Job numbers** are the FreeAgent base reference verbatim (e.g.
  `03024`). When no container estimate `Date` parses, the Job's `created_date`
  falls back to `_FALLBACK_YEAR-01-01T00:00:00+00:00` (currently 2025);
  otherwise it is the earliest estimate date − 1 day. The job_number itself is
  unaffected by this.
- **Archived jobs carry no invented data.** Everything the converter
  fabricates for live jobs (worker times, invented `est_qty`, bleps and
  shifts, fake deliverables, shipments, PO and earmark state, transient
  lots, QBO payment fields) is stripped from archived jobs, since the
  importer could not have produced it (§4, "Archived jobs").
- **PII** is replaced, never preserved. The dataset is intended to look
  realistic but contain nothing real.

## 10. Tests

The pipeline is covered by:

- `tests/test_neals_parsing.py` — pure helpers in `parsing.py`.
- `tests/test_neals_loaders.py` — the Excel + CSV loaders.
- `tests/test_neals_builders.py` — every builder and the reconcile passes,
  exercised against the real `datasets/` files (skipped if not present).
  The fixture file is auto-discovered via `discover_datasets` so any
  matching pair of `.xlsx`/`.csv` works without editing the test.
  Several behavioural changes (Shipment synthesis, Invoice source-link
  wiring, completed-job downgrade, blep/shift placement, the job-date swap,
  invoice dates) are covered by dedicated `*SynthesisTest` / `*WiringTest` /
  `*SwapTest` / `Downgrade*Test` classes that build minimal synthetic state and
  assert the new behaviour directly — they don't depend on the real data
  exercising the case. `VendorBuildersTest` covers the Bills-sheet vendor
  import (cap, most-recent-first ordering, reuse on canonical org match,
  name-only skip). `ContactResolutionTest` is a dataset-free synthetic test of
  `resolve_contact` — canonicalization/fuzzy folding, the individual-vs-business
  split, multi-contact businesses, and `_FORCE_DISTINCT`. The name-matching
  primitives (`normalize_name`, `clean_display_name`, `name_similarity`,
  `looks_like_person`) have unit tests in `test_neals_parsing.py`.
  `PurchasingBuilderTest` runs the whole pipeline once (`convert()`) and asserts
  `build_purchasing`'s invariants: every Material item-backed, transient lots
  priced via the markup, no negative QOH, consumption-by-task, earmarks only on
  pending Materials of active jobs, `received_in_full` POs linking Materials, and
  Bills linked to those POs.
  The archive rule has its own classes: `RunClockTest` (`now` / `c.now`),
  `EstQtyProvenanceTest` (`c.invented_est_qty`), `ArchiveOldJobsTest` (the
  rule and every row of the §4 shape), `ArchivedJobsDownstreamSkipTest` (the
  builder guards), `ArchivedJobHistoryTest` (importer-shaped history rows),
  and `ConvertEndToEndTest.test_archive_rule_holds_end_to_end`.
- `tests/test_neals_fixture.py` — loads the generated `converted.json`
  into the test database and runs `validate_data` over it. This is the
  end-to-end safety net; it also asserts bleps/shifts load and that the
  enclosure / no-overlap / task-not-pending invariants report no errors, and
  (`test_archived_jobs_present_and_valid`) that archived jobs load and pass
  the archived-job checks.
- `tests/test_neals_archive_parity.py` — `ConverterImporterParityTest` loads
  `converted.json` and checks that every archived job is reproduced, field
  for field, by `ArchiveImportService` from a payload built off that job.
  `FarFutureParityTest` runs a conversion with a 2030 clock so every closed
  job archives, covering materials, superseded chains and cancelled tasks
  that the real-clock dataset's few archives lack.

`validate_data` now also enforces the time-tracking invariants
(`check_bleps_and_shifts`): a blep's task is never pending, every closed blep is
enclosed by a shift of the same user, and no two of a user's bleps overlap.

Run them with:

```bash
python manage.py test tests.test_neals_parsing tests.test_neals_loaders \
    tests.test_neals_builders tests.test_neals_fixture \
    tests.test_neals_archive_parity
```

Per `CLAUDE.md`, only one agent/process may run the Django test suite at a
time (the MySQL test DB cannot survive parallel teardown).
