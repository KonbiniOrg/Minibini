# Converter Archived Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The nealsdata converter emits jobs completed or rejected six or more months before run time as `archived` jobs carrying only translated data, shaped exactly as `ArchiveImportService` would create them; the importer learns estimate version chains.

**Architecture:** A new post-reconcile pass `archive_old_jobs` in `nealsdata/converter/build.py` flips status, strips invented rows and nulls invented fields; every later builder skips archived jobs; `build_history` gets an importer-shaped branch. `ArchiveImportService` gains a `version` field with chain validation. A Django parity test loads the converter output and proves the importer reproduces each archived job field for field.

**Tech Stack:** Python 3.12, Django 5.2 test runner, `dateutil.relativedelta`, the converter's pure-JSON fixture pipeline.

**Spec:** `docs/plans/2026-10-21-converter-archived-jobs-design.md`

## Global Constraints

- Never write to the dev database: no `migrate`, no `loaddata` outside the test runner, no `manage.py shell` writes, no DB-mutating scripts. The converter itself is read-only on sources and writes only `nealsdata/datasets/converted.json` (git-ignored); running it is allowed.
- `fixtures/large_datasets/nealseed.json` is RM-managed: never regenerate or edit it.
- Django tests: always `python manage.py test <modules> --noinput`, foreground, one run at a time, never piped. Judge by the `Ran N tests` / `OK` / `FAILED` lines. Converter changes must run `tests.test_neals_builders` (memory rule). After the fixture is regenerated, `tests.test_neals_fixture` must be run too.
- Status strings in `build.py` / `reconcile.py` are literals mirroring the model constants (the converter imports no Django). In `archive.py` and tests use the model constants.
- Cutoff arithmetic: `cutoff = now - relativedelta(months=6)`; a job is archived when `completed_date <= cutoff`. `_ARCHIVE_AFTER_MONTHS = 6` lives in `build.py`.
- Archived jobs are only ever `completed`, `rejected` or `cancelled` jobs at reconcile exit; `work_complete` is never archived.
- History text, verbatim: action rows `Created`, `Started`, `Completed` / `Rejected` / `Cancelled`, `Imported from Kanban`; note text `Picked up/Delivered (Kanban checklist)`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- No e2e: nothing here has a browser surface.

## Review Focus

1. A `completed` job whose `completed_date` fell back to `created_date` (no `Archived at`, no estimate closed date) must still archive by that date and no other. Pinned in Task 3 (`test_archives_on_reconciled_completed_date_whatever_its_source`).
2. A transient lot shared by a material on an archived job and a material on a live job must survive. Pinned in Task 3 (`test_shared_transient_lot_survives`).
3. A rejected job (no `start_date`) must produce no `Started` row and tasks all cancelled. Pinned in Task 5 (`test_rejected_archive_rows`).
4. A line-derived task whose line quantity was real keeps `est_qty`; an elapsed-time task's invented `est_qty` is nulled. Pinned in Task 2 (`test_records_invented_est_qty`) and Task 3 (`test_task_quantities`).
5. Two archived jobs in one payload / one fixture with estimate chains: version chains are per `estimate_number`, never confused across jobs. Pinned in Task 1 (`test_two_chains_in_one_payload`).

---

### Task 1: Importer accepts estimate version chains

**Files:**
- Modify: `apps/jobs/archive.py` (`_document_statuses` ~226, `_validate_documents` 373-424, `_create_estimates` 592-607)
- Modify: `docs/designs/jobs-and-tasks.md` (§3.8 payload table row `estimates[]`, ~784)
- Modify: `docs/designs/data-constraints.md` (Archived job invariants, estimates bullet ~806)
- Test: `tests/test_archive_import.py` (`DocumentTests`)

**Interfaces:**
- Produces: `estimates[]` rows accept `version` (int ≥ 1, default 1). Rows sharing `estimate_number` form a chain. Errors are path-keyed as today (`estimates[i].version`, `estimates[i].status`, `estimates[i].estimate_number`).

- [ ] **Step 1: Write the failing tests** in `DocumentTests`:

