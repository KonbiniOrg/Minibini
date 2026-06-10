# Job History Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated deep-dive Job History page that collates the narrative history of a Job and its related records (Estimate, ChangeOrder, Invoice, Task, Deliverable, Shipment, Material), after widening `@history` coverage to the operational models that currently lack it.

**Architecture:** Add the signal-based `@history` decorator to four more models and remove it from `EstWorksheet`. Widen the existing `GET /api/jobs/{id}/history/` aggregation and annotate each entry with a human `source_label`. Add a new Svelte route `#/jobs/:id/history` rendering a flat narrative timeline with note-adding. Granularity refinements (curated action phrasing, grouping, filtering) are deliberately deferred to revision passes.

**Tech Stack:** Django 5.2 / DRF (signals + `HistoryEntry`), Svelte 5 SPA (svelte-spa-router), MySQL. Backend tests: Django `TestCase` in `/tests/`. Frontend tests: Vitest + `@testing-library/svelte` in `frontend/tests/`.

**Companion spec:** `docs/plans/2026-06-08-job-history-page-design.md`

**Key facts established during design (do not re-derive):**
- The `@history` decorator (`apps/core/history.py`) is pure signal wiring — **no DB schema change, no migration** for add/remove.
- `object_type` for a decorated model = `ClassName.lower()` (e.g. `Deliverable` → `'deliverable'`).
- **`ChangeOrder` `object_type` is normalized to `'changeorder'` up front (Task 0).** Auto **audit** entries already use `'changeorder'` (decorator: `ClassName.lower()`); the manual **action** writers historically used `'change_order'`. Task 0 flips the writers + the test assertions that query them, and migrates existing rows — so all later collation matches the single string `'changeorder'`.
- Label fields: `Job.job_number`, `Estimate.estimate_number`, `ChangeOrder.change_order_number`, `Invoice.invoice_number`, `Task.name`, `Deliverable.description`, `Shipment.sequence`, `Material.description`.
- pk attnames: `Task.task_id`, `Material.material_id`; `Deliverable`/`Shipment` use default `id` and carry `auto_now` `updated_at` (must be excluded).
- `api` client (`frontend/src/lib/api.js`) exposes `api.get(url)`, `api.post(url, data)`, `api.patch(url, data)`.
- **DB rule (CLAUDE.md):** never run `migrate`/`shell` writes/`loaddata`/seed scripts against the dev DB. Tests use the auto-created test DB. The backfill command (Task 9) is **user-run only** — the agent must never execute it.

---

## Task 0: Normalize `ChangeOrder` history `object_type` to `'changeorder'` (PREREQUISITE — do first)

