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
python nealsdata/convert_neals_data.py [--limit N] [--verbose]
```

The default `--limit 100` caps how many Jobs are built from the most recent
matched Kanban cards. The output is `nealsdata/datasets/converted.json` (the
file is git-ignored — regenerate it whenever inputs change).

Loading the result into Minibini is the user's job — the script never writes
to a database. Tests load it into the auto-created test DB via
`call_command('loaddata', ...)`.

## 3. Pipeline at a glance

`orchestrator.NealsDataConverter.convert()` runs these phases in order:

1. **Load**: Excel sheets into memory; Kanban CSV into a list of dicts.
2. **Select spine**: pair each recent Kanban card with the Estimates-sheet
   rows whose `Reference` base matches the card's `External ID`. The
   newest `--limit` matched cards become the Jobs we'll build.
3. **`build_seed`**: copies users, accounting categories and rate schemes
   from `fixtures/large_datasets/nealseed.json`, then creates one extra shared
   "Flat Fee" RateScheme for tasks that don't fit a seeded one. **Assigns
   explicit pks to the (otherwise pk-less) seed users** and builds
   `c.user_by_username`, the blep-rotation pool `c.rotation_user_pks` (every
   active seed user except `system`), and `c.scheme_algorithm_by_pk` (used for
   entered_qty actuals). Records a seed worker's fields as the clone template
   for minting extra users (§4).
4. **`build_configuration`**: emits the `core.configuration` entries the
   app needs at runtime (numbering patterns + counters, `units_list`,
   retention windows).
5. **`build_inventory_items`**: copies the FreeAgent Price List Items
   sheet.
6. **`build_contacts_and_businesses`**: walks the Contacts sheet and emits
   only the businesses/contacts actually referenced by a spine card.
   Anonymizes emails + phones (see §6).
7. **`build_jobs`**: one Job per spine entry, named from the card
   Description, status from Stage + Swimlane. Job number is the FreeAgent
   estimate base reference (the digit run, e.g. `03024`) — the same
   identifier used to join Kanban cards to Estimates rows. **`created_date` is
   the earliest container estimate's `Date` minus one day** (the job object
   exists a day before its first estimate); `start_date` is filled later by
   reconcile from the *latest* estimate's date, so `created_date < start_date`.
   Accent color is round-robined through `JOB_ACCENT_COLOR_PALETTE` (mirrored
   from `apps.jobs.models`) so loaddata-emitted jobs render with the colored
   bars the SPA board expects.
8. **`build_estimates`**: emits the Estimate + its line items for every
   revision in the chain. Estimate number is `{job_number}-{version}` — the
   canon form `EstimateService.create_estimate` would have produced. Each
   estimate also gets a fresh `public_token` via `secrets.token_urlsafe(32)`
   so the customer-portal URL (`/portal/?token=…`) works for seeded data.
   Estimate line items are **kept**; downstream atoms (Task, Material,
   Deliverable) are *copies*, not moves.
9. **`derive_atoms`**: for each Job, builds Tasks/PlanTasks,
   Materials/PlanMaterials, and Deliverables from the Kanban Checklist
   and/or the estimate line items. Branches on the Job's as-built status:
   `draft`/`submitted` route to the plan side (one EstWorksheet per Job,
   PlanTasks + PlanMaterials on it, and an EstimateLineItemSource per
   LI-derived atom); everything else routes to the real side. Deliverables
   stay on the Job either way. Materials get a `unit_cost` and an optional
   `inventory_item` link via fuzzy matching (§4). This is where most of the
   interesting logic lives — see §4.
9a. **`assign_worker_times`**: gives every Task and PlanTask an invented
    per-task `est_worker_time` — random in `[0.5, 4.0]` hours, 2 sig figs,
    minute granularity (§4).
9b. **`assign_est_quantities`**: fills `est_qty` on every real Task by its
    rate-scheme algorithm (hourly = worker hours; flat fee = 1; entered_qty =
    piece count tied to worker time) — §4.
10. **`build_invoices`**: emits Invoices + line items via the
    Project-name link. Stashes each emitted line's classification (`task`,
    `material`, `lineitem`, `skip`) on `c.invoice_line_kinds` for the
    next phase. Sets `sent_date` on `open`/`paid` invoices (= the FreeAgent
    invoice Date) and `qbo_amount_paid` on `paid` invoices (= that invoice's
    own line-item total; `draft` invoices stay null-dated — §8).
11. **`build_invoice_line_item_sources`**: heuristic source-link wiring
    — for each Invoice, claim Tasks/Materials on the Job in deterministic
    order against the invoice's line items so the SPA shows them as
    "billed" rather than orphaned. Honours the model's global
    `unique_together(source_type, source_pk)`. Leftover lines stay
    freeform.
12. **`reconcile`**: cross-model fixups in a fixed order — see §5.
13. **`build_shipments`**: runs *after* reconcile so it can see final Job
    status / dates. Builds a Shipment + ShipmentItems for any card whose
    checklist has a checked `Picked up/Delivered` line OR for any Job that
    landed in `completed` status without a marker (synthesised — see §4).
13a. **`assign_project_managers`**: runs *after* reconcile (needs final job
    status). Assigns a random `project_manager` from the seed rotation pool to
    every Job beyond `draft`; draft jobs keep a null PM.
14. **`build_bleps_and_shifts`**: runs *after* reconcile (needs final task
    statuses + job dates). Emits one Blep per complete Task **within a three-week
    horizon**, the Shifts that enclose them, and `actual_qty` for complete
    `entered_qty` tasks (§4).
14a. **`assign_current_work`**: runs *after* `build_bleps_and_shifts`. Gives each
    rotation worker up to three random **pending** Tasks drawn from
    **in_progress** Jobs (assignee + `worker_queue`), so the board and schedule
    show current work (§4).
15. **`build_history`**: last — emits a created/transition entry per tracked
    object.

The RNG is seeded with a fixed constant at the top of `convert()` so the
invented worker times and blep placement are byte-stable across regenerations
unless the inputs change.

## 4. Building Tasks, Materials, and Deliverables

This is the most-rewritten part of the script and the part most likely to
need tweaking again.

### Plan side vs real side

`derive_atoms` branches on the Job's as-built status (set by `build_jobs`,
read from `c.jobs[base_ref]['status']`).

- **`draft` and `submitted` → plan side.** No estimate has been accepted
  yet (per §2.3 the accept event is what copies plan atoms onto the Job),
  so the atoms live on an `estimates.estworksheet`. Tasks become
  `jobs.plantask` (flat — no hierarchy; PlanTask's `clean()` requires
  non-null `est_qty`, so checklist-derived plan tasks get `Decimal('1')`),
  Materials become `inventory.planmaterial`. Each LI-derived plan atom
  also gets an `estimates.estimatelineitemsource` row linking back to its
  source line item so the worksheet/estimate relationship is traceable.
- **Every other status → real side** (existing behaviour): Tasks on Job
  with full lifecycle, Materials on Job. Checklist subtask hierarchy and
  `[X]`/`[ ]` status preserved.

Deliverables go on the Job in both modes (deliverables are job-scoped, not
plan-scoped).

A Job that was draft/submitted at derive time but later expired and was
rejected by the reconcile pass keeps its plan-side state — the worksheet
and plan atoms become the historical record of "we estimated this; the
customer never accepted."

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

Every task is assigned a RateScheme:

- Checklist tasks: keyword-matched (`checklist_scheme_name`):
  - `cut`        → `CNC Routing`
  - `laser`      → `Laser`
  - `draw` / `cad` / `model` → `CAD`
  - everything else → `Shop labor`
- Line-item tasks: same keyword rule; if no keyword hits, try to match a
  seeded scheme by `(algorithm, rate)`; failing that, fall back to the
  shared **Flat Fee** scheme and stash the price in
  `Task.active_modifiers = {'flat_fee_price': '…'}`.

If the named scheme isn't in nealseed, the closest match is used (see
`_match_seed_scheme`). When you add new schemes to nealseed, this will pick
them up automatically.

### Estimated worker time

Every Task **and** PlanTask gets an invented per-task `est_worker_time` in a
single pass (`assign_worker_times`, run after `derive_atoms`): a random value
uniform in `[0.5, 4.0]` hours, rounded to 2 significant figures and stored at
minute granularity. The pass iterates in `(model, pk)` order with the seeded
RNG, so output is deterministic.

The old `est *cut*`/`est ASS` Kanban columns are **no longer consumed** — they
were rare *whole-job* estimates wrongly stamped onto a single task, which made
no sense once every task carries its own per-task estimate. The checklist holds
no per-task time data, so a real estimate isn't derivable from it anyway.

### Estimated quantity (real Tasks)

`assign_est_quantities` (after `assign_worker_times`) fills `est_qty` on every
real Task by its rate-scheme algorithm. `est_qty` is optional on `Task` (nullable
at the DB level and unenforced; only `PlanTask` requires it), but the dataset
wants it populated:

- **elapsed_time** (hourly, the most common): `est_qty` = the worker-time
  estimate in hours (`02:30:00` → `2.50`), set always — so estimated billable
  hours equal the estimated worker time.
- **flat_fee**: `1.00` (a single fixed charge), unless a source line set a qty.
- **entered_qty** (piece counts): tied to the worker time — `round(worker_hours
  × pieces_per_hour)`, `pieces_per_hour` random 2–6 (min 1) — unless a source
  line set a qty. This also feeds the `entered_qty` actuals.

PlanTasks keep the `est_qty` they were built with.

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
  and to ≥ the horizon; and **no user's bleps overlap**. A blep sits in an
  08:00–16:00 UTC workday (weekends allowed),
  packed back-to-back. Users are taken round-robin from `c.rotation_user_pks`;
  if every existing user is booked across a job's window, a new worker is
  **minted** (`_mint_user`) as the pressure valve.
- **Shifts**: one `core.shift` per (user, calendar day) with bleps, tightly
  enclosing that day's bleps (`start` = first blep start, `end` = last blep
  end) — satisfying the shift↔blep enclosure invariant. `loaddata` bypasses
  `Blep.save()`/`Shift.save()`, so all timestamps are emitted pre-floored to
  the minute.
- **entered_qty actuals**: a complete task on an `entered_qty` scheme gets an
  `actual_qty = est_qty × {thirds}` (fallback base `1` when `est_qty` is null)
  so it doesn't invoice at zero. This is set for **every** complete task — even
  ones too old for a blep under the horizon — so historical work never invoices
  at zero. `elapsed_time` tasks derive qty from their bleps; `flat_fee` uses
  `est_qty`/1 — neither needs an explicit actual.

`assign_current_work` (after `build_bleps_and_shifts`) then populates **current**
work: each rotation worker (excludes `system` + minted users) gets up to three
random **pending** Tasks drawn from **in_progress** Jobs, with `assignee` and a
per-worker `worker_queue` (0,1,2). The Tasks stay `pending` — assigned, not yet
started — so they appear as forecast bars on the schedule (ScheduleService
includes pending assigned tasks) and as queued cards on the job board. Only Tasks
with an `est_worker_time` are eligible (`Task.clean()` requires it on an assigned
Task). Deterministic given the seeded RNG.

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
from the price list, is an acceptable miss.

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
Pickup-marker checklist lines never become Tasks.

### Units mapping

`build_configuration` writes `units_list` mirroring
`apps.core.units.DEFAULT_UNITS` so every emitted line-item, Material and
Deliverable row validates against the running app's canonical list.
`parsing.resolve_li_units_and_qty` converts FreeAgent `Item Type` values:

- `Hours` → `units='hours'`, qty unchanged
- `Days`  → `units='hours'`, qty multiplied by 8 (one workday)
- anything else → `units='none'`, qty unchanged

Deliverables default to `units='ea'` (canon form of `each`).

## 5. Reconciliation passes

`reconcile.reconcile()` runs after all builders, in this order:

1. **Estimate version chains** — for any base reference with multiple
   versions, every version below the highest is marked `superseded` and
   linked to the previous via `parent`. The highest keeps the builder's
   status.
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
7. **Task status from job** — cancel tasks on cancelled/rejected jobs.
   Otherwise the per-checklist `[X]`/`[ ]` state is preserved.
8. **Document counters** — Configuration counters for jobs/invoices/POs
   are set to the number of emitted records so the next number generated
   by the running app doesn't collide. `estimate_counter` is intentionally
   excluded — estimate numbers now derive from `{job_number}-{version}`,
   not from a counter.

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
    reconcile.py          cross-model fixups (the 8 passes above)
    orchestrator.py       NealsDataConverter — phase wiring + state container
```