```python
def test_version_chain_creates_superseded_parents(self):
    from apps.estimates.models import Estimate
    created = (timezone.now() - timedelta(days=400)).replace(microsecond=0)
    job = self.create(self.base('OLD-V1', estimates=[
        {'estimate_number': 'EST-V', 'version': 1, 'status': 'superseded',
         'created_date': created, 'lines': [{'description': 'a', 'qty': 1, 'price': 10}]},
        {'estimate_number': 'EST-V', 'version': 2, 'status': 'superseded',
         'created_date': created + timedelta(days=3), 'closed_date': created + timedelta(days=9),
         'lines': [{'description': 'b', 'qty': 1, 'price': 20}]},
        {'estimate_number': 'EST-V', 'version': 3, 'status': 'accepted',
         'created_date': created + timedelta(days=10),
         'lines': [{'description': 'c', 'qty': 1, 'price': 30}]},
    ]))
    v = {e.version: e for e in Estimate.objects.filter(job=job)}
    self.assertEqual(set(v), {1, 2, 3})
    self.assertEqual(v[1].status, Estimate.STATUS_SUPERSEDED)
    self.assertEqual(v[2].status, Estimate.STATUS_SUPERSEDED)
    self.assertEqual(v[3].status, Estimate.STATUS_ACCEPTED)
    self.assertIsNone(v[1].parent)
    self.assertEqual(v[2].parent, v[1])
    self.assertEqual(v[3].parent, v[2])
    # superseded without closed_date defaults to the successor's created_date
    self.assertEqual(v[1].closed_date, v[2].created_date)
    self.assertEqual(v[2].closed_date, created + timedelta(days=9))
    self.assertEqual(v[3].estimatelineitem_set.count(), 1)

def test_version_chain_validation(self):
    def chain(*rows):
        return [{'estimate_number': 'EST-X', **r} for r in rows]
    # non-contiguous
    self.assertErrorKeys(self.base('OLD-V2', estimates=chain(
        {'version': 1, 'status': 'superseded'}, {'version': 3, 'status': 'accepted'})),
        'estimates[1].version')
    # duplicate (number, version)
    self.assertErrorKeys(self.base('OLD-V3', estimates=chain(
        {'version': 1, 'status': 'superseded'}, {'version': 1, 'status': 'accepted'})),
        'estimates[1].estimate_number')
    # lower version not superseded
    self.assertErrorKeys(self.base('OLD-V4', estimates=chain(
        {'version': 1, 'status': 'rejected'}, {'version': 2, 'status': 'accepted'})),
        'estimates[0].status')
    # highest version superseded
    self.assertErrorKeys(self.base('OLD-V5', estimates=chain(
        {'version': 1, 'status': 'superseded'}, {'version': 2, 'status': 'superseded'})),
        'estimates[1].status')
    # a lone version-1 estimate may not be superseded
    self.assertErrorKeys(self.base('OLD-V6', estimates=chain(
        {'version': 1, 'status': 'superseded'})), 'estimates[0].status')
    # bad version values
    self.assertErrorKeys(self.base('OLD-V7', estimates=chain(
        {'version': 0, 'status': 'accepted'})), 'estimates[0].version')
    self.assertErrorKeys(self.base('OLD-V8', estimates=chain(
        {'version': 'two', 'status': 'accepted'})), 'estimates[0].version')
    self.assertEqual(Job.objects.filter(job_number__startswith='OLD-V').count(), 0)

def test_number_taken_at_any_version_is_refused(self):
    from apps.estimates.models import Estimate
    live = Job.objects.create(job_number='LIVE-V', contact=self.contact)
    Estimate.objects.create(job=live, estimate_number='EST-T', version=2)
    self.assertErrorKeys(self.base('OLD-V9', estimates=[
        {'estimate_number': 'EST-T', 'status': 'expired'}]), 'estimates[0].estimate_number')

def test_two_chains_in_one_payload(self):
    from apps.estimates.models import Estimate
    job = self.create(self.base('OLD-V10', estimates=[
        {'estimate_number': 'EST-P', 'version': 1, 'status': 'superseded'},
        {'estimate_number': 'EST-Q', 'version': 1, 'status': 'rejected'},
        {'estimate_number': 'EST-P', 'version': 2, 'status': 'accepted'},
    ]))
    p2 = Estimate.objects.get(job=job, estimate_number='EST-P', version=2)
    self.assertEqual(p2.parent.estimate_number, 'EST-P')
    self.assertIsNone(Estimate.objects.get(job=job, estimate_number='EST-Q').parent)
```

