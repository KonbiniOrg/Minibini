# Converter: old work as archived jobs — design

Date: 2026-10-21. Discussed with RM 2026-10-21. Follows the archived-jobs
feature on `feature/archival-jobs` (durable reference:
`docs/designs/jobs-and-tasks.md` §3.8).

## 1. Intent

The nealsdata converter (`nealsdata/`) turns Neal's FreeAgent export plus the
Kanban CSV into a dev/test fixture. Today every job it emits is a *live* job,
and to make old jobs pass the live invariants it invents a great deal: worker
times, bleps and shifts, fake deliverables, fake shipments, project managers,
purchasing state, estimate source wiring and a per-object history cascade.

Now that the app has an `archived` status for historical work, old jobs
should come through as archived jobs instead: the translated facts only, in
the same shape `ArchiveImportService` produces, with none of the inventions.
This makes the dev dataset show what a real import will look like, and it
exercises the archived code paths with realistic volume.

Secondary intent: the archived-job importer must accept estimate version
chains, because the converter's chains are genuine history RM does not want
to lose. That change ships here, since the converter is its first producer.

## 2. Goals, non-goals, anti-goals

Goals

- Any job the converter reconciles to `completed` or `rejected` whose
  `completed_date` is six months or more before run time is emitted as an
  `archived` job carrying only translated data.
- An archived converter job is **exactly** what `ArchiveImportService`
  would have created from an equivalent payload (tasks, materials,
  estimates, invoices, history rows). Every field and row on a converter
  archive must be expressible in the importer's payload; otherwise RM's
  testing of the archive feature on converted data is not valid (RM
  2026-10-21).
- `ArchiveImportService` accepts multi-version estimate chains.
- The generated fixture still loads and passes `validate_data`
  (`tests/test_neals_fixture.py`).

Non-goals

- No change to spine selection: old cards compete for the `--limit` slots
  exactly as today. The limit remains an approximate upper bound on dataset
  size.
- No spreadsheet import, no UI, no e2e. Nothing here has a browser surface,
  so the e2e Definition-of-Done rule does not apply.
- No change to how *live* converter jobs are built.

Anti-goals

- Invented data on an archived job. If a value is not in the sources, the
  archive leaves it empty and the app's "imported labor may be incomplete"
  caveat covers it.
- A converter archive that the importer could not have produced. The one
  exception is the estimate version chain, and only because the importer
  is being taught it here. Where the converter knows something the
  importer's payload cannot express (the estimate-line source rows behind
  line-derived tasks and materials, the task's `source_scheme`
  provenance), the converter **drops it** rather than the importer
  growing a field for it: the importer will take a single spreadsheet from
  users unfamiliar with konbini's data structure, and those relationships
  are too involved to ask of them (RM 2026-10-21).

## 3. The rule

### 3.1 Which jobs

After `reconcile.reconcile(c)` has settled every job's final status and
dates, a job is archived when:

- its status is `completed` or `rejected` (or `cancelled`, should the
  converter ever produce it), **and**
- its `completed_date` is on or before `cutoff = now − 6 calendar months`
  (`dateutil.relativedelta`, the same arithmetic as the app's customer
  financials window).

`now` is wall-clock UTC, captured **once** at the top of `convert()` and
passed down, so one run never straddles a boundary. RM regenerates the input
datasets periodically off live data and wants the output to track real time;
the fixture is therefore no longer byte-stable across days, and tests must
assert the rule, not fixed counts (see §7).

Jobs reconcile pass 6 downgraded to `work_complete` for an unpaid invoice are
not archived whatever their age: they are genuinely unresolved. Jobs
`completed` whose date is younger than the cutoff stay live, as today.

### 3.2 Why after reconcile

A conservative early guess is possible for most cards (Stage plus
`Archived at`), but reconcile can still move a job: pass 3 rejects on
expiry, pass 6 downgrades, pass 6.5 promotes, and pass 5 is what sets
`completed_date` (preferring the card's `Archived at`, then the estimate's
closed date, then `created_date`). Classifying after reconcile is the only
exact point. The cost is that some rows already emitted for these jobs
(deliverables, their source rows, transient lots, worker times) have to be
removed or nulled by the archive pass. That is new for the converter, which
until now only ever appended or mutated fixture rows; it is acceptable.

## 4. What an archived converter job carries

Per job, after the archive pass:

