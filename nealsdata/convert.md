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
- **est *cut* time** and **est ASS time** are job-level hour estimates that
  land on one task each (see §4). `est $` is ignored.
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
   verbatim from `fixtures/large_datasets/nealseed.json`, then creates one
   extra shared "Flat Fee" RateScheme for tasks that don't fit a seeded one.
4. **`build_configuration`**: emits the `core.configuration` entries the
   app needs at runtime (numbering patterns + counters, `units_list`,
   retention windows).
5. **`build_price_list_items`**: copies the FreeAgent Price List Items
   sheet.
6. **`build_contacts_and_businesses`**: walks the Contacts sheet and emits
   only the businesses/contacts actually referenced by a spine card.
   Anonymizes emails + phones (see §6).
7. **`build_jobs`**: one Job per spine entry, named from the card
   Description, status from Stage + Swimlane. Job number is the FreeAgent
   estimate base reference (the digit run, e.g. `03024`) — the same
   identifier used to join Kanban cards to Estimates rows. Accent color is
   round-robined through `JOB_ACCENT_COLOR_PALETTE` (mirrored from
   `apps.jobs.models`) so loaddata-emitted jobs render with the colored
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
   stay on the Job either way. This is where most of the interesting logic
   lives — see §4.
10. **`build_invoices`**: emits Invoices + line items via the
    Project-name link. Stashes each emitted line's classification (`task`,
    `material`, `lineitem`, `skip`) on `c.invoice_line_kinds` for the
    next phase.
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

The Kanban card carries two job-level hour columns: `est *cut* time` and
`est ASS time`. `_apply_worker_times` lands each on at most one task:

- **cut time** → the first task on the job whose name contains `cut`.
- **ass time** → the first task whose name contains `assemb`, `build`,
  or `make`, *and* isn't the same task already given the cut time.

The cut/ass columns are sparse in recent data, so in practice almost
nothing matches. Every other task — and that's most of them — gets a flat
**1-hour** default (`_DEFAULT_WORKER_TIME`). The checklist itself carries
no per-task time data, so a real estimate is not derivable from it.

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
5. **Job status & dates** — `start_date` for started jobs, `completed_date`
   for terminal jobs (preferring `Archived at`, falling back to the
   estimate's `closed_date`, finally the job's `created_date`).
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
material attach), `c.scheme_by_name`, `c.invoice_line_kinds` (per-line
classifications used by `build_invoice_line_item_sources`), the pk
counters, and a few diagnostics (`c.discarded_cards`,
`c.time_match_misses`, `c.fake_deliverable_count`).

## 8. Common updates you'll likely need

- **The Minibini schema changed.** Look at `docs/designs/data-constraints.md`
  first to see what the model now requires. Then update the relevant
  builder in `build.py`. The fixture-load test
  (`tests/test_neals_fixture.py`) catches FK / field / NOT-NULL drift
  immediately.
- **A Kanban column was added/renamed/removed.** Update `KanbanCsvLoader`
  isn't necessary — it uses `DictReader` and is column-name-driven — but
  any consumer (`build_jobs`, `_apply_worker_times`, etc.) that names the
  column directly needs the change. Update §1's column table here too.
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

- **Worker time defaults to 1 hour** for any task not matched by the
  card's `est *cut* time` or `est ASS time`. The checklists carry no time
  data, so there is no better source. ("won't be accurate to real life
  but is likely all we can really do.")
- **Fake Deliverables** are synthesised for jobs whose estimate has no
  line item that classifies as a deliverable. The verbose summary counts
  these; review them periodically.
- **Job names** come from the Kanban Description (FreeAgent has no job
  names). They're truncated to 50 characters.
- **Job numbers** are the FreeAgent base reference verbatim (e.g.
  `03024`). When `Date` is missing on the primary estimate row, the Job's
  `created_date` falls back to `_FALLBACK_YEAR-01-01T00:00:00+00:00`
  (currently 2025); the job_number itself is unaffected by this.
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
  wiring, completed-job downgrade) are covered by dedicated
  `*SynthesisTest` / `*WiringTest` / `Downgrade*Test` classes that build
  minimal synthetic state and assert the new behaviour directly — they
  don't depend on the real data exercising the case.
- `tests/test_neals_fixture.py` — loads the generated `converted.json`
  into the test database and runs `validate_data` over it. This is the
  end-to-end safety net.

Run them with:

```bash
python manage.py test tests.test_neals_parsing tests.test_neals_loaders \
    tests.test_neals_builders tests.test_neals_fixture
```

Per `CLAUDE.md`, only one agent/process may run the Django test suite at a
time (the MySQL test DB cannot survive parallel teardown).