The state container (`NealsDataConverter` instance, conventionally `c`)
carries everything between phases: `c.fixture_data` (the output list),
`c.org_map`, `c.job_map`, `c.jobs` (with `'status'` for plan/real
branching in `derive_atoms`), `c.estimates`, `c.line_items`, `c.cut_task`
and `c.cut_plan_task` (the real/plan-side first-cut-task index for
material attach), `c.scheme_by_name`, `c.scheme_algorithm_by_pk` (for
entered_qty actuals), `c.user_by_username` / `c.rotation_user_pks` (blep
rotation), `c.pli_index` / `c.pli_purchase_by_code` (material→PLI matching),
`c.invoice_line_kinds` (per-line classifications used by
`build_invoice_line_item_sources`), the pk counters, and a diagnostic
(`c.discarded_cards`, `c.fake_deliverable_count`).

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
  exercising the case.
- `tests/test_neals_fixture.py` — loads the generated `converted.json`
  into the test database and runs `validate_data` over it. This is the
  end-to-end safety net; it also asserts bleps/shifts load and that the
  enclosure / no-overlap / task-not-pending invariants report no errors.

`validate_data` now also enforces the time-tracking invariants
(`check_bleps_and_shifts`): a blep's task is never pending, every closed blep is
enclosed by a shift of the same user, and no two of a user's bleps overlap.

Run them with:

```bash
python manage.py test tests.test_neals_parsing tests.test_neals_loaders \
    tests.test_neals_builders tests.test_neals_fixture
```

Per `CLAUDE.md`, only one agent/process may run the Django test suite at a
time (the MySQL test DB cannot survive parallel teardown).