| Record | Archived shape |
|---|---|
| `jobs.job` | `status='archived'`; `job_number`, `contact`, `name`, `description`, `due_date` (from the card), `created_date`, `start_date` (completed outcome only; rejected has none), `completed_date` as reconciled. `project_manager=None`. `accent_color` left as round-robined (my call: harmless, the SPA renders archives grey). |
| `jobs.task` | The checklist / line-item tasks with their reconciled `complete` / `cancelled` status, `name`, `description`, `sort_order`, `parent=None`. Money block exactly as the importer writes it: `qty_source='entered_qty'`, `rate`, `unit_label`, `accounting_category` as plain values (stamped from the keyword scheme, then detached); `source_scheme=None`, `active_modifiers=[]`, `service_item=None`. `est_qty` is **kept only when it came from the estimate line's own quantity** (a line-derived task whose line carried a qty) and nulled when `assign_est_quantities` invented it (every `elapsed_time` task, and any entered-qty task filled from the random pieces-per-hour rule); the pass therefore needs to know which is which, recorded when `assign_est_quantities` runs. `est_worker_time`, `actual_qty`, `assignee`, `worker_queue` always null/empty. |
| `inventory.material` | Raw-stock lines as today (`description`, `quantity`, `units`, `unit_cost` from the PLI match or the 0.8333 ratio, `task` link to the cut task). `consumption_state='consumed'`, `cost_source='imported'`, `released_qty=0`, `po_line_item=None`. `inventory_item` kept when it points at a real price-list item; cleared when it pointed at a converter-minted transient lot, and that lot row is removed if no other material references it. |
| `estimates.estimate` + lines | Unchanged: the full version chain with `superseded` lower versions, `parent` links, statuses and dates as reconciled. |
| `estimates.estimatelineitemsource` | None. Every source row for the job's tasks, materials and deliverables is removed, including the ones `derive_atoms` emitted for line-derived atoms (the importer cannot express them). No synthetic round-robin rows. |
| `invoicing.invoice` + lines | Status, dates and lines as reconciled. `qbo_amount_paid=None`, `qbo_id=None`, `qbo_payment_status=''`: the importer never sets QBO fields, and there is no link between QBO data and imported data nor will there be in the foreseeable future (RM 2026-10-21). Harmless to the customer totals, which only sum `qbo_amount_paid` over unpaid-status invoices. No `invoicelineitemsource` rows, no `agreement_estimate_line` refs. |
| `deliverables.deliverable` | None. Deliverable-shaped estimate lines stay as estimate lines. The `Fake Deliverable` is removed and `c.fake_deliverable_count` decremented so the verbose summary stays honest. |
| `deliverables.shipment` | None. |
| bleps / shifts | None. |
| earmarks, POs, PO lines, lot QOH / `qty_sold` changes | None. `build_purchasing` skips archived jobs' materials entirely. |
| `core.jobhistory` | The importer's rows only (§5). |

Contacts, businesses and their CRM history rows are unaffected.

## 5. History rows

Mirror what `ArchiveImportService.create_archived_job` leaves behind. It
does two things: its own history context flushes a `_created` audit row
for **every record it creates** (job, each task, material, estimate and
invoice), timestamped at import time with `user=None`; and
`_write_history` adds backdated lifecycle action rows on the job. The
converter emits the same set, all `user=None`:

Audit rows (`entry_type='audit'`, `changes={'_created': True}`), one per
job, task, material, estimate and invoice of the archived job, timestamped
at the run's `now`.

Action rows on the job (`entry_type='action'`, `changes={'_action': …}`):

1. `Created` at `created_date`.
2. `Started` at `start_date`, when set.
3. The outcome at `completed_date`: `Completed`, `Rejected` or `Cancelled`
   (capitalised status label).
4. `Imported from Kanban` at the run's `now`.

Plus, when the card's checklist has a checked `Picked up/Delivered` marker,
one `entry_type='note'` row at `completed_date` with text
`Picked up/Delivered (Kanban checklist)`, so the fact survives without a
Shipment. No transition rows for tasks, materials, estimates or invoices
(the importer writes none).

## 6. Pipeline placement and downstream skips

New pass `build.archive_old_jobs(c, cutoff)` runs immediately after
`reconcile.reconcile(c)` and before `assign_project_managers`. It flips the
status, strips and nulls per §4, records `c.archived_job_pks` (set) and
`c.archived_outcome[job_pk]` (the pre-archive status), and emits nothing.

Every later builder skips archived jobs explicitly, even where an existing
filter would already exclude them, so the intent is readable:
`assign_project_managers`, `build_shipments`, `build_bleps_and_shifts`,
`assign_current_work`, `build_purchasing`,
`build_invoice_line_item_sources`, `build_invoice_agreement_refs`,
`build_synthetic_estimate_sources`, `build_checklist_declines`.
`build_history` gets an archived branch that emits §5 instead of the causal
timeline.

Reconcile pass 8 (document counters) is unaffected: archived jobs and their
invoices still count toward the emitted totals.