Also, in `test_estimates_created_without_side_effects`, keep the `version == 1` / `parent is None` assertions (rows without `version` default to 1).

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_archive_import --noinput`
Expected: FAIL (`version` ignored, chains rejected as duplicates / `superseded` not allowed).

- [ ] **Step 3: Implement in `apps/jobs/archive.py`**

- `_document_statuses()['estimates']` stays `(accepted, rejected, expired)` as the *settled* set; add a module constant `_SUPERSEDED = Estimate.STATUS_SUPERSEDED` usage inside `_validate_documents`.
- In `_validate_documents`, for `key == 'estimates'`: coerce `version` (`int`, default 1, `≥ 1`, else `estimates[i].version` error); payload duplicate key becomes `(casefolded number, version)`; `taken` becomes `Estimate.objects.filter(estimate_number=n).exists()` (any version). Allowed statuses per row: `superseded` **or** a settled status. After the loop, group rows by casefolded number: versions must be exactly `1..k` (report the first offending row's `estimates[i].version`: "Estimate versions must be contiguous from 1."); every row below the max must be `superseded` (`estimates[i].status`: "Lower versions of an estimate must be superseded."); the max must be settled (`estimates[i].status`: "The latest version of an estimate must be accepted, rejected or expired."). "At most one accepted" unchanged.
- `_create_estimates(job, rows)`: sort rows by `(estimate_number, version)`; create each with `version=row['version']` and `parent=` the previously created row of the same number (chains are contiguous, so the previous row is version − 1); when `status == superseded` and `closed_date` is None, use the successor's `created_date` (coerce the successor's date first; fall back to this row's own `created_date`). Keep "created straight at a settled status" semantics.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test tests.test_archive_import --noinput`
Expected: `OK`.

- [ ] **Step 5: Update the docs**

`jobs-and-tasks.md` §3.8 `estimates[]` row: add `version` to fields; restrictions become "rows sharing `estimate_number` form a chain: versions contiguous from 1, lower versions `superseded` (`parent` set to the previous version; `closed_date` defaults to the successor's `created_date`), highest ∈ {accepted, rejected, expired}; at most one accepted; number unique in the DB at any version and `(number, version)` unique in the payload". `data-constraints.md` estimates bullet: replace "`version = 1`, no parent" with "version chains allowed: lower versions `superseded` with `parent` linked".

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/archive.py tests/test_archive_import.py docs/designs/jobs-and-tasks.md docs/designs/data-constraints.md
git commit -m "feat(archive): importer accepts estimate version chains"
```

---

### Task 2: Converter prep — one run clock, and est_qty provenance

**Files:**
- Modify: `nealsdata/converter/orchestrator.py` (`__init__` 37-73, `convert()` 128-170)
- Modify: `nealsdata/converter/reconcile.py` (`_pass_estimate_version_chains` 76, `_pass_estimate_expiry` 156)
- Modify: `nealsdata/converter/build.py` (`assign_est_quantities` 1457-1483)
- Test: `tests/test_neals_builders.py`

**Interfaces:**
- Produces: `NealsDataConverter(..., now=None)`; attribute `c.now` (aware UTC `datetime`, default `datetime.now(timezone.utc)`). `reconcile` reads `c.now.date()` where it used `date.today()`. `c.invented_est_qty`: `set` of `jobs.task` pks whose `est_qty` was written by `assign_est_quantities` (initialised `set()` in `__init__`).

- [ ] **Step 1: Write the failing tests**

```python
class RunClockTest(unittest.TestCase):
    def test_now_defaults_to_aware_utc_and_is_injectable(self):
        from datetime import datetime, timezone as tz
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        self.assertIsNotNone(c.now.tzinfo)
        fixed = datetime(2030, 1, 15, tzinfo=tz.utc)
        self.assertEqual(NealsDataConverter('/dev/null', '/dev/null',
                                            output_path='/tmp/x.json', now=fixed).now, fixed)

    def test_expiry_uses_run_clock(self):
        # An open estimate created 2029-12-01 is expired when now=2030-01-15
        # (45 days later) and NOT expired when now=2029-12-20.
        ...  # build c.estimates / fixture rows the way ReconcileTest does; call reconcile.reconcile(c)