`ChangeOrder` audit entries use `'changeorder'` (the decorator form) while its manual **action** writers use `'change_order'`. Standardize on `'changeorder'` (the decorator form can't easily change), flip the writers and the tests that assert against them, and migrate existing rows. After this task, all collation matches the single string.

**Files:**
- Modify: `apps/estimates/change_order_service.py` (2 sites)
- Modify: `apps/estimates/management/commands/mark_change_orders_expired.py` (1 site)
- Modify: `apps/api/portal/change_order_views.py` (1 site)
- Modify (tests that assert the written string): `tests/test_change_order_request_changes.py`, `tests/test_mark_change_orders_expired.py`, `tests/test_change_order_lifecycle.py`, `tests/test_portal_change_orders.py`
- Create: `apps/core/migrations/0019_normalize_change_order_object_type.py`

- [ ] **Step 1: Write the guard test (failing)**

Add to `ChangeOrderRequestChangesTests` in `tests/test_change_order_request_changes.py`:
```python
    def test_request_changes_history_uses_changeorder_object_type(self):
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        entries = HistoryEntry.objects.filter(object_id=self.co.pk, entry_type='action')
        self.assertTrue(entries.exists())
        self.assertFalse(entries.filter(object_type='change_order').exists())
        self.assertTrue(entries.filter(object_type='changeorder').exists())
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python manage.py test tests.test_change_order_request_changes.ChangeOrderRequestChangesTests.test_request_changes_history_uses_changeorder_object_type -v 2`
Expected: FAIL — the entry exists under `'change_order'`, not `'changeorder'`.

- [ ] **Step 3: Flip the four production writers**

In each file, change `object_type='change_order'` → `object_type='changeorder'`:
- `apps/estimates/change_order_service.py` (both occurrences, ~lines 185 and 228)
- `apps/estimates/management/commands/mark_change_orders_expired.py` (~line 41)
- `apps/api/portal/change_order_views.py` (~line 125)

- [ ] **Step 4: Flip the test assertions that query the old string**

These tests locate the written entry by filtering `object_type='change_order'`; update each occurrence to `'changeorder'` (replace-all per file):
- `tests/test_change_order_request_changes.py` (~line 81, in `test_records_customer_action_history`)
- `tests/test_mark_change_orders_expired.py` (~lines 98, 102, 110, 121, 129)
- `tests/test_change_order_lifecycle.py` (~lines 143, 146 — the before/after count filter)
- `tests/test_portal_change_orders.py` (~lines 103, 132, 160)

- [ ] **Step 5: Create the data migration**

Create `apps/core/migrations/0019_normalize_change_order_object_type.py`:
```python
from django.db import migrations


def forwards(apps, schema_editor):
    HistoryEntry = apps.get_model('core', 'HistoryEntry')
    HistoryEntry.objects.filter(object_type='change_order').update(object_type='changeorder')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0018_move_machine_state_to_appstate'),
    ]
    operations = [
        # Reverse is a deliberate no-op — we never want to recreate the split.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
```

- [ ] **Step 6: Verify no writer/assertion uses the old string**

Run: `grep -rn "object_type='change_order'" --include="*.py" .`
Expected: **no matches.**

- [ ] **Step 7: Run the affected suites, verify they pass**

Run: `python manage.py test tests.test_change_order_request_changes tests.test_mark_change_orders_expired tests.test_change_order_lifecycle tests.test_portal_change_orders -v 2`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/estimates/change_order_service.py \
        apps/estimates/management/commands/mark_change_orders_expired.py \
        apps/api/portal/change_order_views.py \
        apps/core/migrations/0019_normalize_change_order_object_type.py \
        tests/test_change_order_request_changes.py tests/test_mark_change_orders_expired.py \
        tests/test_change_order_lifecycle.py tests/test_portal_change_orders.py
git commit -m "Normalize ChangeOrder history object_type to 'changeorder'"
```

- [ ] **Step 9: USER RUNS — apply the data migration (agent must NOT run migrate)**

Ask the user to run, in their own shell:
```bash
python manage.py migrate core
```
This converts existing `'change_order'` rows to `'changeorder'`. (Per CLAUDE.md the agent never runs `migrate`.)

---

## Task 1: Add `@history` to `Task`

**Files:**
- Modify: `apps/jobs/models.py` (class `Task`, ~line 302; `history` already imported at line 6)
- Test: `tests/test_history_all_models.py`

- [ ] **Step 1: Add the model to the tracked-models test (failing)**

In `tests/test_history_all_models.py`, add the import and list entry, and add an exclude-pk assertion:

```python
from apps.jobs.models import Job, Task   # add Task
```
Add `Task` to `TRACKED_MODELS`:
```python
    TRACKED_MODELS = [
        Job, Task, Estimate, EstWorksheet,
        Invoice, PurchaseOrder, Bill, Contact, Business,
    ]
```
Add a new test method:
```python
    def test_pk_fields_excluded(self):
        expected = {
            Task: 'task_id',
        }
        for model, pk in expected.items():
            with self.subTest(model=model.__name__):
                self.assertIn(pk, model._history_exclude)
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: FAIL — `Task is not decorated with @history` and/or `'task_id' not found in _history_exclude`.

- [ ] **Step 3: Decorate `Task`**

In `apps/jobs/models.py`, immediately above `class Task(TaskBase):`:
```python
@history(exclude=['task_id'])
class Task(TaskBase):
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/models.py tests/test_history_all_models.py
git commit -m "Track Task with @history"
```

---

## Task 2: Add `@history` to `Material`

**Files:**
- Modify: `apps/inventory/models.py` (class `Material`, ~line 251; **add the import**)
- Test: `tests/test_history_all_models.py`

- [ ] **Step 1: Extend the tracked-models test (failing)**

In `tests/test_history_all_models.py` add the import and list/expected entries:
```python
from apps.inventory.models import Material   # add
```
Add `Material` to `TRACKED_MODELS`, and add to the `expected` dict in `test_pk_fields_excluded`:
```python
            Material: 'material_id',
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: FAIL — `Material is not decorated`.

- [ ] **Step 3: Decorate `Material`**

In `apps/inventory/models.py`, add the import near the top (with the other `apps.*` imports):
```python
from apps.core.history import history
```
Then immediately above `class Material(MaterialBase):`:
```python
@history(exclude=['material_id'])
class Material(MaterialBase):
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/models.py tests/test_history_all_models.py
git commit -m "Track Material with @history"
```

---

## Task 3: Add `@history` to `Deliverable`

**Files:**
- Modify: `apps/deliverables/models.py` (class `Deliverable`, ~line 6; **add the import**)
- Test: `tests/test_history_all_models.py`

- [ ] **Step 1: Extend the tracked-models test (failing)**

In `tests/test_history_all_models.py`:
```python
from apps.deliverables.models import Deliverable   # add
```
Add `Deliverable` to `TRACKED_MODELS`, and add to the `expected` dict:
```python
            Deliverable: 'id',
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: FAIL — `Deliverable is not decorated`.

- [ ] **Step 3: Decorate `Deliverable`**

In `apps/deliverables/models.py`, add near the top imports:
```python
from apps.core.history import history
```
Then immediately above `class Deliverable(models.Model):`:
```python
@history(exclude=['id', 'created_at', 'updated_at'])
class Deliverable(models.Model):
```
(`updated_at` is `auto_now`; excluding it stops every save logging a timestamp diff. `created_at` excluded as redundant with the `_created` marker.)

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/deliverables/models.py tests/test_history_all_models.py
git commit -m "Track Deliverable with @history"
```

---

## Task 4: Add `@history` to `Shipment`

**Files:**
- Modify: `apps/deliverables/models.py` (class `Shipment`, ~line 35; import added in Task 3)
- Test: `tests/test_history_all_models.py`

- [ ] **Step 1: Extend the tracked-models test (failing)**

In `tests/test_history_all_models.py`:
```python
from apps.deliverables.models import Deliverable, Shipment   # add Shipment
```
Add `Shipment` to `TRACKED_MODELS`, and add to the `expected` dict:
```python
            Shipment: 'id',
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: FAIL — `Shipment is not decorated`.

- [ ] **Step 3: Decorate `Shipment`**

In `apps/deliverables/models.py`, immediately above `class Shipment(models.Model):`:
```python
@history(exclude=['id', 'created_at', 'updated_at'])
class Shipment(models.Model):
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/deliverables/models.py tests/test_history_all_models.py
git commit -m "Track Shipment with @history"
```

---

## Task 5: Remove `@history` from `EstWorksheet`

Worksheets are internal planning scratch with little narrative value (spec §3). Removing the decorator stops new entries; old `estworksheet` rows remain harmlessly and fall out of the Job collation in Task 7.

**Files:**
- Modify: `apps/estimates/models.py` (class `EstWorksheet`, ~line 298)
- Test: `tests/test_history_all_models.py`

- [ ] **Step 1: Update the test to expect EstWorksheet NOT tracked (failing)**

In `tests/test_history_all_models.py`, remove `EstWorksheet` from `TRACKED_MODELS` (leave its import) and add an explicit assertion:
```python
    def test_estworksheet_not_tracked(self):
        self.assertFalse(
            getattr(EstWorksheet, '_history_tracked', False),
            'EstWorksheet should no longer be tracked',
        )
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: FAIL — `EstWorksheet should no longer be tracked` (still decorated).

- [ ] **Step 3: Remove the decorator**

In `apps/estimates/models.py`, delete the line `@history(exclude=['est_worksheet_id'])` directly above `class EstWorksheet(AbstractWorkContainer):`. Leave the `history` import (still used by `Estimate`/`ChangeOrder` in the same file).

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_history_all_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/models.py tests/test_history_all_models.py
git commit -m "Stop tracking EstWorksheet with @history"
```

---

## Task 6: Add `source_label` / `source_link` to `HistoryEntrySerializer`

These are `SerializerMethodField`s that read from serializer **context**, defaulting to `null`. Existing callers (Contact/Business/PO history) pass no context and are unaffected.

**Files:**
- Modify: `apps/api/history/serializers.py`
- Test: `tests/test_api_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_history.py`:
```python
from apps.api.history.serializers import HistoryEntrySerializer


class HistoryEntrySourceLabelTest(BaseTestCase):
    def test_source_label_from_context(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='hi',
        )
        ctx = {
            'source_labels': {('job', job.pk): 'Job XYZ'},
            'source_links': {('job', job.pk): '#/jobs/1'},
        }
        data = HistoryEntrySerializer(entry, context=ctx).data
        self.assertEqual(data['source_label'], 'Job XYZ')
        self.assertEqual(data['source_link'], '#/jobs/1')

    def test_source_label_defaults_null_without_context(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='hi',
        )
        data = HistoryEntrySerializer(entry).data
        self.assertIsNone(data['source_label'])
        self.assertIsNone(data['source_link'])
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_api_history.HistoryEntrySourceLabelTest -v 2`
Expected: FAIL — `KeyError: 'source_label'` (field not present).

- [ ] **Step 3: Add the fields**

Replace the body of `apps/api/history/serializers.py` with:
```python
from rest_framework import serializers
from apps.core.models import HistoryEntry


class HistoryEntrySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    source_label = serializers.SerializerMethodField()
    source_link = serializers.SerializerMethodField()

    class Meta:
        model = HistoryEntry
        fields = ['id', 'entry_type', 'object_type', 'object_id',
                  'user', 'username', 'timestamp', 'changes', 'text',
                  'source_label', 'source_link']
        read_only_fields = fields

    def get_source_label(self, obj):
        labels = self.context.get('source_labels') or {}
        return labels.get((obj.object_type, obj.object_id))

    def get_source_link(self, obj):
        links = self.context.get('source_links') or {}
        return links.get((obj.object_type, obj.object_id))
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_api_history.HistoryEntrySourceLabelTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/history/serializers.py tests/test_api_history.py
git commit -m "Add source_label/source_link to HistoryEntrySerializer (context-driven)"
```

---

## Task 7: Build the collation helper and widen the Job history endpoint

Extract collation into a focused, unit-testable helper, then have the viewset action use it. Adds ChangeOrder (both `object_type` strings), Task, Deliverable, Shipment, Material; drops `estworksheet`.

**Files:**
- Create: `apps/api/jobs/history.py`
- Modify: `apps/api/jobs/views.py` (the `history` action, ~lines 115-138)
- Test: `tests/test_api_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_history.py`:
```python
class JobHistoryCollationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_collates_new_object_types_and_labels(self):
        from apps.jobs.models import Job, Task
        job = Job.objects.first()
        task = Task.objects.filter(job=job).first()
        if not task:
            self.skipTest('Need a task on the job')
        HistoryEntry.objects.create(
            entry_type='audit', object_type='task', object_id=task.pk,
            changes={'status': {'old': 'pending', 'new': 'complete'}},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(resp.status_code, 200)
        labels = {(e['object_type'], e['source_label']) for e in resp.data['results']}
        self.assertIn(('task', f'Task: {task.name}'), labels)

    def test_collates_change_orders(self):
        from apps.jobs.models import Job
        from apps.estimates.models import ChangeOrder
        job = Job.objects.first()
        co = ChangeOrder.objects.filter(job=job).first()
        if not co:
            self.skipTest('Need a change order on the job')
        HistoryEntry.objects.create(
            entry_type='action', object_type='changeorder', object_id=co.pk,
            changes={'_action': 'Auto-expired'},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        labels = {(e['object_type'], e['source_label']) for e in resp.data['results']}
        self.assertIn(('changeorder', f'Change Order {co.change_order_number}'), labels)

    def test_excludes_estworksheet(self):
        from apps.jobs.models import Job
        from apps.estimates.models import EstWorksheet
        job = Job.objects.first()
        ws = EstWorksheet.objects.filter(job=job).first()
        if not ws:
            self.skipTest('Need a worksheet on the job')
        HistoryEntry.objects.create(
            entry_type='audit', object_type='estworksheet', object_id=ws.pk,
            changes={'status': {'old': 'a', 'new': 'b'}},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        types = [e['object_type'] for e in resp.data['results']]
        self.assertNotIn('estworksheet', types)
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_api_history.JobHistoryCollationTest -v 2`
Expected: FAIL — task/change_order entries not collated (and `source_label` absent for task).

- [ ] **Step 3: Create the collation helper**

Create `apps/api/jobs/history.py`:
```python
from django.db.models import Q

from apps.core.models import HistoryEntry


def build_job_history(job):
    """Collate a Job's history across its related records.

    Returns (queryset, source_labels, source_links), where the label/link
    dicts are keyed by (object_type, object_id). ChangeOrder uses the single
    object_type 'changeorder' (normalized in Task 0).
    """
    from apps.estimates.models import Estimate, ChangeOrder
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Task
    from apps.deliverables.models import Deliverable, Shipment
    from apps.inventory.models import Material

    estimates = list(Estimate.objects.filter(job=job))
    change_orders = list(ChangeOrder.objects.filter(job=job))
    invoices = list(Invoice.objects.filter(job=job))
    tasks = list(Task.objects.filter(job=job))
    deliverables = list(Deliverable.objects.filter(job=job))
    shipments = list(Shipment.objects.filter(job=job))
    materials = list(Material.objects.filter(job=job))

    q = Q(object_type='job', object_id=job.pk)

    def add(object_type, objs):
        nonlocal q
        ids = [o.pk for o in objs]
        if ids:
            q |= Q(object_type=object_type, object_id__in=ids)

    add('estimate', estimates)
    add('changeorder', change_orders)
    add('invoice', invoices)
    add('task', tasks)
    add('deliverable', deliverables)
    add('shipment', shipments)
    add('material', materials)

    labels = {}
    links = {}

    def reg(object_type, obj_id, label, link=None):
        labels[(object_type, obj_id)] = label
        links[(object_type, obj_id)] = link

    reg('job', job.pk, f'Job {job.job_number}', f'#/jobs/{job.pk}')
    for e in estimates:
        reg('estimate', e.pk, f'Estimate {e.estimate_number}')
    for c in change_orders:
        reg('changeorder', c.pk, f'Change Order {c.change_order_number}')
    for inv in invoices:
        reg('invoice', inv.pk, f'Invoice {inv.invoice_number}')
    for t in tasks:
        reg('task', t.pk, f'Task: {t.name}', f'#/jobs/{job.pk}/tasks/{t.pk}')
    for d in deliverables:
        reg('deliverable', d.pk, f'Deliverable: {d.description[:40]}')
    for s in shipments:
        reg('shipment', s.pk, f'Shipment #{s.sequence}')
    for m in materials:
        reg('material', m.pk, f'Material: {m.description[:40]}')

    qs = HistoryEntry.objects.filter(q).select_related('user')
    return qs, labels, links
```
(v1 populates `source_link` only for `job` and `task` — routes verified against `App.svelte`. Other link targets are deferred to revision 1, spec §6.6; they serialize as `null`.)

- [ ] **Step 4: Rewrite the viewset action to use the helper**

In `apps/api/jobs/views.py`, replace the body of the `history` action (the method starting at ~line 116) with:
```python
    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        from apps.api.jobs.history import build_job_history
        job = self.get_object()
        entries, labels, links = build_job_history(job)
        ctx = {'source_labels': labels, 'source_links': links}
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True, context=ctx)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True, context=ctx)
        return Response(serializer.data)
```
(The old inline `Estimate`/`EstWorksheet`/`Invoice` id-gathering and `Q` block are removed — now in the helper. Leave the file's other imports as they are.)

- [ ] **Step 5: Run the tests, verify they pass**

Run: `python manage.py test tests.test_api_history -v 2`
Expected: PASS (new collation tests + the pre-existing `JobHistoryAPITest` still green).

- [ ] **Step 6: Commit**

```bash
git add apps/api/jobs/history.py apps/api/jobs/views.py tests/test_api_history.py
git commit -m "Widen Job history collation (CO/Task/Deliverable/Shipment/Material) with source labels"
```

---

## Task 8: Frontend — Job History page, route, and header link

**Files:**
- Create: `frontend/src/routes/jobs/JobHistoryPage.svelte`
- Modify: `frontend/src/App.svelte` (import + routes)
- Modify: `frontend/src/components/jobs/JobHeader.svelte` (add the link)
- Test: `frontend/tests/components/JobHistoryPage.test.js`

- [ ] **Step 1: Write the failing component test**

Create `frontend/tests/components/JobHistoryPage.test.js`:
```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobHistoryPage from '@/routes/jobs/JobHistoryPage.svelte';

const JOB = { job_id: 5, job_number: 'JOB-2025-0005', name: 'Test' };

describe('JobHistoryPage', () => {
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });

  it('renders collated entries with source labels', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 1, entry_type: 'action', object_type: 'estimate', object_id: 9,
          username: 'admin', timestamp: '2026-01-02T10:00:00Z',
          changes: { _action: 'Sent to customer' },
          source_label: 'Estimate EST-2025-0001', source_link: null },
        { id: 2, entry_type: 'note', object_type: 'job', object_id: 5,
          username: 'admin', timestamp: '2026-01-03T10:00:00Z', text: 'Customer called',
          changes: null, source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByText, getByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByText('History — Job JOB-2025-0005');
    expect(getByText('Estimate EST-2025-0001')).toBeInTheDocument();
    expect(getByText('Sent to customer')).toBeInTheDocument();
    expect(getByText('Customer called')).toBeInTheDocument();
  });

  it('posts a note then reloads', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      return Promise.resolve({ results: [] });
    });
    api.post.mockResolvedValue({});
    const { findByText, getByPlaceholderText, getByRole } =
      render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByText('History — Job JOB-2025-0005');
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/notes/', { text: 'Hello' });
  });
});
```

- [ ] **Step 2: Run the test, verify it fails**

Run (from `frontend/`): `npm run test:run -- JobHistoryPage`
Expected: FAIL — cannot resolve `@/routes/jobs/JobHistoryPage.svelte`.

- [ ] **Step 3: Create the page component**

Create `frontend/src/routes/jobs/JobHistoryPage.svelte`:
```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';

  let { params = {} } = $props();
  let jobId = $derived(params.id);

  let job = $state(null);
  let history = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let noteText = $state('');
  let saving = $state(false);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [jobData, histData] = await Promise.all([
        api.get(`/api/jobs/${jobId}/`),
        api.get(`/api/jobs/${jobId}/history/`),
      ]);
      job = jobData;
      history = histData;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  let entries = $derived((history?.results || []).map(h => ({ ...h, when: new Date(h.timestamp) })));

  function fieldChanges(changes) {
    if (!changes) return '';
    return Object.entries(changes)
      .filter(([k]) => !k.startsWith('_'))
      .map(([k, v]) => `${k}: ${v.old} → ${v.new}`)
      .join(', ');
  }

  function describe(entry) {
    const c = entry.changes || {};
    if (entry.entry_type === 'note') return entry.text;
    if (c._action) return c._action;
    if (c._created) return 'created';
    return fieldChanges(c) || '(no detail)';
  }

  async function addNote() {
    const text = noteText.trim();
    if (!text) return;
    saving = true;
    try {
      await api.post(`/api/jobs/${jobId}/notes/`, { text });
      noteText = '';
      await load();
    } catch (e) {
      alert(e.message || 'Failed to add note');
    } finally {
      saving = false;
    }
  }
</script>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p class="error">{loadError}</p>
{:else}
  <div class="job-history-page">
    <p><a href="#/jobs/{jobId}">← Back to job</a></p>
    <h1>History — Job {job?.job_number}</h1>

    <div class="add-note">
      <textarea bind:value={noteText} rows="2" placeholder="Add a note…"></textarea>
      <button onclick={addNote} disabled={saving || !noteText.trim()}>Add Note</button>
    </div>

    {#if entries.length > 0}
      <ul class="timeline">
        {#each entries as entry (entry.id)}
          <li class="entry entry-{entry.entry_type}">
            <div class="entry-meta">
              {#if entry.source_link}
                <a class="source" href={entry.source_link}>{entry.source_label || entry.object_type}</a>
              {:else}
                <span class="source">{entry.source_label || entry.object_type}</span>
              {/if}
              <span class="who">{entry.username || 'System'}</span>
              <span class="when">{entry.when.toLocaleString()}</span>
            </div>
            <div class="entry-body preserve-breaks">{describe(entry)}</div>
          </li>
        {/each}
      </ul>
    {:else}
      <p>No history yet.</p>
    {/if}
  </div>
{/if}

<style>
  .job-history-page { max-width: 820px; margin: 0 auto; padding: 16px 24px; }
  .add-note { margin: 12px 0 20px; }
  .add-note textarea { width: 100%; box-sizing: border-box; }
  .timeline { list-style: none; padding: 0; margin: 0; }
  .entry { padding: 8px 0; border-bottom: 1px solid #eee; }
  .entry-meta { display: flex; gap: 10px; font-size: 13px; color: #555; align-items: baseline; }
  .entry-meta .source { font-weight: 600; color: #1f2937; }
  .entry-meta .when { margin-left: auto; }
  .entry-body { margin-top: 2px; }
  .entry-note .entry-body { font-style: italic; }
  .preserve-breaks { white-space: pre-wrap; }
</style>
```

- [ ] **Step 4: Register the route**

In `frontend/src/App.svelte`, add the import alongside the other job-page imports (near line 34):
```javascript
  import JobHistoryPage from './routes/jobs/JobHistoryPage.svelte';
```
And add to the `routes` object, next to the other `/jobs/:id/...` routes:
```javascript
    '/jobs/:id/history': JobHistoryPage,
```

- [ ] **Step 5: Add the header link**

In `frontend/src/components/jobs/JobHeader.svelte`, in the `<h1>` titleblock next to the existing edit/duplicate links, add (visible to all authenticated users — history is `IsAuthenticated`, so not gated on `canManageJobs`):
```svelte
      <a href="#/jobs/{job.job_id}/history" class="edit-link">history</a>
```
Place it after the `duplicate…` link.

- [ ] **Step 6: Run the test, verify it passes**

Run (from `frontend/`): `npm run test:run -- JobHistoryPage`
Expected: PASS (both cases).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/jobs/JobHistoryPage.svelte frontend/src/App.svelte \
        frontend/src/components/jobs/JobHeader.svelte \
        frontend/tests/components/JobHistoryPage.test.js
git commit -m "Add dedicated Job History page (#/jobs/:id/history) with header link"
```

---

## Task 9: Backfill management command (for evaluation data)

Existing jobs have little captured history (tracking was just added), so the page can't be evaluated against real data. This command synthesizes a representative spread of `HistoryEntry` rows for **one chosen job**, across its real related records, with staggered timestamps. It is **idempotent-cleanable** via a `_backfill` marker and a `--clear` flag.

> **DB RULE:** the agent writes and tests this command against the **test DB only** (via `call_command` in a `TestCase`). The agent must **never run it against the dev DB** — the user runs it on a chosen job themselves (final step).

**Files:**
- Create: `apps/jobs/management/commands/backfill_job_history.py`
- Test: `tests/test_backfill_job_history.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_job_history.py`:
```python
from django.core.management import call_command
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry


class BackfillJobHistoryTest(BaseTestCase):
    def test_backfill_creates_marked_entries_for_job(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        before = HistoryEntry.objects.filter(object_type='job', object_id=job.pk).count()
        call_command('backfill_job_history', f'--job={job.pk}')
        after = HistoryEntry.objects.filter(object_type='job', object_id=job.pk).count()
        self.assertGreater(after, before)
        # every created row carries the marker
        marked = HistoryEntry.objects.filter(
            object_type='job', object_id=job.pk, changes___backfill=True,
        )
        self.assertTrue(marked.exists())

    def test_clear_removes_only_backfilled_entries(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        # a real (non-backfill) note must survive
        keep = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='real note',
        )
        call_command('backfill_job_history', f'--job={job.pk}')
        call_command('backfill_job_history', f'--job={job.pk}', '--clear')
        self.assertTrue(HistoryEntry.objects.filter(pk=keep.pk).exists())
        self.assertFalse(
            HistoryEntry.objects.filter(object_id=job.pk, changes___backfill=True).exists()
        )
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python manage.py test tests.test_backfill_job_history -v 2`
Expected: FAIL — `Unknown command: 'backfill_job_history'`.

- [ ] **Step 3: Implement the command**

Create `apps/jobs/management/commands/backfill_job_history.py`:
```python
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import HistoryEntry, User
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate, ChangeOrder
from apps.invoicing.models import Invoice
from apps.deliverables.models import Deliverable, Shipment
from apps.inventory.models import Material


class Command(BaseCommand):
    help = (
        'Synthesize representative HistoryEntry rows for ONE job so the Job '
        'History page can be evaluated. Marked with changes["_backfill"]=True '
        'so --clear can remove them. NEVER run against data you care about.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--job', required=True, help='Job pk')
        parser.add_argument('--clear', action='store_true',
                            help='Delete previously backfilled entries for this job instead of creating.')

    def handle(self, *args, **opts):
        try:
            job = Job.objects.get(pk=opts['job'])
        except Job.DoesNotExist:
            raise CommandError(f'Job {opts["job"]} not found')

        if opts['clear']:
            n = self._clear(job)
            self.stdout.write(self.style.SUCCESS(f'Cleared {n} backfilled entries for job {job.pk}'))
            return

        user = User.objects.order_by('pk').first()
        created = self._backfill(job, user)
        self.stdout.write(self.style.SUCCESS(f'Created {created} backfilled entries for job {job.pk}'))

    def _object_ids(self, job):
        """(object_type, [ids]) pairs covering everything the Job page collates."""
        return [
            ('job', [job.pk]),
            ('estimate', list(Estimate.objects.filter(job=job).values_list('pk', flat=True))),
            ('changeorder', list(ChangeOrder.objects.filter(job=job).values_list('pk', flat=True))),
            ('invoice', list(Invoice.objects.filter(job=job).values_list('pk', flat=True))),
            ('task', list(Task.objects.filter(job=job).values_list('pk', flat=True))),
            ('deliverable', list(Deliverable.objects.filter(job=job).values_list('pk', flat=True))),
            ('shipment', list(Shipment.objects.filter(job=job).values_list('pk', flat=True))),
            ('material', list(Material.objects.filter(job=job).values_list('pk', flat=True))),
        ]

    def _clear(self, job):
        total = 0
        for object_type, ids in self._object_ids(job):
            if not ids:
                continue
            qs = HistoryEntry.objects.filter(
                object_type=object_type, object_id__in=ids, changes___backfill=True,
            )
            total += qs.count()
            qs.delete()
        return total

    def _backfill(self, job, user):
        now = timezone.now()
        created = 0
        day = 0
        for object_type, ids in self._object_ids(job):
            for obj_id in ids:
                # a "created" beat and a "changed" beat, staggered into the past
                created += self._entry(object_type, obj_id, user, now - timedelta(days=day + 30),
                                       changes={'_created': True, '_backfill': True})
                created += self._entry(object_type, obj_id, user, now - timedelta(days=day + 15),
                                       entry_type='action',
                                       changes={'_action': f'Backfilled activity on {object_type}',
                                                '_backfill': True})
                day += 1
        return created

    def _entry(self, object_type, obj_id, user, when, entry_type='audit', changes=None):
        entry = HistoryEntry.objects.create(
            entry_type=entry_type, object_type=object_type, object_id=obj_id,
            user=user, changes=changes or {},
        )
        # timestamp is auto_now_add; backdate it via update() (HistoryEntry is not
        # @history-tracked and has no save-normalization, so update() is safe here).
        HistoryEntry.objects.filter(pk=entry.pk).update(timestamp=when)
        return 1
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python manage.py test tests.test_backfill_job_history -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/management/commands/backfill_job_history.py tests/test_backfill_job_history.py
git commit -m "Add backfill_job_history management command for Job History evaluation data"
```

- [ ] **Step 6: USER RUNS — populate a chosen job (agent must NOT run this)**

Ask the user to pick a job with a good spread of related records and run, in their own shell:
```bash
python manage.py backfill_job_history --job <JOB_PK>
```
Then open `#/jobs/<JOB_PK>/history` to evaluate. To undo: `python manage.py backfill_job_history --job <JOB_PK> --clear`.

---

## Task 10: Documentation

**Files:**
- Modify: `docs/designs/architecture-and-conventions.md` (§7.2, §7.4, §7.5)

- [ ] **Step 1: Update §7.2 (tracked models)**

Replace the bullet list under "Models opt in with `@history(...)`" so it reads (additions/removal reflected):
- `Contact`, `Business` — `apps/contacts/models.py`
- `Job`, `Task`, `BlepChangeRequest` — `apps/jobs/models.py`
- `Estimate`, `ChangeOrder` — `apps/estimates/models.py` *(EstWorksheet no longer tracked)*
- `Invoice` — `apps/invoicing/models.py`
- `PurchaseOrder`, `Bill` — `apps/purchasing/models.py`
- `Material` — `apps/inventory/models.py`
- `Deliverable`, `Shipment` — `apps/deliverables/models.py`
- `Shift`, `ShiftChangeRequest` — `apps/core/models.py`

- [ ] **Step 2: Update §7.4 (endpoints)**

Change the Job history bullet to describe the widened collation and note the new fields/route:
> - `GET /api/jobs/{id}/history/` — aggregates the job plus its estimates, change orders, invoices, tasks, deliverables, shipments, and materials (`apps/api/jobs/history.py` → `build_job_history`). Each entry carries `source_label` (and `source_link` for job/task). EstWorksheet is no longer collated.

Add to §7.5: *A dedicated `#/jobs/:id/history` page (`JobHistoryPage.svelte`) renders the collated Job feed; the small `HistoryPanel.svelte` remains on Contact/Business/PO.*

- [ ] **Step 3: Commit**

```bash
git add docs/designs/architecture-and-conventions.md
git commit -m "Docs: Job History page and widened history tracking"
```

---

## Final verification

- [ ] **Backend suite** (single runner only — shared MySQL test DB): `python manage.py test tests.test_history_all_models tests.test_api_history tests.test_backfill_job_history tests.test_change_order_request_changes tests.test_mark_change_orders_expired tests.test_change_order_lifecycle tests.test_portal_change_orders -v 2` → all PASS.
- [ ] **Frontend suite** (from `frontend/`): `npm run test:run` → all PASS.
- [ ] Manually confirm the design's deferred items (curated actions, grouping, filtering, ShipmentItem, link coverage) remain explicitly out of v1 — these are the revision surface the user will drive after seeing real data (Task 9 step 6).

---

## Self-review notes (for the implementer)

- **Spec coverage:** prerequisite object_type normalization (Task 0); decorator add/remove (Tasks 1–5) ↔ spec §4.1; collation + source labels (Tasks 6–7) ↔ §4.2; page + route + header link (Task 8) ↔ §4.3; backfill (Task 9) is the user-requested evaluation-data task; docs (Task 10) ↔ §4.4. Deferred items (§6) are intentionally not implemented.
- **Migrations:** the `@history` add/remove changes are signal wiring only — `makemigrations` should emit **nothing** for those apps (if it does, stop and investigate). The *only* migration in this plan is Task 0's hand-written data migration (`core/0019_...`), which the **user** applies via `migrate`.
- **Type consistency:** `build_job_history` returns `(queryset, labels, links)`; the serializer reads context keys `source_labels` / `source_links`; the viewset passes exactly those keys. The page reads `entry.source_label` / `entry.source_link` / `entry.changes._action` / `entry.changes._created`, matching the serializer output.