`NealsDataConverter.__init__` gains `now=None` (defaults to
`datetime.now(timezone.utc)`); `convert()` derives `cutoff` from it, and
the same `now` replaces reconcile's two `date.today()` calls so one run has
one clock. No new
CLI flag: the six-month rule is a constant (`_ARCHIVE_AFTER_MONTHS = 6` in
`build.py`), and tests inject `now`. The `--verbose` summary adds a line:
`N jobs archived (completed/rejected ≥ 6 months before <now date>)`.

## 7. Importer change: estimate version chains

`ArchiveImportService` (`apps/jobs/archive.py`) accepts, in `estimates[]`:

- `version`: integer ≥ 1, default 1.
- Rows sharing an `estimate_number` form a chain. Validation (path-keyed,
  as today): versions within a chain are contiguous from 1 with no
  duplicates; every version below the chain's highest has
  `status='superseded'`; the highest has one of the settled statuses
  (`accepted` / `rejected` / `expired`). "At most one accepted" remains a
  payload-wide rule. Number uniqueness against the DB checks any version
  (`Estimate.objects.filter(estimate_number=n).exists()`), not only
  version 1; within the payload the duplicate check becomes
  `(estimate_number, version)`.
- Creation: each row is created at its `version`; after the chain is
  created, every version's `parent` is set to the previous version (my
  call: a second pass of `update(parent=…)`-free `save()`s is unnecessary
  since `Estimate.save` hooks fire only on status *change*; create in
  version order and pass `parent=` directly). A superseded row with no
  `closed_date` defaults it to the successor's `created_date` (the
  validator warns on superseded without a closed date).
- `_document_statuses()['estimates']` gains `superseded`, but only
  non-highest versions may carry it (the rule above).

Docs: `jobs-and-tasks.md` §3.8 payload table (currently says
`version=1`), `data-constraints.md` if it restates the rule, and
`nealsdata/convert.md` (new subsection under §4 or §5, the §3 phase list,
§9 "Fake data" and the test list). While in `convert.md`, correct its
stale references to `jobs.fee` atoms: there is no Fee model and
`derive_atoms` leaves fixed-charge lines as plain document lines.

## 8. Tests

Converter (`tests/test_neals_builders.py`, dataset-free synthetic classes in
the existing `*SynthesisTest` style, plus one end-to-end assertion):

- Archives `completed` and `rejected` jobs at or before the cutoff; leaves
  younger completed jobs, `work_complete` and live statuses alone.
- Importer parity: a test that creates one archive through
  `ArchiveImportService` and one through the converter pass from
  equivalent inputs and asserts the task, material, estimate, invoice and
  history rows match field for field (ignoring pks, numbers and
  timestamps that are set at run time).
- Strips deliverables and their source rows, removes orphaned transient
  lots, keeps real PLI links, keeps line-sourced `est_qty` and nulls
  invented `est_qty` / worker time / actuals / assignee, sets
  `qty_source='entered_qty'`, removes every source row for the job and
  nulls `source_scheme`, sets material `consumed` + `imported`, clears PM,
  keeps `due_date`, nulls the invoices' QBO fields.
- Every downstream builder leaves archived jobs untouched (no shipment,
  blep, shift, earmark, PO, source wiring, declines, agreement refs).
- History: exactly the §5 rows (the `_created` audits per record plus the
  job action rows, in order), with the pickup note when the marker is
  present and without it otherwise.
- `convert()` with an injected `now`: every job whose reconciled
  `completed_date ≤ cutoff` is archived and no other job is; the summary
  count matches.
- `tests/test_neals_fixture.py`: the regenerated `converted.json` loads and
  `validate_data` reports no errors (existing tests; `check_archived_jobs`
  and `check_job_work_complete_gate` now cover the archives).

Importer (`tests/test_archive_import.py`): a two-version chain creates
both rows with `parent` linked and the lower `superseded`; non-contiguous
versions, a lower version not marked superseded, a highest version marked
superseded, and a duplicate `(number, version)` each produce a path-keyed
error; a number already in the DB at version 2 is refused; the superseded
row's `closed_date` defaults to the successor's `created_date`.

Per CLAUDE.md the converter is read-only on sources and write-only to the
git-ignored `nealsdata/datasets/converted.json`; regenerating that file is
part of this work. `fixtures/large_datasets/nealseed.json` is RM-managed
and is not touched.

## 9. Left to the builder

- How the archive pass removes rows from `c.fixture_data` (filter and
  rebuild the list, or collect pks and skip on write).
- Whether transient-lot orphan detection runs per job or once after all
  archives are decided.
- The exact dataset-free fixtures for the new test classes.