class EstQtyProvenanceTest(unittest.TestCase):
    def test_records_invented_est_qty(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.add_fixture('jobs.task', 1, {'qty_source': 'elapsed_time', 'est_qty': None,
                                       'est_worker_time': '02:00:00'})
        c.add_fixture('jobs.task', 2, {'qty_source': 'entered_qty', 'est_qty': '4.00',
                                       'est_worker_time': '02:00:00'})
        c.add_fixture('jobs.task', 3, {'qty_source': 'entered_qty', 'est_qty': None,
                                       'est_worker_time': '02:00:00'})
        build.assign_est_quantities(c)
        self.assertEqual(c.invented_est_qty, {1, 3})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_neals_builders.RunClockTest tests.test_neals_builders.EstQtyProvenanceTest --noinput`
Expected: FAIL (`now` unexpected kwarg; no `invented_est_qty`).

- [ ] **Step 3: Implement**

`orchestrator.py`: `__init__(..., now=None)` sets `self.now = now or datetime.now(timezone.utc)` and `self.invented_est_qty = set()`. `reconcile.py`: both passes use `c.now.date()`. `build.assign_est_quantities`: `c.invented_est_qty.add(f['pk'])` on each branch that writes `est_qty`.

- [ ] **Step 4: Run to verify they pass, plus the existing reconcile tests**

Run: `python manage.py test tests.test_neals_builders --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/orchestrator.py nealsdata/converter/reconcile.py nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "refactor(nealsdata): one run clock; record invented est_qty"
```

---

### Task 3: The archive pass

**Files:**
- Modify: `nealsdata/converter/build.py` (new `archive_old_jobs` after `assign_project_managers` ~1446; constants near `_TERMINAL_JOB_STATUSES` 2760)
- Modify: `nealsdata/converter/orchestrator.py` (`__init__`: `self.archived_job_pks = set()`, `self.archived_outcome = {}`)
- Test: `tests/test_neals_builders.py` (new `ArchiveOldJobsTest`, dataset-free, in the `FakeShipmentSynthesisTest` style)

**Interfaces:**
- Consumes: `c.now`, `c.invented_est_qty`, `c.jobs[base_ref]['card']`, `P.has_pickup_done(card)`.
- Produces: `archive_old_jobs(c, cutoff)` where `cutoff` is an aware datetime; mutates `c.fixture_data`; sets `c.archived_job_pks` (set of job pks) and `c.archived_outcome` (`{job_pk: 'completed' | 'rejected' | 'cancelled'}`). Module constant `_ARCHIVE_AFTER_MONTHS = 6` and helper `archive_cutoff(now)` returning `now - relativedelta(months=_ARCHIVE_AFTER_MONTHS)`.

- [ ] **Step 1: Write the failing tests** (`ArchiveOldJobsTest`; helpers `_add_job(c, status, completed_date, checklist='')`, `_add_task(c, job_pk, **over)`, `_add_material(c, job_pk, inventory_item, **over)`, `_add_lot(c)` emitting `inventory.inventoryitem` with `code='LOT-x'`, `_add_deliverable`, `_add_source(c, li_pk, source_type, source_pk)`, `_add_invoice(c, job_pk, status, qbo_amount_paid)`; `CUTOFF = datetime(2026, 4, 21, tzinfo=utc)`):

```python
def test_archives_completed_and_rejected_at_or_before_cutoff(self):
    # completed 2026-04-21 (== cutoff) → archived; rejected 2025-12-01 → archived;
    # completed 2026-04-22 → stays completed; work_complete (no date) → stays;
    # in_progress → stays.
    ...
    self.assertEqual(c.archived_job_pks, {old_completed, old_rejected})
    self.assertEqual(c.archived_outcome, {old_completed: 'completed', old_rejected: 'rejected'})
    self.assertEqual(job(old_completed)['status'], 'archived')
    self.assertEqual(job(old_completed)['project_manager'], None)
    self.assertEqual(job(old_completed)['completed_date'], '2026-04-21T00:00:00+00:00')  # kept

def test_archives_on_reconciled_completed_date_whatever_its_source(self):
    # Only completed_date is consulted — a job with no card 'Archived at' but a
    # completed_date before the cutoff archives; a job with a card 'Archived at'
    # older than the cutoff but completed_date None (work_complete) does not.
    ...

def test_task_quantities(self):
    # three tasks on an archived job: elapsed_time with invented est_qty (pk in
    # c.invented_est_qty) → est_qty None; entered_qty with line est_qty '4.00'
    # (not in the set) → kept '4.00'; all: qty_source 'entered_qty',
    # est_worker_time/actual_qty/assignee/worker_queue None, source_scheme None,
    # active_modifiers [], service_item None, rate/unit_label/accounting_category
    # unchanged, status unchanged.
    ...

def test_materials_and_lots(self):
    # material A on archived job → inventory_item kept (real PLI: code 'MDF.75'),
    # consumption_state 'consumed', cost_source 'imported', released_qty '0.00',
    # po_line_item None, unit_cost/quantity/units/task unchanged.
    # material B on archived job → its LOT-* item referenced by nobody else:
    # inventory_item None and the inventoryitem row removed.
    ...

def test_shared_transient_lot_survives(self):
    # LOT-* referenced by a material on an archived job AND a material on a live
    # job: the archived material unlinks, the row stays, the live link stays.
    ...

def test_deliverables_sources_and_invoices(self):
    # deliverables on the archived job removed (incl. a 'Fake Deliverable', and
    # c.fake_deliverable_count decremented by 1); every estimatelineitemsource
    # whose (source_type, source_pk) is one of the job's tasks/materials removed;
    # invoices: qbo_amount_paid None, qbo_id None, qbo_payment_status '';
    # status/dates unchanged. Rows of a live job untouched.
    ...

def test_cutoff_helper(self):
    self.assertEqual(build.archive_cutoff(datetime(2026, 10, 21, 12, tzinfo=utc)),
                     datetime(2026, 4, 21, 12, tzinfo=utc))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_neals_builders.ArchiveOldJobsTest --noinput`
Expected: FAIL (`archive_old_jobs` not defined).

- [ ] **Step 3: Implement `archive_old_jobs(c, cutoff)` and `archive_cutoff(now)` in `build.py`**

Selection: for each `jobs.job` fixture with `status in ('completed', 'rejected', 'cancelled')` and `_aware(completed_date) is not None and <= cutoff`. Then per archived job, in this order: job fields (`status='archived'`, `project_manager=None`); tasks (nulls per the test; `qty_source='entered_qty'`); materials (per the test; collect lot pks to check); invoices (QBO fields); remove rows: `deliverables.deliverable` of the job (decrement `c.fake_deliverable_count` per `'Fake Deliverable'` removed), `estimates.estimatelineitemsource` whose `(source_type, source_pk)` ∈ the job's task/material pks. After all jobs: remove each candidate `inventory.inventoryitem` with `code.startswith('LOT-')` that no remaining `inventory.material` references. Rebuild `c.fixture_data` once as a filtered list (do not mutate while iterating). Populate `c.archived_job_pks` / `c.archived_outcome`.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test tests.test_neals_builders.ArchiveOldJobsTest --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py nealsdata/converter/orchestrator.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): archive_old_jobs pass — old completed/rejected jobs become archived"
```

---

### Task 4: Wire the pass and make every later builder skip archived jobs

**Files:**
- Modify: `nealsdata/converter/orchestrator.py` (`convert()` after `reconcile.reconcile(self)`; `_print_summary`)
- Modify: `nealsdata/converter/build.py`: `assign_project_managers` 1429, `build_shipments` 2146, `build_bleps_and_shifts` 2387, `assign_current_work` 2540, `build_purchasing` 2770, `build_invoice_line_item_sources` 2045, `build_invoice_agreement_refs` 1977, `build_synthetic_estimate_sources` 1835, `build_checklist_declines` 1905
- Test: `tests/test_neals_builders.py` (new `ArchivedJobsDownstreamSkipTest`)

**Interfaces:**
- Consumes: `c.archived_job_pks`.
- Produces: `convert()` calls `build.archive_old_jobs(self, build.archive_cutoff(self.now))` immediately after reconcile. Verbose summary line: `  {n} jobs archived (completed/rejected on or before {cutoff:%Y-%m-%d})`.

- [ ] **Step 1: Write the failing tests** — one method per builder, each building the minimal synthetic state that builder would otherwise act on (copy the shape from that builder's existing test class: `FakeShipmentSynthesisTest`, `BlepShiftSynthesisTest`, `AssignCurrentWorkTest`, `PurchasingBuilderTest`'s synthetic parts, `InvoiceLineItemSourceWiringTest`, `InvoiceAgreementRefsTest`, `SyntheticEstimateSourcesTest`, `ProjectManagerAssignmentTest`), with the job's pk in `c.archived_job_pks` and `status='archived'`, asserting the builder emits/changes nothing for it while a twin live job is handled as before:

```python
def test_project_manager_skips_archived(self): ...
def test_shipments_skip_archived(self): ...          # even with a pickup marker
def test_bleps_skip_archived(self): ...              # complete task, no blep, no actual_qty
def test_current_work_skips_archived(self): ...
def test_purchasing_skips_archived(self): ...        # no earmark/PO/QOH/qty_sold change
def test_invoice_sources_skip_archived(self): ...
def test_agreement_refs_skip_archived(self): ...
def test_synthetic_sources_skip_archived(self): ...
def test_checklist_declines_skip_archived(self): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_neals_builders.ArchivedJobsDownstreamSkipTest --noinput`
Expected: FAIL on each (builder acts on the archived job).

- [ ] **Step 3: Implement** — each builder reads `archived = getattr(c, 'archived_job_pks', set())` and `continue`s on an archived job pk at its per-job (or per-task/material/invoice by `fields['job']`) loop head, with a one-line comment `# archived jobs carry only translated data (spec §6)`. Wire the orchestrator and the summary line.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test tests.test_neals_builders --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py nealsdata/converter/orchestrator.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): run archive pass after reconcile; downstream builders skip archived jobs"
```

---

### Task 5: History rows for archived jobs

**Files:**
- Modify: `nealsdata/converter/build.py` (`build_history` 2977-3058)
- Test: `tests/test_neals_builders.py` (new `ArchivedJobHistoryTest`, in the `BuildHistoryUnitTest` style)

**Interfaces:**
- Consumes: `c.archived_job_pks`, `c.archived_outcome`, `c.now`, `c.jobs[...]['card']`.
- Produces: for an archived job, `build_history` emits exactly: one `audit` `{'_created': True}` row per job/task/material/estimate/invoice at `c.now.isoformat()`; action rows on the job `Created`@`created_date`, `Started`@`start_date` (if set), outcome@`completed_date` (`Completed`/`Rejected`/`Cancelled`), `Imported from Kanban`@`c.now`; and, when `P.has_pickup_done(card)`, a `note` row at `completed_date` with `text='Picked up/Delivered (Kanban checklist)'`. All `user=None`. No rows of any other kind for that job's objects.

- [ ] **Step 1: Write the failing tests**

```python
def test_completed_archive_rows(self):
    # job 1 archived (outcome completed, start_date set, checklist '[X] Picked up/Delivered'),
    # with task 2, material 4, estimate 3, invoice 7 → rows:
    # audits for ('job',1),('task',2),('material',4),('estimate',3),('invoice',7) at c.now;
    # actions Created/Started/Completed/Imported from Kanban at the stated dates;
    # one note row. assertEqual on the full sorted list of
    # (entry_type, object_type, object_id, changes, text, timestamp).

