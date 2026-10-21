# Archived Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a terminal, read-only `archived` Job status that an import service can create (with tasks, materials, deliverables, estimates, invoices, shipments and backdated history) in the existing tables, and make archived jobs visible on the customer page, in search and in the customer's rolling-window dollar totals, while keeping them out of every live-work view.

**Architecture:** `archived` is a Job status with no transitions in or out; it joins a new named `CLOSED_STATUSES` grouping so every closed-job rule picks it up. Read-only comes from the existing frozen-job chokepoint gaining an archived check. A new module `apps/jobs/archive.py` writes an archived job with plain ORM `create()` calls inside one transaction, managing the history context itself. Customer totals move to a configurable rolling window; archived labor is the sum of hour-unit task actuals. The SPA gets a `jobStatus.js` twin of the groupings, an archived banner, a Delete button (archived only, two-phase), the window labels and an archive caveat.

**Tech Stack:** Django 5.2 / DRF / MySQL, Svelte 5 (runes) + Vite + Vitest, Playwright.

**Spec:** `docs/plans/2026-10-20-archived-jobs-design.md` — section numbers below (§) refer to it.

**Branch:** `feature/archival-jobs` (already exists; every commit lands here).

## Global Constraints

- Never write to the dev database: no `migrate`, no `manage.py shell` writes, no `loaddata`, no DB-mutating scripts. Verify behaviour with tests only. `makemigrations` is fine.
- Run Django tests one process at a time, in the foreground, always with `--noinput`, never piped (read the `OK`/`FAILED` summary line). Targeted modules per task; the full suite (without `--keepdb`, since migrations change) once at the end.
- `python manage.py test --noinput tests.test_x` is the invocation shape. Vitest: `cd frontend && npm run test:run -- <file>`. E2E: `cd e2e && npx playwright test <spec>`.
- Status values come from model constants (`Job.STATUS_ARCHIVED`), never string literals, in Python. The frontend uses the string `'archived'` only inside `lib/jobStatus.js` and status-keyed CSS/labels.
- Error shapes: `ValidationError({'field': ['msg']})` for input problems, `ValidationError('sentence')` otherwise; views do not catch to re-render. Field paths in the import service are `tasks[2].rate`-style strings.
- Every DELETE response is 200 with a JSON body.
- No live-job rule gains an "unless archived" clause (§2 anti-goal). Archived is excluded from live rules by status membership, never by exemption.
- Never call `QuerySet.update()` / `bulk_create` on models whose `save()` has side effects; never `.delete()` a line item directly (cascade from the parent is fine).
- Copy fixed strings exactly as given here: guard message `"Cannot {action}: this job is archived. Archived jobs are a historical record and cannot be changed."`; banner text `Archived: this job was imported as a historical record and cannot be changed.`; caveat `Includes archived jobs — imported labor may be incomplete.`; status label `Archived`; Configuration key `customer_financials_window_months`, default `12`; list param `exclude_archived`; material cost source `imported` labelled `Imported`.
- Commit after each task with a conventional-commit message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never merge, push or open a PR.

## Review Focus

Inputs the spec implies but names no test for; each is pinned to a task below.

1. **An archived job whose material references a PO line is deleted.** `Material.po_line_item` is `SET_NULL` from the material side, so the cascade must succeed and the PO line must survive. → Task 7.
2. **An import that fails validation after some rows were valid writes nothing, including history.** The `_created` audits are queued on the history context; a rollback must not leave them behind. → Task 8a.
3. **A closed job whose `completed_date` is exactly on the window cutoff** counts as in-window (`>=`), and a closed job with `completed_date = None` is out even when `created_date` is recent. → Task 6.
4. **The board's Closed lane renders an archived card** (`ClosedCard` gets status `archived`): label `Archived`, no crash on missing sub-fields. → Task 9.
5. **An expense already attributed to a live job is re-attributed to an archived job via PATCH** — refused with the archived sentence, and the material move does not happen. → Task 4.

---

### Task 1: `archived` status and the named groupings on `Job`

**Files:**
- Modify: `apps/jobs/models.py:74-92` (constants + choices), `:145-154` (`VALID_TRANSITIONS` inside `clean`)
- Create: `apps/jobs/migrations/0002_job_status_archived.py` (via `makemigrations`)
- Test: `tests/test_archived_job_status.py` (new)

**Interfaces:**
- Produces: `Job.STATUS_ARCHIVED = 'archived'`; `Job.PRE_APPROVAL_STATUSES`, `Job.CLOSED_STATUSES`, `Job.WORK_FROZEN_STATUSES` (all `frozenset` of status strings, defined as class attributes right after the status constants).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_archived_job_status.py
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from apps.core.models import User
from apps.jobs.models import Job
from tests.base import BaseTestCase
from tests.test_contacts_status import make_business, make_job


class ArchivedStatusModelTest(TestCase):
    def setUp(self):
        _, self.contact, _ = make_business('ArcCo', n_contacts=1)

    def test_archived_is_a_choice(self):
        self.assertIn(('archived', 'Archived'), Job.JOB_STATUS_CHOICES)
        self.assertEqual(Job.STATUS_ARCHIVED, 'archived')

    def test_groupings_membership(self):
        self.assertEqual(Job.PRE_APPROVAL_STATUSES, frozenset({'draft', 'submitted'}))
        self.assertEqual(Job.CLOSED_STATUSES, frozenset({'completed', 'rejected', 'cancelled', 'archived'}))
        self.assertEqual(Job.WORK_FROZEN_STATUSES, Job.CLOSED_STATUSES | {'work_complete'})

    def test_create_at_archived_with_explicit_dates_is_allowed(self):
        from django.utils import timezone
        when = timezone.now()
        job = Job.objects.create(job_number='ARC-1', contact=self.contact,
                                 status=Job.STATUS_ARCHIVED, start_date=when, completed_date=when)
        job.refresh_from_db()
        self.assertEqual(job.status, 'archived')
        self.assertEqual(job.completed_date, when)

    def test_no_transition_into_archived(self):
        for status in (Job.STATUS_DRAFT, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED):
            job = make_job(self.contact, status)
            job.status = Job.STATUS_ARCHIVED
            with self.assertRaises(ValidationError):
                job.save()

    def test_no_transition_out_of_archived(self):
        job = Job.objects.create(job_number='ARC-2', contact=self.contact, status=Job.STATUS_ARCHIVED)
        for status in (Job.STATUS_DRAFT, Job.STATUS_IN_PROGRESS, Job.STATUS_COMPLETED):
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()


class ArchivedStatusAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        _, self.contact, _ = make_business('ArcApi', n_contacts=1)

    def test_patch_to_archived_is_refused(self):
        job = make_job(self.contact, Job.STATUS_COMPLETED)
        r = self.client.patch(f'/api/jobs/{job.pk}/', {'status': 'archived'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_status_actions_refused_on_archived(self):
        job = Job.objects.create(job_number='ARC-3', contact=self.contact, status=Job.STATUS_ARCHIVED)
        for action in ('complete', 'cancel', 'reopen'):
            r = self.client.post(f'/api/jobs/{job.pk}/{action}/', {}, format='json')
            self.assertEqual(r.status_code, 400, (action, r.data))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_archived_job_status`
Expected: FAIL — `AttributeError: type object 'Job' has no attribute 'STATUS_ARCHIVED'` / `PRE_APPROVAL_STATUSES`.

- [ ] **Step 3: Add the status, choices and groupings**

In `apps/jobs/models.py` after `STATUS_CANCELLED` (line 81) add `STATUS_ARCHIVED = 'archived'`; append `(STATUS_ARCHIVED, 'Archived')` to `JOB_STATUS_CHOICES`; then define the three `frozenset` class attributes with a comment pointing at spec §3.2 (archived ∈ CLOSED; WORK_FROZEN = CLOSED | {work_complete}). In `clean()`'s `VALID_TRANSITIONS` add `Job.STATUS_ARCHIVED: [],  # terminal; set only by ArchiveImportService` and add nothing to any other status's list.

- [ ] **Step 4: Make the migration**

Run: `python manage.py makemigrations jobs -n job_status_archived`
Expected: one `AlterField` on `job.status` in `apps/jobs/migrations/0002_job_status_archived.py`.

- [ ] **Step 5: Run tests**

Run: `python manage.py test --noinput tests.test_archived_job_status tests.test_state_transitions tests.test_jobs_models`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/0002_job_status_archived.py tests/test_archived_job_status.py
git commit -m "feat(jobs): add terminal archived status and named status groupings"
```

---

### Task 2: Replace hard-coded closed / pre-approval sets with the groupings

**Files:**
- Modify (closed → `Job.CLOSED_STATUSES`): `apps/api/jobs/views.py:173-175`; `apps/jobs/financials.py:283`; `apps/core/services.py:587-597` (`FINAL_STATUSES['job']`); `apps/jobs/services.py:1429-1430` (`delete_task`), `:2168-2171` (`get_board_data` closed lane), `:2390-2393` (`get_closed_data`)
- Modify (pre-approval → `Job.PRE_APPROVAL_STATUSES`): `apps/jobs/services.py:2447`; `apps/schedule/services.py:612`; `apps/inventory/services.py:498`, `:595`, `:1013`; `apps/estimates/services.py:81`
- Modify (work-frozen → `Job.WORK_FROZEN_STATUSES`): `apps/core/management/commands/validate_data.py:895` (`check_earmark_job_status`)
- Modify: `apps/api/jobs/views.py` `get_queryset` — new `?exclude_archived=true` param
- Test: `tests/test_archived_job_visibility.py` (new)

**Interfaces:**
- Consumes: Task 1 groupings.
- Produces: `GET /api/jobs/?exclude_archived=true` drops only archived jobs.

Leave bespoke sets alone (spec §3.2 list; `apps/contacts/services.py:_open_statuses`, `validate_data.py` date checks at 203-218, `estimates/signals.py`, board pipeline/in-progress/unpaid, schedule work-active, `BILLABLE_JOB_STATUSES`, `_EARMARK_RELEASING_STATUSES`, blep allow-list, hold gates). The `in_progress_column_jobs` and schedule `work_active_job_statuses` lists include `in_progress`; they are allow-lists and stay as written.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_archived_job_visibility.py
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import User, Configuration
from apps.jobs.models import Job
from apps.jobs.services import BoardService
from apps.jobs.financials import compute_customer_financials
from apps.contacts.services import ContactService
from tests.base import BaseTestCase
from tests.test_contacts_status import make_business, make_job


def archived_job(contact, number, completed_days_ago=3):
    when = timezone.now() - timedelta(days=completed_days_ago)
    return Job.objects.create(job_number=number, contact=contact, status=Job.STATUS_ARCHIVED,
                              created_date=when, start_date=when, completed_date=when)


class ArchivedVisibilityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        _, self.contact, _ = make_business('VisCo', n_contacts=1)
        self.archived = archived_job(self.contact, 'ARC-V1')
        self.live = make_job(self.contact, Job.STATUS_APPROVED)
        self.done = make_job(self.contact, Job.STATUS_COMPLETED)

    def _ids(self, url):
        return {j['job_id'] for j in self.client.get(url).data['results']}

    def test_open_filter_excludes_archived_and_plain_list_includes_it(self):
        self.assertNotIn(self.archived.pk, self._ids('/api/jobs/?open=true&page_size=100'))
        self.assertIn(self.archived.pk, self._ids('/api/jobs/?page_size=100'))

    def test_exclude_archived_drops_only_archived(self):
        ids = self._ids('/api/jobs/?exclude_archived=true&page_size=100')
        self.assertNotIn(self.archived.pk, ids)
        self.assertIn(self.live.pk, ids)
        self.assertIn(self.done.pk, ids)

    def test_open_jobs_count_excludes_archived(self):
        rollup = compute_customer_financials(self.contact.job_set.all())
        self.assertEqual(rollup['open_jobs'], 1)

    def test_board_closed_lane_includes_recent_archive_and_other_lanes_never_do(self):
        Configuration.objects.update_or_create(key='board_closed_retention_days', defaults={'value': '14'})
        data = BoardService.get_board_data()          # keys: 'pipeline', 'approved' {'jobs', …}, 'closed'
        ids = lambda rows: {j['job_id'] for j in rows}
        self.assertIn(self.archived.pk, ids(data['closed']))
        self.assertIn(self.archived.pk, ids(BoardService.get_closed_data()['jobs']))
        self.assertNotIn(self.archived.pk, ids(data['pipeline']))
        self.assertNotIn(self.archived.pk, ids(data['approved']['jobs']))
        self.assertNotIn(self.archived.pk, ids(BoardService.get_unpaid_data()['jobs']))

    def test_contact_with_only_archived_jobs_can_be_deactivated(self):
        _, c, _ = make_business('OnlyArc', n_contacts=1)
        archived_job(c, 'ARC-V2')
        self.assertEqual(ContactService.contact_deactivation_blockers(c), [])
```

Add to `tests/test_cleanup_temp_emails_command.py`, next to `test_linked_active_job_kept_even_if_email_old`: `test_linked_archived_job_counts_as_final` — an old email linked to an archived job is cleaned up exactly as one linked to a completed job.

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_archived_job_visibility tests.test_cleanup_temp_emails_command`
Expected: FAIL — `?exclude_archived` is ignored today (archived job still listed) and the board's Closed lane omits the archived job (its hard-coded list has no `archived`).

- [ ] **Step 3: Replace the sets and add the list param**

At each listed site replace the literal list/set with the grouping attribute (`status__in=Job.CLOSED_STATUSES`, `job.status in Job.PRE_APPROVAL_STATUSES`, …). In `JobViewSet.get_queryset` after the `open` block: `if self.request.query_params.get('exclude_archived') == 'true': qs = qs.exclude(status=Job.STATUS_ARCHIVED)`. `BoardService` closed-lane queries now include archived automatically; `get_board_data`'s other lanes are allow-lists and need no change.

- [ ] **Step 4: Run tests**

Run: `python manage.py test --noinput tests.test_archived_job_visibility tests.test_cleanup_temp_emails_command tests.test_board_service tests.test_api_jobs tests.test_job_financials tests.test_task_delete_guards tests.test_validate_data tests.test_api_schedule tests.test_inventory_services tests.test_estimates_services tests.test_contacts_status`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add -A apps tests
git commit -m "refactor(jobs): route closed/pre-approval status checks through Job groupings; add ?exclude_archived"
```

---

### Task 3: Validator rules for archived jobs

**Files:**
- Modify: `apps/core/management/commands/validate_data.py` — `check_job_work_complete_gate` (:917-925), `check_shipments` (:680-699), new `check_archived_jobs`
- Test: `tests/test_validate_data.py` (`ValidateDataStateInvariantsTest`, :423)

**Interfaces:**
- Consumes: Task 1.

- [ ] **Step 1: Write the failing tests** (same `call_command('validate_data', stdout=out)` shape as `test_invoice_on_draft_job_is_an_error`)

- `test_archived_job_without_dates_is_clean` — archived job, no `start_date`/`completed_date`: no error or warning mentioning it.
- `test_archived_job_with_pending_task_is_an_error` — archived job + `Task(status='pending')`: an error line naming the job.
- `test_archived_job_with_open_invoice_is_an_error` — archived job + `Invoice(status='open', invoice_number='ARC-I1')`: error; the same job with a `paid` and a `cancelled` invoice: clean.
- `test_archived_shipment_without_accepted_estimate_is_not_a_warning` — archived job + deliverable + picked-up shipment, no estimate: no warning; a live approved job with the same shape still warns.

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_validate_data`
Expected: FAIL on the pending-task, open-invoice and shipment-warning tests.

- [ ] **Step 3: Implement**

- `check_job_work_complete_gate`: `closed = (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_ARCHIVED)`.
- `check_shipments`: skip the accepted-estimate warning when `s.job.status == Job.STATUS_ARCHIVED` (select the job status in the queryset; do not add a per-row query).
- New `check_archived_jobs(self)`: for every `Invoice` whose job is archived and whose status is not in `(Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED)`, append an error `f'Archived job {job.job_number}: invoice {invoice.display_number} is {invoice.status}; archived invoices must be paid or cancelled'`. Register it where the other `check_*` methods are called.
- `check_jobs` date checks already omit archived (every set is explicit); add a one-line comment there saying so and why (§3.8).

- [ ] **Step 4: Run tests**

Run: `python manage.py test --noinput tests.test_validate_data`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/core/management/commands/validate_data.py tests/test_validate_data.py
git commit -m "feat(validate_data): archived-job invariants (terminal tasks, settled invoices, no estimate warning)"
```

---

### Task 4: The archived guard, and the expense side door

**Files:**
- Modify: `apps/jobs/services.py:186-199` (`_assert_job_not_frozen`), new `_assert_job_not_archived` just above it
- Modify: `apps/expenses/services.py` `submit` (job resolved by :95, before `Expense(...)` at :97) and `update` (:138-146)
- Test: `tests/test_archived_job_guard.py` (new); `tests/test_expense_service.py`

**Interfaces:**
- Produces: `_assert_job_not_archived(job, action)` in `apps/jobs/services.py` (module-level, importable by `apps/expenses/services.py`); `_assert_job_not_frozen` calls it first.

- [ ] **Step 1: Write the failing guard tests**

`tests/test_archived_job_guard.py` mirrors `tests/test_api_inactive_party_freeze.py` (`JobFreezeTest`, `DocumentFreezeTest`, `DocumentFreezeBypassAndFunnelTest`): same client setup, but the job is `Job.objects.create(job_number='ARC-G1', contact=..., status=Job.STATUS_ARCHIVED)` with one task `Task.objects.create(job=job, name='T', status=Task.STATUS_COMPLETE, qty_source=Task.QTY_ENTERED)`, and the contact stays active. `ARCHIVED = 'is archived'`. Copy every request those three classes make (header PATCH, hold, notes, task create/edit/delete/complete, blep start, material create, estimate create, deliverable create, shipment create, invoice create, wizard start) and assert `400` with `ARCHIVED` in `detail`. Add:

- `test_assert_mutable_raises` — `JobService.assert_mutable(job)` raises `ValidationError` whose message contains `ARCHIVED`.
- `test_duplicate_still_works` — `JobService.duplicate_job(job, contact=job.contact, path='draft')` returns a new draft job.
- `test_email_link_and_unlink_work` — `POST /api/emails/{pk}/link-to-job/ {job_id}` → 200 with `job == job.pk`; `GET /api/emails/?job={pk}` lists it; unlink → 200 (reuse `test_api_email.py`'s email setup).
- `test_contact_swap_carve_out_does_not_apply` — PATCH `{'contact': <same-business sibling pk>}` → 400 `ARCHIVED`.

- [ ] **Step 2: Write the failing expense tests** in `tests/test_expense_service.py` (use its `_expense(...)` helper at :342):

- `test_submit_to_archived_job_is_refused` — `ExpenseService.submit(..., job=archived)` raises `ValidationError` containing `is archived`.
- `test_submit_to_completed_job_still_allowed`.
- `test_update_reattributing_to_archived_job_is_refused` — expense on a live job with a linked material; `ExpenseService.update(expense=e, actor=u, job=archived)` raises; the material's `job` is unchanged (Review Focus 5).

- [ ] **Step 3: Run to verify failure**

Run: `python manage.py test --noinput tests.test_archived_job_guard tests.test_expense_service`
Expected: FAIL — mutations return 200/201 on the archived job; expense submit succeeds.

- [ ] **Step 4: Implement**

```python
def _assert_job_not_archived(job, action):
    if job.status == Job.STATUS_ARCHIVED:
        raise ValidationError(
            f"Cannot {action}: this job is archived. Archived jobs are a "
            f"historical record and cannot be changed."
        )
```
First line of `_assert_job_not_frozen` becomes `_assert_job_not_archived(job, action)`. In `ExpenseService.submit`, once `job` is final (after :95): `if job is not None: _assert_job_not_archived(job, 'attribute an expense to this job')`. In `update`, when `'job' in fields and fields['job'] is not None`, the same check before any `setattr` (so the material move at :144 never runs). Import lazily inside the functions to avoid an import cycle if one appears.

- [ ] **Step 5: Run tests**

Run: `python manage.py test --noinput tests.test_archived_job_guard tests.test_expense_service tests.test_api_inactive_party_freeze tests.test_api_expenses tests.test_api_email`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py apps/expenses/services.py tests/test_archived_job_guard.py tests/test_expense_service.py
git commit -m "feat(jobs): archived jobs are read-only via the frozen-job guard; expenses cannot attach to them"
```

---

### Task 5: `Material.cost_source = 'imported'` and the duplicate mapping

**Files:**
- Modify: `apps/inventory/models.py:265-276`
- Create: `apps/inventory/migrations/0003_material_cost_source_imported.py` (via `makemigrations`)
- Modify: `apps/jobs/services.py:1111-1138` (`_copy_work_to_job`)
- Modify: `frontend/src/lib/materialStatus.js` only if it switches on every `cost_source` value (builder checks; today it tests `customer_supplied` and `estimated` only, so no change expected)
- Test: `tests/test_material_cost_source.py`, `tests/test_job_duplication.py`

**Interfaces:**
- Produces: `Material.COST_SOURCE_IMPORTED = 'imported'` (choice label `Imported`).

- [ ] **Step 1: Write the failing tests**

- `tests/test_material_cost_source.py`: `test_imported_is_a_choice_and_does_not_mint` — `MaterialService.create_on_job(job=approved_job, description='Ply', quantity=1, unit_cost=Decimal('5.00'), cost_source=Material.COST_SOURCE_IMPORTED, accounting_category=ac)` creates a material with `inventory_item is None` and `InventoryItem.objects.count()` unchanged.
- `tests/test_job_duplication.py` (`DuplicateJobTestBase`): `test_duplicating_archived_job_maps_imported_cost_to_estimated_without_minting` — source job at `STATUS_ARCHIVED` with a `Material(cost_source='imported', unit_cost=5, inventory_item=None, consumption_state='consumed')`; after `duplicate_job(..., path='draft')` the copy has `cost_source == 'estimated'`, `consumption_state == 'pending'`, and `InventoryItem` count is unchanged; a source material with `cost_source='po'` copies through as `po` (existing behaviour, assert it in the same test).

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_material_cost_source tests.test_job_duplication`
Expected: FAIL — `AttributeError: COST_SOURCE_IMPORTED`.

- [ ] **Step 3: Implement**

Add the constant and `(COST_SOURCE_IMPORTED, 'Imported')` to `COST_SOURCE_CHOICES`. In `_copy_work_to_job`, before `MaterialService.create_on_job(...)`: `fields = material.copy_fields(); if fields.get('cost_source') == Material.COST_SOURCE_IMPORTED: fields['cost_source'] = Material.COST_SOURCE_ESTIMATED` and splat `fields`. The mint gate (`inventory/services.py:748-752`) already excludes `imported`; do not touch it.

- [ ] **Step 4: Make the migration and run tests**

Run: `python manage.py makemigrations inventory -n material_cost_source_imported`
Run: `python manage.py test --noinput tests.test_material_cost_source tests.test_job_duplication tests.test_mint_service tests.test_material_service_create`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations/0003_material_cost_source_imported.py apps/jobs/services.py tests/test_material_cost_source.py tests/test_job_duplication.py
git commit -m "feat(inventory): 'imported' material cost source; duplicate maps it to estimated"
```

---

### Task 6: Archived labor, the rolling window, and the settings key

**Files:**
- Modify: `apps/jobs/financials.py` — new `_labor_hours`, `load_customer_financials_window_months`, `spend_breakdown` (:132-133), `compute_customer_financials` (:256-309)
- Modify: `apps/api/contacts/views.py:31-41` (`_financials_payload`)
- Modify: `apps/api/templates_config/views.py:260-268` (add a block for the new key)
- Modify: `fixtures/unit_test_data.json` (add a `core.configuration` row `customer_financials_window_months` = `"12"` next to `board_closed_retention_days` at :263); `fixtures/playwright/seed.json` (same, next to :1622)
- Test: `tests/test_job_financials.py`, `tests/test_api_contacts.py` (`CustomerFinancialsAPITest`, :217), `tests/test_api_templates_config.py`

**Interfaces:**
- Produces: `_labor_hours(job) -> Decimal`; `load_customer_financials_window_months() -> int` (default 12, `max(1, n)`, same shape as `apps/activity/services.py:load_recent_days`); `compute_customer_financials(jobs, *, now=None)` returning the existing keys plus `window_months: int` and `includes_archived: bool`; `/api/contacts/{id}/financials/` and `/api/businesses/{id}/financials/` payloads gain those two keys.

- [ ] **Step 1: Write the failing labor tests** in `tests/test_job_financials.py` (seed `average_labor_cost` = `'50.00'` as `test_includes_labor_at_average_cost` does):

- `test_archived_hour_tasks_are_labor` — archived job, tasks: (`unit_label='hour'`, `actual_qty=10`, complete), (`unit_label='hour'`, `actual_qty=2`, cancelled), (`unit_label='ea'`, `actual_qty=40`), (`unit_label='min'`, `actual_qty=90`); `spend_breakdown(job)['labor_hours'] == Decimal('12')`, `['labor'] == Decimal('600.00')`.
- `test_archived_without_hour_tasks_has_zero_labor`.
- `test_live_entered_hour_task_is_not_labor` — approved job, `Task(qty_source='entered_qty', unit_label='hour', actual_qty=8)`, no bleps → `labor_hours == 0`.
- `test_live_bleps_unchanged` — existing blep-based expectation still holds (reuse the existing test's fixture).

- [ ] **Step 2: Write the failing window tests** in `tests/test_api_contacts.py` `CustomerFinancialsAPITest` (call `compute_customer_financials(jobs, now=fixed)` directly for the rule, and the endpoint once for the payload keys). Use `fixed = timezone.now()` and `completed_date` offsets of `relativedelta(months=...)` from `dateutil`:

- `test_open_job_always_in_window` — approved job completed-date null, in.
- `test_closed_job_inside_window_in_and_outside_out` — completed at `fixed − 11 months` in; at `fixed − 13 months` out.
- `test_closed_job_on_the_cutoff_is_in` — `completed_date == fixed − 12 months` exactly → in (Review Focus 3).
- `test_closed_job_with_null_completed_date_is_out` — archived, `completed_date=None`, recent `created_date` → out.
- `test_window_config_override_and_default` — `Configuration customer_financials_window_months='3'` → a job completed 4 months ago is out and `window_months == 3`; with the key deleted → `window_months == 12`; with value `'abc'` → 12.
- `test_archived_in_window_counts_toward_invoiced_and_profit_and_sets_flag` — archived job with a paid invoice line (qty 1 × 1000) and an hour task (10 h at labor cost 50): `invoiced` includes 1000, `profit` includes 500, `includes_archived is True`; the same archived job completed 13 months ago: excluded from both and `includes_archived is False`.
- `test_open_jobs_and_outstanding_ignore_the_window` — a 13-month-old open invoice on a live job still counts in `outstanding`.
- `test_financials_endpoint_exposes_window_and_flag` — `GET /api/contacts/{id}/financials/` has `window_months` (int) and `includes_archived` (bool).

- [ ] **Step 3: Write the failing settings test** in `tests/test_api_templates_config.py`: PATCH `{'customer_financials_window_months': 0}` → 400 with that key; `'abc'` → 400; `'6'` → 200 and GET shows `'6'`.

- [ ] **Step 4: Run to verify failure**

Run: `python manage.py test --noinput tests.test_job_financials tests.test_api_contacts tests.test_api_templates_config`
Expected: FAIL — `labor_hours` is 0 on the archived job; `compute_customer_financials()` got an unexpected keyword `now`; settings PATCH accepts 0.

- [ ] **Step 5: Implement**

```python
def _labor_hours(job):
    hours = _blep_hours(job)
    if job.status == Job.STATUS_ARCHIVED:
        hours += sum((t.actual_qty or Decimal('0')) for t in job.tasks.all() if t.unit_label == HOUR_UNIT)
    return hours
```
(`HOUR_UNIT` from `apps.core.units`; `job.tasks` is the related name.) `spend_breakdown` calls `_labor_hours`. `compute_customer_financials(jobs, *, now=None)`: `now = now or timezone.now()`, `months = load_customer_financials_window_months()`, `cutoff = now - relativedelta(months=months)`; `in_window(j) = j.status not in Job.CLOSED_STATUSES or (j.completed_date is not None and j.completed_date >= cutoff)`; sum `invoiced`/`profit` over `[j for j in jobs if in_window(j)]`; `includes_archived = any(j.status == Job.STATUS_ARCHIVED for j in windowed)`; leave `open_jobs`, `outstanding`, `first_job_date`, `last_job_start` over all jobs; return the two new keys. `_financials_payload` passes them through unchanged. Settings view: copy the `activity_recent_days` block for the new key with message `'must be an integer >= 1'`.

- [ ] **Step 6: Run tests**

Run: `python manage.py test --noinput tests.test_job_financials tests.test_api_contacts tests.test_api_templates_config tests.test_job_overview_endpoint tests.test_average_labor_cost_settings`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/financials.py apps/api/contacts/views.py apps/api/templates_config/views.py fixtures/unit_test_data.json fixtures/playwright/seed.json tests/test_job_financials.py tests/test_api_contacts.py tests/test_api_templates_config.py
git commit -m "feat(financials): archived labor from hour-unit tasks; customer totals over a configurable rolling window"
```

---

### Task 7: Two-phase job delete, archived short-circuit and history purge

**Files:**
- Modify: `apps/jobs/services.py:813-845` (`assert_job_deletable`), new `JobService.job_deletion_impact`, `JobService.delete_job`
- Modify: `apps/api/jobs/views.py:93` (class bases), `:125-135` (`destroy`)
- Test: `tests/test_deletion_guards.py` (`JobDeletionGuardTests`, :237), `tests/test_api_jobs.py` (`test_delete_job`, :182)

**Interfaces:**
- Consumes: `ConfirmDeleteMixin` (`apps/api/mixins.py:49-79`: hooks `get_deletion_impact(obj)` and `perform_confirmed_destroy(obj)`), `CanManageJobs` (`apps/api/permissions.py:14`).
- Produces: `JobService.job_deletion_impact(job) -> dict` with int keys `tasks, materials, deliverables, shipments, estimates, invoices, history_rows`; `JobService.delete_job(job) -> None`; `DELETE /api/jobs/{id}/` → `{'confirm_required': True, 'impact': {...}}`, then with `?confirm=true` → `{'message': 'Job deleted.'}`; 403 for an archived job when the caller lacks the `can_manage_jobs` atom.

- [ ] **Step 1: Write the failing service tests** in `tests/test_deletion_guards.py`:

- `test_archived_job_with_history_deletes_and_purges_history` — archived job + task + consumed material whose `po_line_item` points at a real PO line (Review Focus 1) + accepted estimate + paid invoice (with a line) + deliverable + picked-up shipment; `JobService.delete_job(job)`; the job, children and every `JobHistory` row with those `(object_type, object_id)` pairs are gone; the PO line still exists.
- `test_same_shape_at_completed_is_refused` — same children on a completed job → `ValidationError` from `assert_job_deletable`.
- `test_live_draft_delete_leaves_its_history` — draft job with one `JobHistory` row; `delete_job` leaves the row.
- `test_impact_counts` — `job_deletion_impact(job)` on the archived fixture returns the exact counts.

- [ ] **Step 2: Write the failing API tests** in `tests/test_api_jobs.py`:

- Rewrite `test_delete_job`: first DELETE → 200 with `confirm_required True` and `impact` dict; job still exists; `?confirm=true` → 200 with `message`; job gone.
- `test_pm_only_user_cannot_delete_archived_but_can_delete_own_draft` — PM user pattern from `tests/test_pm_job_access.py:19-29`; archived job with `project_manager=pm` → DELETE 403; draft job with `project_manager=pm` → two-phase delete succeeds.
- `test_atom_user_can_delete_archived` — `grant_atoms(user, 'can_manage_jobs')` → two-phase succeeds.

- [ ] **Step 3: Run to verify failure**

Run: `python manage.py test --noinput tests.test_deletion_guards tests.test_api_jobs`
Expected: FAIL — `AttributeError: delete_job`; first DELETE deletes outright.

- [ ] **Step 4: Implement**

- `assert_job_deletable`: first line `if job.status == Job.STATUS_ARCHIVED: return`.
- `job_deletion_impact(job)`: counts via the related managers; `history_rows` = the size of the purge set below (0 for a live job).
- `delete_job(job)`: `assert_job_deletable(job)`; inside `transaction.atomic()`: if archived, collect `keys = {'job': [job.pk], 'task': [...], 'material': [...], 'estimate': [...], 'invoice': [...], 'deliverable': [...], 'shipment': [...]}` from the related querysets, then `job.delete()`, then for each type `JobHistory.objects.filter(object_type=t, object_id__in=ids).delete()` (`JobHistory` has no custom `delete`; builder confirms before using the queryset delete); otherwise just `job.delete()`.
- `JobViewSet`: replace `JSONDestroyMixin` with `ConfirmDeleteMixin` in the bases, drop `destroy_response_message`. Override `destroy(self, request, *a, **kw)`: `job = self.get_object()`; `if job.status == Job.STATUS_ARCHIVED and not CanManageJobs().has_permission(request, self): raise PermissionDenied('Only a user who can manage jobs may delete an archived job.')`; `JobService.assert_job_deletable(job)` (so the refusal comes before the confirm round-trip, as today); then `return super().destroy(request, *a, **kw)`. `get_deletion_impact` → `JobService.job_deletion_impact(job)`; `perform_confirmed_destroy` → `JobService.delete_job(job)` and `Response({'message': 'Job deleted.'})`.

- [ ] **Step 5: Run tests**

Run: `python manage.py test --noinput tests.test_deletion_guards tests.test_api_jobs tests.test_pm_job_access tests.test_api_mixins`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py apps/api/jobs/views.py tests/test_deletion_guards.py tests/test_api_jobs.py
git commit -m "feat(jobs): two-phase job delete; archived jobs delete with their history, atom-gated"
```

---

### Task 8a: `ArchiveImportService` — header, tasks, deliverables, materials, history

**Files:**
- Create: `apps/jobs/archive.py`
- Test: `tests/test_archive_import.py` (new)

**Interfaces:**
- Consumes: Tasks 1, 5; `record_history` / `HistoryContext` / `set_history_context` / `get_history_context` (`apps/core/history.py`).
- Produces:

```python
class ArchiveImportService:
    @staticmethod
    def create_archived_job(payload: dict, *, user=None) -> Job
```
Payload (every key optional unless marked): `job_number`* (str ≤ 50), `contact`* (Contact pk; may be inactive), `name`, `description`, `customer_po_number`, `project_manager` (User pk), `created_date`, `start_date`, `due_date`, `completed_date` (ISO datetimes or `datetime`s), `outcome` (str), `source` (str), `notes` (list of `{text*, timestamp?, user?}`), `tasks`, `deliverables`, `materials` (this task), `estimates`, `invoices`, `shipments` (Task 8b).
- `tasks[i]`: `name`*, `description`, `sort_order`, `status` ∈ {`complete`, `cancelled`} (default `complete`), `unit_label` (default `'none'`), `rate`, `est_qty`, `actual_qty`, `est_worker_time` (seconds or ISO duration), `accounting_category` (pk), `service_item` (pk). Always `qty_source='entered_qty'`.
- `deliverables[i]`: `description`*, `qty_ordered`* (> 0), `units` (default `'none'`), `sort_order`.
- `materials[i]`: `description`, `quantity`, `units`, `unit_cost`, `sell_price`, `accounting_category` (pk; required unless `inventory_item` is given), `inventory_item` (pk), `task` (int index into `tasks`), `po_line_item` (pk). Always `consumption_state='consumed'`, `released_qty=0`, `cost_source='imported'`.
- Errors: one `ValidationError(dict)` collecting every problem found before any write, keyed by path (`'job_number'`, `'contact'`, `'tasks[2].status'`, `'materials[0].task'`, …); messages are sentences.
- Internal shape (names are binding so Task 8b extends them): `_validate(payload) -> dict` (errors), `_coerce_dt(value, path, errors)`, `_create_job(payload, user)`, `_create_tasks(job, rows) -> list[Task]`, `_create_deliverables(job, rows) -> list[Deliverable]`, `_create_materials(job, rows, tasks)`, `_write_history(job, payload, user, ctx)`, `_flush_history(ctx, user)`.

- [ ] **Step 1: Write the failing tests** (`tests/test_archive_import.py`, `TestCase`, a `make_business` contact, one `AccountingCategory`):

- `test_minimal_payload_creates_archived_job` — `{'job_number': 'OLD-1', 'contact': c.pk}` → job at `archived`, `name == ''`, `created_date` ≈ now, `start_date`/`completed_date` None; one `JobHistory` audit row `_created` for the job with `user == user`, plus exactly two `action` rows: `Created` (at `created_date`) and `Imported`; no `Started` or outcome row.
- `test_inactive_contact_is_allowed` — deactivated contact → success.
- `test_missing_required_and_unknown_contact` — `{}` → errors for `job_number` and `contact`; unknown contact pk → `{'contact': [...]}`.
- `test_duplicate_job_number_is_a_field_error` — existing live job number → `{'job_number': [...]}`; nothing created.
- `test_header_fields_and_dates_land_as_given` — all header fields incl. `project_manager`, three dates 2 years back → stored verbatim; `Job.save` did not restamp them.
- `test_tasks_are_terminal_entered_quantity` — two tasks (one `cancelled`, one with `unit_label='hour'`, `actual_qty=12.5`) → `qty_source == 'entered_qty'`, statuses as given, `sort_order` ascending in payload order when omitted (`Task.save` assigns it), `get_actual_qty() == Decimal('12.50')`; task `status='pending'` → `{'tasks[0].status': [...]}`.
- `test_deliverables_and_materials` — deliverable with `qty_ordered=0` → `{'deliverables[0].qty_ordered': [...]}`; material with `task=5` on a 1-task payload → `{'materials[0].task': [...]}`; valid material → `consumption_state == 'consumed'`, `cost_source == 'imported'`, `task` linked, `Earmark.objects.count()` unchanged, `InventoryItem.qty_on_hand` unchanged when `inventory_item` given, `po_line_item` stored when given.
- `test_backdated_history_and_notes` — `created_date`, `start_date`, `completed_date` set, `outcome='Completed in Fishbowl'`, `source='Fishbowl'`, two notes (one with `timestamp` and `user`) → `JobHistory` `action` rows: `Created` at `created_date`, `Started` at `start_date`, `Completed in Fishbowl` at `completed_date`, `Imported from Fishbowl` at ≈ now; `note` rows at their timestamps with the given / default user; the `_created` audits exist for the job and each task/material/deliverable and carry `user`.
- `test_failure_after_valid_rows_writes_nothing` — payload with two valid tasks and a third with `status='pending'` → `ValidationError`; `Job`, `Task` and `JobHistory` counts unchanged (Review Focus 2).
- `test_history_context_is_restored` — set a sentinel context before the call (`set_history_context(HistoryContext())`); after success and after failure `get_history_context()` is that same object.

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_archive_import`
Expected: FAIL — `ModuleNotFoundError: apps.jobs.archive`.

- [ ] **Step 3: Implement `apps/jobs/archive.py`**

`create_archived_job`: `errors = _validate(payload)`; `if errors: raise ValidationError(errors)`; then

```python
prev = get_history_context()
ctx = HistoryContext(user=user)
set_history_context(ctx)
try:
    with transaction.atomic():
        job = _create_job(...); tasks = _create_tasks(...); dels = _create_deliverables(...)
        _create_materials(...)            # 8b adds estimates / invoices / shipments here
        _flush_history(ctx, user)         # inside atomic so a rollback discards them
        _write_history(job, payload, user)
finally:
    set_history_context(prev)
return job
```
`_flush_history` is the body of `HistoryMiddleware._flush_pending` (`apps/core/middleware.py:26-50`) with `user` passed in, then `ctx.pending.clear()`. `_validate` resolves every pk with `Model.objects.filter(pk=...).first()` and reports `'Unknown contact 42.'`-style messages; checks `job_number` uniqueness against `Job.objects.filter(job_number=...)`; coerces dates with `django.utils.dateparse.parse_datetime` (make naive values aware with the current timezone). `_create_job` uses `Job.objects.create(status=Job.STATUS_ARCHIVED, ...)` with the dates passed explicitly. `_write_history` uses `record_history(object_type='job', entry_type='action', object_id=job.pk, user=user, changes={'_action': text}, timestamp=when)` for `Created`/`Started`/outcome (outcome row text = `payload.get('outcome') or 'Closed'`, only when `completed_date` is given) and `Imported from {source}` / `Imported` at now; notes use `entry_type='note'`, `text=`, `user=` (default `user`), `timestamp=`.

- [ ] **Step 4: Run tests**

Run: `python manage.py test --noinput tests.test_archive_import tests.test_history_decorator`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/archive.py tests/test_archive_import.py
git commit -m "feat(jobs): ArchiveImportService creates an archived job with tasks, deliverables, materials and backdated history"
```

---

### Task 8b: `ArchiveImportService` — estimates, invoices, shipments

**Files:**
- Modify: `apps/jobs/archive.py`
- Test: `tests/test_archive_import.py`

**Interfaces:**
- Consumes: Task 8a internals.
- Produces payload sections:
  - `estimates[i]`: `estimate_number`*, `status`* ∈ {`accepted`, `rejected`, `expired`}, `created_date`, `sent_date`, `closed_date`, `expiration_date`, `lines` (list of `{description, qty, units, price, accounting_category (pk), is_comment}`). `version=1`, `parent=None`, no `EstimateLineItemSource`. At most one `accepted`.
  - `invoices[i]`: `invoice_number`*, `status`* ∈ {`paid`, `cancelled`}, `created_date`, `sent_date`, `closed_date` (defaults to `created_date` when `paid`), `lines` as above. No `InvoiceLineItemSource`; `qbo_*` left null/blank.
  - `shipments[i]`: `status` (only `picked_up`, default), `picked_up_date`*, `prepared_date` (defaults to `picked_up_date`), `notes`, `items`* (list of `{deliverable (index), qty (> 0)}`). `sequence = i + 1`.
- Validation additions: `estimate_number` + `version=1` unique DB-wide (`Estimate.objects.filter(estimate_number=..., version=1)`), duplicates within the payload too; `invoice_number` required and unique (`Invoice.objects.filter(invoice_number=...)` + within payload); more than one `accepted` → `{'estimates': ['At most one accepted estimate.']}`; shipment `deliverable` index range; per-deliverable shipped total ≤ `qty_ordered` → `{'shipments[i].items[j].qty': [...]}`; comment lines must have zero `qty`/`price`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_archive_import.py`):

- `test_estimates_created_without_side_effects` — one `accepted` (two lines, one comment) and one `rejected`; `version == 1`, `public_token` set, `EstimateLineItemSource.objects.count()` unchanged, job still `archived`, no `Earmark`, line numbers 1..n; `status='draft'` → `{'estimates[0].status': [...]}`; two `accepted` → `{'estimates': [...]}`.
- `test_estimate_number_collision` — existing estimate with the same number at version 1 → `{'estimates[0].estimate_number': [...]}`; two payload estimates sharing a number → the second is reported.
- `test_invoices_created_settled` — `paid` with `closed_date` defaulting to `created_date`, and `cancelled`; `display_number == invoice_number`; `InvoiceLineItemSource.objects.count()` unchanged; `status='open'` → `{'invoices[0].status': [...]}`; missing `invoice_number` → `{'invoices[0].invoice_number': [...]}`; duplicate of an existing number → field error (Review Focus 2 shape: nothing written).
- `test_shipments_picked_up_with_items` — two deliverables, two shipments; sequences 1 and 2; `prepared_date == picked_up_date` when omitted; `status='prepared'` → field error; missing `picked_up_date` → field error; items summing above `qty_ordered` → `{'shipments[1].items[0].qty': [...]}`; `deliverable=9` → `{'shipments[0].items[0].deliverable': [...]}`.
- `test_full_payload_round_trip` — every section populated; `compute_job_financials(job)['invoiced']` equals the paid invoice's lines; `spend_breakdown(job)['labor_hours']` equals the hour task's `actual_qty`; `JobService.duplicate_job(job, contact=job.contact, path='draft')` copies tasks/materials/deliverables and no estimates, invoices or shipments.

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test --noinput tests.test_archive_import`
Expected: FAIL — unknown sections are ignored, so the estimate/invoice/shipment assertions fail on count 0.

- [ ] **Step 3: Implement**

Add `_create_estimates(job, rows)`, `_create_invoices(job, rows)`, `_create_shipments(job, rows, deliverables)` and the matching `_validate` branches. Line items: `EstimateLineItem.objects.create(estimate=est, line_number=n, description=, qty=, units=, price=, accounting_category_id=, is_comment=)` (same for `InvoiceLineItem(invoice=...)`); `BaseLineItem.save` runs `full_clean`, so a comment line's qty/price must already be zero (validated). Estimates run `full_clean` on save; invoices run only `clean()`, so the number uniqueness relies on the pre-check. Shipments: `Shipment.objects.create(job=job, sequence=i+1, status=Shipment.STATUS_PICKED_UP, prepared_date=..., picked_up_date=..., notes=...)` then `ShipmentItem.objects.create(shipment=s, deliverable=deliverables[idx], qty=...)`.

- [ ] **Step 4: Run tests**

Run: `python manage.py test --noinput tests.test_archive_import tests.test_estimate_job_signals tests.test_invoice_closed_date tests.test_shipment_models`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/archive.py tests/test_archive_import.py
git commit -m "feat(jobs): ArchiveImportService imports settled estimates, invoices and shipments"
```

---

### Task 8c: `import_archived_job` management command (dev convenience — RM may strike)

*Addition beyond the spec's §4 "no endpoint in this project": without it there is no way to put an archived job in the dev database for browser review. It is a thin wrapper, no new behaviour.*

**Files:**
- Create: `apps/jobs/management/commands/import_archived_job.py`
- Test: `tests/test_import_archived_job_command.py` (new)

**Interfaces:**
- Consumes: Task 8b.
- Produces: `python manage.py import_archived_job <path.json> [--user <username>]` — reads one payload (or a JSON list of payloads), calls `create_archived_job` per payload, prints `Imported <job_number> (pk <id>)` per success; on `ValidationError` prints `<path>: <field>: <msg>` lines to stderr and exits 1 **without importing any later payload**. `--user` defaults to the first superuser.

- [ ] **Step 1: Write the failing tests** — `call_command('import_archived_job', tmp_path)` with a two-payload file creates two archived jobs and prints both numbers; a file whose second payload is invalid creates the first job, prints the field error and raises `CommandError`.
- [ ] **Step 2: Run to verify failure** — `python manage.py test --noinput tests.test_import_archived_job_command` → FAIL `Unknown command`.
- [ ] **Step 3: Implement** — `BaseCommand` with `add_arguments(path, --user)`, `handle` loops payloads, raising `CommandError` after the first failure.
- [ ] **Step 4: Run tests** — same command, expected `OK`.
- [ ] **Step 5: Commit** — `git commit -m "feat(jobs): import_archived_job management command"`.

---

### Task 9: Frontend status plumbing (`jobStatus.js` and its consumers)

**Files:**
- Create: `frontend/src/lib/jobStatus.js`
- Modify: `frontend/src/lib/customerActivity.js:10-14`; `frontend/src/lib/jobOverview.js:277-282, :508`; `frontend/src/components/jobs/JobHeader.svelte:44-64, :100-102`; `frontend/src/components/tasks/TasksPanel.svelte:111-113`; `frontend/src/routes/jobs/TaskDetailPage.svelte:82-84`; `frontend/src/css/app.css:197-201`; `frontend/src/routes/Search.svelte:43-51`; `frontend/src/components/board/ClosedCard.svelte:14-25`; `frontend/src/components/board/JobCard.svelte:31`; `frontend/src/components/JobPicker.svelte:7-11`; `frontend/src/components/expenses/ExpenseForm.svelte:231`; `e2e/specs/contacts/_customer.js:9`
- Test: `frontend/tests/lib/jobStatus.test.js` (new), `frontend/tests/components/board/ClosedCard.test.js` (new), plus `lib/jobOverview.test.js`, `lib/customerActivity.test.js`, `components/jobs/JobHeader.test.js`, `components/JobPicker.test.js`, `routes/Search.test.js`, `components/board/JobCard.test.js`, `components/tasks/TasksPanel.test.js`

**Interfaces:**
- Produces `frontend/src/lib/jobStatus.js`:

```js
export const PRE_APPROVAL_JOB_STATUSES = new Set(['draft', 'submitted']);
export const CLOSED_JOB_STATUSES = new Set(['completed', 'rejected', 'cancelled', 'archived']);
export const WORK_FROZEN_JOB_STATUSES = new Set([...CLOSED_JOB_STATUSES, 'work_complete']);
export const isPreApprovalJob = (status) => PRE_APPROVAL_JOB_STATUSES.has(status);
export const isClosedJob = (status) => CLOSED_JOB_STATUSES.has(status);
export const isWorkFrozenJob = (status) => WORK_FROZEN_JOB_STATUSES.has(status);
export const JOB_STATUS_LABELS = { draft: 'Draft', submitted: 'Submitted', approved: 'Approved', in_progress: 'In Progress', work_complete: 'Work Complete', rejected: 'Rejected', completed: 'Completed', cancelled: 'Cancelled', archived: 'Archived' };
export const jobStatusLabel = (status) => JOB_STATUS_LABELS[status] ?? status;
```
- `customerActivity.js` keeps exporting `isClosedJob(row)` (row-taking) and delegates to the status version. `JobPicker` gains `excludeArchived = false` → appends `&exclude_archived=true`.

- [ ] **Step 1: Write the failing tests**

- `jobStatus.test.js`: the three sets' exact membership; `isClosedJob('archived') === true`; `jobStatusLabel('archived') === 'Archived'`; `jobStatusLabel('xyz') === 'xyz'`.
- `jobOverview.test.js`: `workBlock` and `spendBlock` return `state: 'frozen'` for `status: 'archived'`.
- `customerActivity.test.js`: an `archived` row sorts into the closed split.
- `JobHeader.test.js`: for `{status: 'archived', can_manage: true}` the pill text is `Archived`, there is no `<select>`, no `Edit`, and `Duplicate…` is present.
- `JobPicker.test.js`: `excludeArchived: true` → the GET URL contains `&exclude_archived=true`; default → it does not.
- `Search.test.js`: the job-status select has an `Archived` option.
- `ClosedCard.test.js` (new): render `{ job_id: 1, job_number: 'OLD-1', name: 'x', status: 'archived', contact_name: 'C', billed: '0.00', spent: '0.00', profit: '0.00' }` → label `Archived`, no throw (Review Focus 4). `JobCard.test.js`: `status: 'archived'` with a `completed_date` → label `Archived`.
- `TasksPanel.test.js`: archived job → the add-task control is absent (same assertion the completed case uses).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/lib/jobStatus.test.js tests/lib/jobOverview.test.js tests/lib/customerActivity.test.js tests/components/jobs/JobHeader.test.js tests/components/JobPicker.test.js tests/routes/Search.test.js tests/components/board`
Expected: FAIL — module not found; archived not frozen/closed.

- [ ] **Step 3: Implement**

Create `jobStatus.js` as above. Replace the private constants: `customerActivity.js` → `import { isClosedJob as isClosedStatus }`; `jobOverview.js` → `PRE_APPROVAL_JOB_STATUSES`/`WORK_FROZEN_JOB_STATUSES`/`TERMINAL_JOB_STATUSES` become the imported sets (keep the local `WORK_DONE_JOB_STATUSES`, it is bespoke; `.includes(status)` becomes `.has(status)`); `JobHeader.svelte` → `VALID_TRANSITIONS.archived = []`, `STATUS_LABELS` replaced by the import, `isTerminal = $derived(isClosedJob(job.status))`; `TasksPanel.svelte` and `TaskDetailPage.svelte` `jobLocked` → `isClosedJob(job.status)`. `app.css`: add `.status-archived { background: #e5e7eb; color: #4b5563; }` after `.status-cancelled`. `Search.svelte`: append `{ value: 'archived', label: 'Archived' }`. `ClosedCard.svelte`: `borderColor` archived → `'#9ca3af'`, `statusLabel` archived → `'Archived'`; `JobCard.svelte:31` add the archived branch. `JobPicker.svelte`: new prop and query fragment; `ExpenseForm.svelte:231` passes `excludeArchived`. `e2e/specs/contacts/_customer.js:9` adds `'archived'`.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm run test:run`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests e2e/specs/contacts/_customer.js
git commit -m "feat(frontend): jobStatus groupings; archived status in header, pickers, search, board cards"
```

---

### Task 10: The archived job page — banner, Delete…, imported-hours label

**Files:**
- Create: `frontend/src/components/jobs/ArchivedJobBanner.svelte`
- Modify: `frontend/src/components/jobs/JobHeader.svelte:248-259` (banner slot, action buttons), new delete state + modal; `frontend/src/lib/jobOverview.js:548`
- Test: `frontend/tests/components/jobs/ArchivedJobBanner.test.js` (new), `components/jobs/JobHeader.test.js`, `lib/jobOverview.test.js` / `components/jobs/overview/SpendBlock.test.js`

**Interfaces:**
- Consumes: `canManageJobs` from `frontend/src/stores/permissions.js:23`; `Modal` props (`open, onSave, onCancel, busy, maxWidth, label`); the two-phase pattern in `routes/contacts/ContactDetailPage.svelte:86-112, :183-194`; `DELETE /api/jobs/{id}/` from Task 7.
- Produces: `ArchivedJobBanner.svelte` (no props) rendering `<div class="archived-banner" role="status"><strong>Archived:</strong> <span>this job was imported as a historical record and cannot be changed.</span></div>` with `FrozenPartyBanner`'s box styling in grey (`#f3f4f6` / `#d1d5db` / `#374151`).

- [ ] **Step 1: Write the failing tests**

- `ArchivedJobBanner.test.js`: renders the exact sentence inside `role="status"`.
- `JobHeader.test.js`:
  - archived job → banner present; `contact_is_active: false` on an archived job → archived banner, **not** `Frozen:`.
  - archived + `user.set({ permissions: ['can_manage_jobs'] })` → `Delete…` button; archived + `permissions: []` with `can_manage: true` (PM-only) → no `Delete…`; completed job with the atom → no `Delete…`.
  - click `Delete…` with `api.delete` resolving `{ confirm_required: true, impact: { tasks: 2, materials: 1, deliverables: 1, shipments: 1, estimates: 1, invoices: 1, history_rows: 9 } }` → dialog `Delete job` shows `2 task(s)` … `9 history row(s)`; confirm → `api.delete` called with `/api/jobs/5/?confirm=true` and `push('/contacts/<job.contact>')`.
- `spendBlock`: archived job → the Labor stat `sub` is `12.5 hours (imported)`; live job → `… hours`.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/components/jobs tests/lib/jobOverview.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement**

`JobHeader.svelte`: `{#if job.status === 'archived'}<ArchivedJobBanner />{:else if job.contact_is_active === false}<FrozenPartyBanner … />{/if}`. Action row: after `Duplicate…`, `{#if job.status === 'archived' && $canManageJobs}<button type="button" class="edit-link header-action danger" onclick={requestDelete}>Delete…</button>{/if}`. `requestDelete`/`confirmDelete` copy ContactDetailPage's pair against `/api/jobs/${job.job_id}/`, success → `showSuccess('Job deleted.')` + `push(`/contacts/${job.contact}`)`; errors through `triageError`. Modal `label="Delete job"`, heading `Delete {job.job_number}?`, `This cannot be undone.`, impact `<ul class="impact">` with one `<li>` per key in the order `tasks, materials, deliverables, shipments, estimates, invoices, history_rows` labelled `task(s)`, `material(s)`, `deliverable(s)`, `shipment(s)`, `estimate(s)`, `invoice(s)`, `history row(s)`. `jobOverview.js:548`: `sub: \`${fmtHours(spend.labor_hours)} hours${status === 'archived' ? ' (imported)' : ''}\``.

- [ ] **Step 4: Run tests** — `cd frontend && npm run test:run` → green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat(frontend): archived job banner, atom-gated two-phase Delete, imported-hours label"
```

---

### Task 11: Customer banner window labels and caveat; settings input

**Files:**
- Modify: `frontend/src/components/contacts/CustomerHeader.svelte:60-79`; `frontend/src/components/settings/GeneralSettings.svelte:8, :20, :51-57, :67-68`
- Test: `frontend/tests/components/contacts/CustomerHeader.test.js`, `frontend/tests/components/settings/GeneralSettings.test.js`

**Interfaces:**
- Consumes: `financials.window_months`, `financials.includes_archived` (Task 6).

- [ ] **Step 1: Write the failing tests**

- `CustomerHeader.test.js`: with `FIN = {…, window_months: 12, includes_archived: false}` the labels read `Invoiced (12 mo)` and `Profit (12 mo)` and no caveat is rendered; with `includes_archived: true` a `.ch-caveat` element reads exactly `Includes archived jobs — imported labor may be incomplete.`; with `window_months` absent the labels fall back to `Invoiced` / `Profit`.
- `GeneralSettings.test.js`: the Defaults group has a `Customer totals window` number input (`min="1"`) loaded from `customer_financials_window_months`; saving Defaults PATCHes that key alongside the existing three.

- [ ] **Step 2: Run to verify failure** — `cd frontend && npm run test:run -- tests/components/contacts/CustomerHeader.test.js tests/components/settings/GeneralSettings.test.js` → FAIL.

- [ ] **Step 3: Implement**

`CustomerHeader.svelte`: `const mo = $derived(financials?.window_months); const span = $derived(mo ? \` (${mo} mo)\` : '');` and labels `Invoiced{span}` / `Profit{span}`; under the stat grid `{#if financials?.includes_archived}<p class="ch-caveat">Includes archived jobs — imported labor may be incomplete.</p>{/if}` styled muted and small. `GeneralSettings.svelte`: state var, load line, a `<p>` block copied from `Job Board retention` with label `Customer totals window`, unit `months`, help text `Months of closed jobs counted in a customer's Invoiced and Profit figures.`, and the key added to the Defaults save payload.

- [ ] **Step 4: Run tests** — `cd frontend && npm run test:run` → green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat(frontend): customer totals window labels, archive caveat, settings input"
```

---

### Task 12: E2E — seed an archived job and cover the flows

**Files:**
- Modify: `fixtures/playwright/seed.json` (append rows; keep valid JSON)
- Create: `e2e/specs/archived-jobs/archived-job.spec.js`
- Test: `tests/test_e2e_prepare_seed.py` (must still pass)

**Interfaces:**
- Consumes: personas (`finjobs` has the jobs atom; `worker` is the PM-only case); `apiAs`, `loadBackdrop` (`e2e/fixtures/`); seed contact **82 Hugo Santana** (business 47, emails 8 and 9, completed job 67).

- [ ] **Step 1: Append the seed rows** (copy each model's field shape from an existing row of the same model in `seed.json`; all pks are one past the current max):

| Model | pk | Key fields |
|---|---|---|
| `jobs.job` | 101 | `job_number "OLD-1042"`, `name "Reception desk (imported)"`, `status "archived"`, `contact 82`, `project_manager` = pk of user `schen` (becomes `worker`), `created_date` / `start_date` / `completed_date` = 120 / 110 / 90 days **before** the newest `core.jobhistory` timestamp currently in the file (so prepare_seed's rebase lands `completed_date` ≈ 90 days ago, inside the window), `accent_color` any valid hex |
| `jobs.task` | 525 | `job 101`, `name "Fabrication"`, `status "complete"`, `qty_source "entered_qty"`, `unit_label "hour"`, `actual_qty "12.50"`, `sort_order 1` |
| `jobs.task` | 526 | `job 101`, `name "Install"`, `status "complete"`, `qty_source "entered_qty"`, `unit_label "ea"`, `actual_qty "1.00"`, `sort_order 2` |
| `deliverables.deliverable` | 106 | `job 101`, `description "Reception desk"`, `qty_ordered "1.00"`, `units "ea"`, `sort_order 10` |
| `deliverables.shipment` | 13 | `job 101`, `sequence 1`, `status "picked_up"`, `prepared_date` = `picked_up_date` = `completed_date` |
| `deliverables.shipmentitem` | 13 | `shipment 13`, `deliverable 106`, `qty "1.00"` |
| `invoicing.invoice` | 29 | `job 101`, `invoice_number "OLD-INV-1042"`, `status "paid"`, `created_date` = `sent_date` = `closed_date` = `completed_date` |
| `invoicing.invoicelineitem` | 137 | `invoice 29`, `line_number 1`, `description "Reception desk"`, `qty "1.00"`, `units "ea"`, `price "3200.00"`, `accounting_category` = an existing non-deposit category pk |
| `core.jobhistory` | 1919–1922 | `object_type "job"`, `object_id 101`, `entry_type "action"`, `user` = `jkim`'s pk, `changes {"_action": …}` for `Created` (at created_date), `Started` (start_date), `Completed in previous system` (completed_date), `Imported` (completed_date + 1 day — still older than the current newest history row) |
| `core.configuration` | `customer_financials_window_months` | `value "12"` (already added in Task 6; confirm) |

Run: `python manage.py test --noinput tests.test_e2e_prepare_seed` → `OK`.

- [ ] **Step 2: Write the spec** `e2e/specs/archived-jobs/archived-job.spec.js` (one `test.describe`, serial, `storageState: personas.finjobs`; find the job through `loadBackdrop()` by `job_number === 'OLD-1042'`):

1. **Customer page** — `goto /#/contacts/82`: labels `Invoiced (12 mo)` and `Profit (12 mo)` visible; the caveat sentence visible; the closed list expands to show `OLD-1042` with status `Archived`; click through to the job.
2. **Job page** — banner sentence visible; pill reads `Archived`; no `Edit`, no status `<select>`, no `Put on hold`; `Duplicate…` and `Delete…` visible; Labor stat shows `12.5 hours (imported)` (open the overview spend block); tasks page shows no add-task control.
3. **Search** — `goto /#/search?q=OLD-1042`, filter job status `Archived` → the row is listed.
4. **Email link** — `goto /#/email/8` (`EmailDetailPage`; seed email 8 is on contact 82's completed job 67), open the link-to-job modal (`EmailLinkModal`), pick `OLD-1042`, save; the archived job page's email list (`EmailsBody`) shows it. Unlink afterwards via `apiAs(personas.finjobs).post('/api/emails/8/unlink-from-job/')` so the seed's shape is restored for other specs.
5. **Duplicate** — `Duplicate…` → keep the contact, draft path → lands on a new draft job whose tasks list contains `Fabrication` and `Install`.
6. **PM-only sees no Delete** — a second `test` with `storageState: personas.worker`: `goto` the archived job → `Duplicate…` visible (PM `can_manage`), `Delete…` absent.
7. **Delete (last)** — as `finjobs`: `Delete…` → dialog `Delete job` lists `2 task(s)`; confirm → lands on `/#/contacts/82`; `GET /api/jobs/<id>/` → 404.

Order 7 last; because the DB is rebuilt every run, deleting at the end is safe.

- [ ] **Step 3: Run**

Run: `cd e2e && npx playwright test specs/archived-jobs`
Expected: all steps pass. Then `cd e2e && npx playwright test` (full suite) — expected green apart from the pre-existing `completion.spec` order dependency noted in memory; confirm nothing new fails.

- [ ] **Step 4: Commit**

```bash
git add fixtures/playwright/seed.json e2e/specs/archived-jobs
git commit -m "test(e2e): seeded archived job; customer page, search, banner, email link, duplicate, delete"
```

---

### Task 13: Docs, LATER entry, full verification, cleanup

**Files:**
- Modify: `docs/designs/jobs-and-tasks.md` (new §3.8 "Archived jobs": status, groupings, guard, delete, import service payload summary, labor rule; a line in §3.6 that archived is a valid duplicate source; §3.7 cross-ref), `docs/designs/data-constraints.md` (§1.1 `customer_financials_window_months`; Job status table + `archived`; `Material.cost_source` `imported`; archived invariants: no transitions, tasks terminal, invoices paid/cancelled, estimates settled, shipments picked up), `docs/designs/contacts-and-businesses.md` (financials rollup: window rule, `window_months`, `includes_archived`, labels, caveat), `docs/designs/architecture-and-conventions.md` (status groupings as a convention: use `Job.*_STATUSES` / `lib/jobStatus.js`, never a literal list, for the three recurring sets), `docs/designs/invoicing-and-expenses.md` (expenses cannot attach to archived jobs), `docs/designs/e2e-testing.md` §3 (seed job `OLD-1042`), `docs/designs/LATER.md` (new entry: PO line task picker variant that offers archived tasks, §3.4), `frontend/README.md` (one line: `ArchivedJobBanner` follows the `FrozenPartyBanner` slot)
- Delete: `docs/plans/2026-10-20-archived-jobs-design.md`, `docs/plans/2026-10-20-archived-jobs.md`

- [ ] **Step 1: Update the docs** as listed; keep each addition in the doc's existing voice and section numbering.
- [ ] **Step 2: Full backend suite, fresh DB** — `python manage.py test --noinput` (no `--keepdb`; migrations changed). Expected: `OK` with the `Ran N tests` line read from the output.
- [ ] **Step 3: Full Vitest** — `cd frontend && npm run test:run` → green. **Build** — `cd frontend && npm run build` → succeeds.
- [ ] **Step 4: Commit docs** — `git commit -m "docs: archived jobs (status, groupings, import service, rolling customer window)"`.
- [ ] **Step 5: Delete the plan files and commit** — `git rm docs/plans/2026-10-20-archived-jobs-design.md docs/plans/2026-10-20-archived-jobs.md && git commit -m "chore: remove shipped archived-jobs spec and plan"`.
- [ ] **Step 6: Report** — tell RM the branch `feature/archival-jobs` is ready for browser review, how to create an archived job locally (`import_archived_job` with a sample payload, if Task 8c was kept), and do not merge, push or open a PR.