def test_rejected_archive_rows(self):
    # start_date None, no marker → no Started row, no note; outcome 'Rejected'.

def test_live_jobs_unchanged(self):
    # a live job in the same fixture still gets the causal timeline (reuse a
    # BuildHistoryUnitTest assertion).
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_neals_builders.ArchivedJobHistoryTest --noinput`
Expected: FAIL (archived job gets the causal timeline).

- [ ] **Step 3: Implement** — in `build_history`'s per-job loop, branch on `job_pk in archived` to a new helper `_archived_job_history(c, job_pk, job_fields, related, emit)` that emits the rows above (audit rows before action rows; action rows in the order listed; note last).

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test tests.test_neals_builders --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): importer-shaped history rows for archived jobs"
```

---

### Task 6: End-to-end, fixture regeneration, importer parity

**Files:**
- Modify: `tests/test_neals_builders.py` (`ConvertEndToEndTest`)
- Modify: `tests/test_neals_fixture.py` (`test_fixture_loads_into_test_db` deliverable assertion)
- Create: `tests/test_neals_archive_parity.py`
- Regenerate: `nealsdata/datasets/converted.json` (git-ignored) via `python nealsdata/convert_neals_data.py --verbose`

**Interfaces:**
- Consumes: Tasks 1-5.

- [ ] **Step 1: Write the failing end-to-end test** in `ConvertEndToEndTest`:

```python
def test_archive_rule_holds_end_to_end(self):
    from datetime import datetime, timezone as tz
    fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd); self.addCleanup(os.unlink, path)
    now = datetime(2030, 1, 1, tzinfo=tz.utc)   # far future: every closed job is old
    c = NealsDataConverter(XLSX, CSV, output_path=path, limit=40, now=now)
    c.convert()
    cutoff = build.archive_cutoff(now)
    jobs = [f for f in c.fixture_data if f['model'] == 'jobs.job']
    archived = {f['pk'] for f in jobs if f['fields']['status'] == 'archived'}
    self.assertEqual(archived, c.archived_job_pks)
    self.assertGreater(len(archived), 0)
    closed = ('completed', 'rejected', 'cancelled')
    for f in jobs:
        st = f['fields']['status']
        cd = build._aware(f['fields'].get('completed_date'))
        if st == 'archived':
            # archived ⇒ it was an old closed job
            self.assertIn(c.archived_outcome[f['pk']], closed)
            self.assertIsNotNone(cd); self.assertLessEqual(cd, cutoff)
        elif st in closed:
            # a closed job left live ⇒ it is younger than the cutoff
            self.assertTrue(cd is None or cd > cutoff, f['fields']['job_number'])
    # nothing invented survives on an archive
    for f in c.fixture_data:
        if f['model'] in ('deliverables.deliverable', 'deliverables.shipment', 'jobs.blep',
                          'inventory.earmark', 'purchasing.purchaseorderlineitem'):
            self.assertNotIn(f['fields'].get('job'), archived, f['model'])
```

- [ ] **Step 2: Update `tests/test_neals_fixture.py`** — the "every Job with a non-draft estimate has a Deliverable" loop excludes `est.job.status == Job.STATUS_ARCHIVED`; add `test_archived_jobs_present_and_valid`: `Job.objects.filter(status=Job.STATUS_ARCHIVED).exists()` is true and `validate_data` output contains no line starting with `Archived job` and no `non-terminal task` line mentioning `archived`.

- [ ] **Step 3: Write the parity test** `tests/test_neals_archive_parity.py` (Django `TestCase`, `skipUnless` `converted.json` exists):

```python
FIXTURE = 'nealsdata/datasets/converted.json'
EXCLUDE_TS_ACTIONS = {'Imported from Kanban'}

class ConverterImporterParityTest(TestCase):
    """Every archived job the converter emits must be reproducible, field for
    field, by ArchiveImportService from a payload built off that job
    (spec §2 goals: RM's archive testing on converted data must be valid)."""

    @classmethod
    def setUpTestData(cls):
        call_command('loaddata', FIXTURE, verbosity=0)
        set_history_context(None)

    def _payload_from(self, job):  # -> dict ArchiveImportService accepts
        ...  # header incl. due_date/dates/outcome ('Completed'/'Rejected'/'Cancelled')/source='Kanban';
             # tasks (name, description, sort_order, status, unit_label, rate, est_qty, actual_qty,
             #        est_worker_time, accounting_category, service_item);
             # materials (…, task=index, inventory_item, po_line_item);
             # estimates (number, version, status, dates, lines); invoices (…); shipments [];
             # notes from the job's note rows (text, timestamp). job_number = f'{job.job_number}-P'.

    def _snapshot(self, job):  # -> nested dict, pks replaced by indexes, timestamps normalised
        ...  # job fields minus pk/job_number/accent_color; ordered child lists; estimate parent as
             # index; history as sorted (entry_type, object_type-kind, action/text,
             # timestamp-or-None for audits and EXCLUDE_TS_ACTIONS)

    def test_every_archived_job_round_trips_through_the_importer(self):
        archived = list(Job.objects.filter(status=Job.STATUS_ARCHIVED).order_by('pk'))
        self.assertGreater(len(archived), 0)
        for job in archived:
            twin = ArchiveImportService.create_archived_job(self._payload_from(job), user=None)
            self.assertEqual(self._snapshot(job), self._snapshot(twin), job.job_number)
```

The snapshot must cover: Job (`name, description, customer_po_number, due_date, created_date, start_date, completed_date, project_manager_id, status, on_hold`), Task (`name, description, sort_order, status, qty_source, unit_label, rate, est_qty, actual_qty, est_worker_time, accounting_category_id, service_item_id, source_scheme_id, active_modifiers, assignee_id, worker_queue, blocked_reason, parent_task_id`), Material (`description, quantity, units, unit_cost, sell_price, accounting_category_id, inventory_item_id, po_line_item_id, task→index, consumption_state, released_qty, cost_source`), Estimate (`estimate_number, version, status, parent→index, created_date, sent_date, closed_date, expiration_date`, lines `description, qty, units, price, accounting_category_id, is_comment, line_number`), Invoice (`invoice_number, status, created_date, sent_date, closed_date, qbo_id, qbo_payment_status, qbo_amount_paid`, lines as above), counts of deliverables / shipments / bleps / earmarks / `EstimateLineItemSource` / `InvoiceLineItemSource` for the job (all zero), and history rows as described. A mismatch here is a spec violation, not a test to loosen: fix the converter (or, if the payload genuinely cannot carry a translated field RM wants, stop and report).

- [ ] **Step 4: Regenerate the fixture and run everything**

Run: `python nealsdata/convert_neals_data.py --verbose` (note the "jobs archived" line).
Run: `python manage.py test tests.test_neals_builders tests.test_neals_fixture tests.test_neals_archive_parity tests.test_archive_import --noinput`
Expected: `OK`. If `validate_data` reports an archived-job error, fix the converter, regenerate, re-run.

- [ ] **Step 5: Commit**

```bash
git add tests/test_neals_builders.py tests/test_neals_fixture.py tests/test_neals_archive_parity.py
git commit -m "test(nealsdata): archive rule end-to-end, fixture load, converter/importer parity"
```

---

### Task 7: Converter documentation

**Files:**
- Modify: `nealsdata/convert.md` (§2 running, §3 pipeline list, new §4 subsection "Archived jobs", §5 note on clock, §9 fake data, §10 tests)
- Modify: `docs/designs/jobs-and-tasks.md` §3.8 (one paragraph: the nealsdata converter is a second producer of archived jobs; parity test)

- [ ] **Step 1: Write** — §3: insert step `11a. archive_old_jobs` after reconcile with the rule and the cutoff clock; §4 "Archived jobs": the §4 table of the spec in prose (what is kept, what is stripped, history rows, parity with the importer and why RM chose drop-over-extend); §2: the output is no longer byte-stable across days (clock cutoff) and what that means for tests; §9: new bullet "Archived jobs carry no invented data" and remove the stale `jobs.fee` claims (there is no Fee model; fixed-charge lines stay plain document lines); §10: the new test classes and `test_neals_archive_parity`. In `jobs-and-tasks.md` §3.8 add the converter paragraph with a pointer to `nealsdata/convert.md`.

- [ ] **Step 2: Commit**

```bash
git add nealsdata/convert.md docs/designs/jobs-and-tasks.md
git commit -m "docs(nealsdata): archived jobs in the converter; converter is a second archive producer"
```

---

## Self-review notes

- Spec §3.1 rule → Task 3 + Task 6; §3.2 placement → Task 4; §4 table → Task 3 (every row) and Task 4 (skips); §5 history → Task 5; §6 clock, flag, summary → Tasks 2, 4; §7 importer → Task 1; §8 tests → Tasks 1-6 (parity in Task 6); docs → Tasks 1, 7.
- `accent_color` is excluded from the parity snapshot on purpose: both producers assign a palette colour mechanically (round-robin vs least-used) and neither value is payload data.
- Names used across tasks: `archive_old_jobs(c, cutoff)`, `archive_cutoff(now)`, `_ARCHIVE_AFTER_MONTHS`, `c.now`, `c.invented_est_qty`, `c.archived_job_pks`, `c.archived_outcome`, `_archived_job_history(...)`.
