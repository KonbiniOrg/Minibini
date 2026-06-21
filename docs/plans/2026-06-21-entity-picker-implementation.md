# Entity-Picker Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SPA's ad-hoc entity `<select>`s and one-off type-ahead pickers with a single `SearchPicker` behavior core plus thin per-entity pickers, and add the missing `?search=` API endpoints.

**Architecture:** A `SearchPicker.svelte` base owns all interaction (debounced search, focus/blur dropdown, prefill-by-id label resolution with a race guard, selected/clear). Thin per-entity pickers (Business, Job, Contact, PurchaseOrder, Bill, InventoryItem, Customer) supply only their search call, label/row rendering, and emit shape via props/snippets. Backend list viewsets gain a hand-rolled `?search=` filter mirroring the existing contacts/jobs pattern.

**Tech Stack:** Django 5.2 + DRF (backend), Svelte 5 runes + Vite (frontend), Vitest + @testing-library/svelte (frontend tests), Django `TestCase` + `APIClient` (backend tests).

## Global Constraints

- **Never write to the dev DB.** Tests use a separate test DB; never run `migrate`/`loaddata`/ORM writes against dev. (CLAUDE.md)
- Backend search is **hand-rolled in `get_queryset`** — do NOT introduce DRF `SearchFilter` (matches contacts/jobs).
- **All DELETE responses return 200 with a JSON body**, never 204 (not relevant here but a repo rule).
- Frontend: **no CSS frameworks**, semantic HTML, per-component `<style>`.
- **Saves are explicit; reversible actions don't confirm** — pickers select/clear freely (no confirm dialogs).
- Run frontend tests with `npm run test:run` from `frontend/` (never watch mode). Run backend tests with `python manage.py test` — **never in parallel from multiple agents** (shared MySQL test DB).
- Svelte 5: wrap `<tr>` in `<tbody>`; use runes (`$state`/`$derived`/`$effect`/`$props`/`$bindable`).
- Test import alias is `@/` → `frontend/src/`. Mock the API with `vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }))`.

---

## Task 1: Backend `?search=` for Purchase Orders

**Files:**
- Modify: `apps/api/purchasing/views.py` (imports + `PurchaseOrderViewSet.get_queryset`, ~lines 2-6 and 77-94)
- Test: `tests/test_api_purchasing.py` (add a test class or methods)

**Interfaces:**
- Produces: `GET /api/purchase-orders/?search=<q>` filters by `po_number` or vendor `business__business_name` (case-insensitive, OR'd), composes with existing `business`/`status` filters.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_purchasing.py`:

```python
from rest_framework.test import APIClient
from apps.core.models import User
from apps.contacts.models import Contact, Business
from apps.purchasing.models import PurchaseOrder
from tests.base import BaseTestCase


class PurchaseOrderSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        dc = Contact.objects.create(first_name='DC', last_name='')
        self.acme = Business.objects.create(business_name='Acme Steel', default_contact=dc)
        self.po_match = PurchaseOrder.objects.create(business=self.acme, po_number='PO-SEARCH-1')
        other_dc = Contact.objects.create(first_name='OC', last_name='')
        other = Business.objects.create(business_name='Zenith Glass', default_contact=other_dc)
        self.po_other = PurchaseOrder.objects.create(business=other, po_number='PO-OTHER-9')

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['po_id'] for r in rows]

    def test_search_by_po_number(self):
        resp = self.client.get('/api/purchase-orders/?search=SEARCH-1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.po_match.po_id, self._ids(resp))
        self.assertNotIn(self.po_other.po_id, self._ids(resp))

    def test_search_by_vendor_name(self):
        resp = self.client.get('/api/purchase-orders/?search=Acme')
        self.assertIn(self.po_match.po_id, self._ids(resp))
        self.assertNotIn(self.po_other.po_id, self._ids(resp))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_purchasing.PurchaseOrderSearchTest -v 2`
Expected: FAIL — `test_search_by_vendor_name` returns both POs (no `search` handling yet).

- [ ] **Step 3: Add `Q` to imports**

In `apps/api/purchasing/views.py`, change the `django.db.models` import block to include `Q`:

```python
from django.db.models import (
    F, Sum, Value, Case, When, DecimalField, ExpressionWrapper,
    OuterRef, Subquery, Q,
)
```

- [ ] **Step 4: Add the search filter to `PurchaseOrderViewSet.get_queryset`**

In `PurchaseOrderViewSet.get_queryset`, immediately before `return qs` (after the `po_status` block), insert:

```python
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(po_number__icontains=search)
                | Q(business__business_name__icontains=search)
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_api_purchasing.PurchaseOrderSearchTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api_purchasing.py
git commit -m "feat(api): add ?search= to purchase-orders (po_number, vendor name)"
```

---

## Task 2: Backend `?search=` for Bills

**Files:**
- Modify: `apps/api/purchasing/views.py` (`BillViewSet.get_queryset`, ~lines 458-466)
- Test: `tests/test_api_bill_list.py`

**Interfaces:**
- Produces: `GET /api/bills/?search=<q>` filters by `vendor_invoice_number`, `purchase_order__po_number`, or vendor `business__business_name`. Applies in all list modes (summary and non-summary); placed in the shared filter block.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_bill_list.py`:

```python
from rest_framework.test import APIClient
from apps.core.models import User
from apps.contacts.models import Contact, Business
from apps.purchasing.models import Bill
from tests.base import BaseTestCase


class BillSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        dc = Contact.objects.create(first_name='DC', last_name='')
        self.acme = Business.objects.create(business_name='Acme Steel', default_contact=dc)
        self.match = Bill.objects.create(business=self.acme, vendor_invoice_number='INV-7788')
        dc2 = Contact.objects.create(first_name='OC', last_name='')
        other = Business.objects.create(business_name='Zenith Glass', default_contact=dc2)
        self.other = Bill.objects.create(business=other, vendor_invoice_number='INV-0001')

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['bill_id'] for r in rows]

    def test_search_by_vendor_invoice_number(self):
        resp = self.client.get('/api/bills/?search=7788')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.match.bill_id, self._ids(resp))
        self.assertNotIn(self.other.bill_id, self._ids(resp))

    def test_search_by_vendor_name(self):
        resp = self.client.get('/api/bills/?search=Acme')
        self.assertIn(self.match.bill_id, self._ids(resp))
        self.assertNotIn(self.other.bill_id, self._ids(resp))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_bill_list.BillSearchTest -v 2`
Expected: FAIL — `test_search_by_vendor_name` returns both bills.

- [ ] **Step 3: Add the search filter to `BillViewSet.get_queryset`**

`Q` is now imported (Task 1). In `BillViewSet.get_queryset`, inside the "Filters that apply to all actions" block, after the `purchase_order` filter and before the `if self.action == 'list' and not self._summary_mode():` block, insert:

```python
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(vendor_invoice_number__icontains=search)
                | Q(purchase_order__po_number__icontains=search)
                | Q(business__business_name__icontains=search)
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_bill_list.BillSearchTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api_bill_list.py
git commit -m "feat(api): add ?search= to bills (invoice no, PO no, vendor name)"
```

---

## Task 3: Backend `?search=` for Inventory

**Files:**
- Modify: `apps/api/inventory/views.py` (`InventoryItemViewSet.get_queryset`)
- Test: `tests/test_api_inventory.py`

**Interfaces:**
- Produces: `GET /api/inventory/?search=<q>` filters by `code` or `description`. Applies only to the `list` action (consistent with the existing `is_active`/`include_finished` list-only scoping), composes with those filters.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_inventory.py`:

```python
from rest_framework.test import APIClient
from apps.core.models import User
from apps.inventory.models import InventoryItem
from tests.base import BaseTestCase


class InventorySearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.match = InventoryItem.objects.create(
            code='BOLT-14', description='Hex bolt 1/4"', is_catalog=True)
        self.other = InventoryItem.objects.create(
            code='SHEET-3', description='Aluminum sheet', is_catalog=True)

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['inventory_item_id'] for r in rows]

    def test_search_by_code(self):
        resp = self.client.get('/api/inventory/?search=BOLT')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.match.inventory_item_id, self._ids(resp))
        self.assertNotIn(self.other.inventory_item_id, self._ids(resp))

    def test_search_by_description(self):
        resp = self.client.get('/api/inventory/?search=Hex')
        self.assertIn(self.match.inventory_item_id, self._ids(resp))
        self.assertNotIn(self.other.inventory_item_id, self._ids(resp))
```

> If `InventoryItem.objects.create(...)` requires additional non-null fields in this schema, mirror an existing `InventoryItem.objects.create(...)` call already used in `tests/test_api_inventory.py` for the required kwargs.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_inventory.InventorySearchTest -v 2`
Expected: FAIL — both items returned.

- [ ] **Step 3: Add the search filter**

In `apps/api/inventory/views.py`, inside `InventoryItemViewSet.get_queryset`, in the list-only section (after the `if self.action != 'list': return qs` guard, alongside the other list filters), add:

```python
        search = self.request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(code__icontains=search) | Q(description__icontains=search))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_inventory.InventorySearchTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/inventory/views.py tests/test_api_inventory.py
git commit -m "feat(api): add ?search= to inventory (code, description)"
```

---

## Task 4: `SearchPicker.svelte` behavior core

**Files:**
- Create: `frontend/src/components/SearchPicker.svelte`
- Test: `frontend/tests/components/SearchPicker.test.js`

**Interfaces:**
- Produces a component with props: `value` (bindable, opaque token), `selectedItem`, `search(query)=>Promise<row[]>`, `resolveLabel(value, selectedItem?)=>Promise<string|null>`, `rowLabel(row)=>string`, `onPick(row)`, `onClear()`, `disabled`, `placeholder`, plus optional snippets `row(item)`, `selected(label)`, `header(close)`.
- Behavior: debounced (250 ms) `search` on input; focus/blur dropdown; prefill `$effect` calls `resolveLabel` when `value` changes and differs from the cached `labelForValue` (race-guarded by capturing the value); `pick(r)` calls `onPick(r)` then caches `rowLabel(r)`; `clear()` calls `onClear()`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/SearchPicker.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SearchPicker from '@/components/SearchPicker.svelte';

beforeEach(() => { vi.useRealTimers(); });

describe('SearchPicker', () => {
  it('debounces, searches, and picks a row', async () => {
    const search = vi.fn().mockResolvedValue([{ id: 1, name: 'Acme' }]);
    const onPick = vi.fn();
    const { getByPlaceholderText, findByRole } = render(SearchPicker, {
      props: {
        search,
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name,
        onPick,
        placeholder: 'Search…',
      },
    });
    await fireEvent.input(getByPlaceholderText('Search…'), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(search).toHaveBeenCalledWith('ac');
    await fireEvent.click(await findByRole('button', { name: 'Acme' }));
    expect(onPick).toHaveBeenCalledWith({ id: 1, name: 'Acme' });
  });

  it('does not search a blank query', async () => {
    const search = vi.fn();
    const { getByPlaceholderText } = render(SearchPicker, {
      props: { search, resolveLabel: vi.fn(), placeholder: 'Search…' },
    });
    await fireEvent.input(getByPlaceholderText('Search…'), { target: { value: '  ' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(search).not.toHaveBeenCalled();
  });

  it('resolves a label for a prefilled value', async () => {
    const resolveLabel = vi.fn().mockResolvedValue('Prefilled Co');
    const { findByText } = render(SearchPicker, {
      props: { value: 42, search: vi.fn(), resolveLabel, rowLabel: (r) => r.name },
    });
    expect(await findByText('Prefilled Co')).toBeInTheDocument();
    expect(resolveLabel).toHaveBeenCalledWith(42, null);
  });

  it('clears the selection', async () => {
    const onClear = vi.fn();
    const { getByRole, findByText } = render(SearchPicker, {
      props: {
        value: 42, search: vi.fn(),
        resolveLabel: vi.fn().mockResolvedValue('Prefilled Co'),
        rowLabel: (r) => r.name, onClear,
      },
    });
    await findByText('Prefilled Co');
    await fireEvent.click(getByRole('button', { name: 'Clear' }));
    expect(onClear).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- SearchPicker`
Expected: FAIL — component file does not exist.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/SearchPicker.svelte`:

```svelte
<script>
  // Behavior core for entity type-ahead pickers. Owns the interaction:
  // debounced search, the focus/blur results dropdown, prefill-by-id label
  // resolution (with a race guard), and the selected/clear state. It is
  // deliberately ignorant of endpoints and entity shapes — those arrive via
  // the `search` / `resolveLabel` / `rowLabel` callbacks and the snippets.
  let {
    value = $bindable(null),       // opaque selection token (id, or {type,id})
    selectedItem = null,           // optional prefill object, passed to resolveLabel
    search,                        // (query) => Promise<row[]>
    resolveLabel,                  // (value, selectedItem?) => Promise<string|null>
    rowLabel = (r) => String(r),   // (row) => string
    onPick = () => {},             // (row) => void  — parent sets `value`
    onClear = () => {},            // () => void     — parent clears `value`
    disabled = false,
    placeholder = 'Search…',
    row,                           // optional snippet(item)
    selected,                      // optional snippet(label)
    header,                        // optional snippet(close)
  } = $props();

  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);
  let selectedLabel = $state('');
  let labelForValue = $state(null); // which `value` selectedLabel describes
  let timer = null;

  function runSearch() {
    const q = query.trim();
    if (!q) { results = []; showResults = false; return; }
    Promise.resolve(search(q))
      .then((rows) => { results = rows || []; showResults = true; })
      .catch((e) => console.error(e));
  }

  function onInput(e) {
    query = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(runSearch, 250);
  }

  function onFocus() { if (query.trim()) showResults = true; }
  function onBlur() { setTimeout(() => { showResults = false; }, 200); }
  function close() { showResults = false; query = ''; results = []; }

  function pick(r) {
    close();
    onPick(r);              // parent assigns `value` synchronously
    selectedLabel = rowLabel(r);
    labelForValue = value;  // now matches the just-assigned value
  }

  function clear() {
    close();
    selectedLabel = '';
    labelForValue = null;
    onClear();              // parent sets value = null
  }

  // Prefill / external value changes: resolve a display label once per value.
  $effect(() => {
    const v = value;
    if (v == null) { selectedLabel = ''; labelForValue = null; return; }
    if (v === labelForValue) return; // already labelled (race guard)
    Promise.resolve(resolveLabel(v, selectedItem))
      .then((lbl) => { if (value === v) { selectedLabel = lbl || ''; labelForValue = v; } })
      .catch(() => {});
  });
</script>

{#if value != null && labelForValue === value}
  {#if selected}
    {@render selected(selectedLabel)}
  {:else}
    <span class="sp-selected">{selectedLabel}
      <button type="button" onclick={clear} disabled={disabled}>Clear</button>
    </span>
  {/if}
{:else}
  <input type="text" value={query} oninput={onInput} onfocus={onFocus}
         onblur={onBlur} {disabled} {placeholder}>
  {#if showResults}
    <ul class="sp-results" role="listbox">
      {#if header}{@render header(close)}{/if}
      {#if results.length}
        {#each results as r}
          <li>
            <button type="button" onmousedown={() => pick(r)}>
              {#if row}{@render row(r)}{:else}{rowLabel(r)}{/if}
            </button>
          </li>
        {/each}
      {:else}
        <li class="sp-empty">No matches.</li>
      {/if}
    </ul>
  {/if}
{/if}

<style>
  .sp-results { position: absolute; background: white; border: 1px solid #ccc;
    max-height: 220px; overflow-y: auto; z-index: var(--z-dropdown); margin: 0;
    padding: 0; list-style: none; min-width: 16rem; }
  .sp-results li button { display: block; width: 100%; text-align: left;
    background: none; border: none; padding: 6px 8px; cursor: pointer; font-size: 13px; }
  .sp-results li button:hover { background: #eef; }
  .sp-empty { padding: 6px 8px; color: #777; font-size: 13px; }
  .sp-selected { font-size: 14px; }
</style>
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test:run -- SearchPicker`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SearchPicker.svelte frontend/tests/components/SearchPicker.test.js
git commit -m "feat(spa): add SearchPicker behavior core for entity type-aheads"
```

---

## Task 5: `BusinessPicker.svelte` (new)

**Files:**
- Create: `frontend/src/components/BusinessPicker.svelte`
- Test: `frontend/tests/components/BusinessPicker.test.js`

**Interfaces:**
- Consumes: `SearchPicker` (Task 4).
- Produces: `<BusinessPicker bind:value selectedItem onSelect disabled />`. `value` = `business_id` (number) | null. `onSelect(business|null)` hands back the full business row (which includes `default_contact`). Searches `/api/businesses/?search=<q>&page_size=10`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/BusinessPicker.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import BusinessPicker from '@/components/BusinessPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BusinessPicker', () => {
  it('searches and emits the picked business', async () => {
    api.get.mockResolvedValue({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(BusinessPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/business/i), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/businesses/?search=ac&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /Acme Steel/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ business_id: 5 }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- BusinessPicker`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/BusinessPicker.svelte`:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (b) => b.business_name;
  const search = (q) =>
    api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/businesses/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(b) => { value = b.business_id; onSelect(b); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search business…" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- BusinessPicker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BusinessPicker.svelte frontend/tests/components/BusinessPicker.test.js
git commit -m "feat(spa): add BusinessPicker on SearchPicker base"
```

---

## Task 6: Rewrite `JobPicker.svelte` on the base

**Files:**
- Modify: `frontend/src/components/JobPicker.svelte` (full replace)
- Modify: `frontend/tests/components/JobPicker.test.js`

**Interfaces:**
- Produces: `<JobPicker bind:value selectedItem onSelect disabled />`. **`value` is now `job_id` (number) | null** (was `{job_id, job_number}`). `onSelect(job|null)` hands back the full job row. Searches `/api/jobs/?search=<q>&page_size=10`.

- [ ] **Step 1: Update the test to the new contract**

Replace `frontend/tests/components/JobPicker.test.js` with:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import JobPicker from '@/components/JobPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('JobPicker', () => {
  it('searches and emits the full job; value is the id', async () => {
    api.get.mockResolvedValue({ results: [{ job_id: 1, job_number: 'JOB-1', name: 'widget run' }] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(JobPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/jobs/?search=wid&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /JOB-1/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ job_id: 1 }));
  });

  it('renders a prefilled label from selectedItem without a fetch', async () => {
    const { findByText } = render(JobPicker, {
      props: { value: 1, selectedItem: { job_id: 1, job_number: 'JOB-1', name: 'x' } },
    });
    expect(await findByText(/JOB-1/)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- JobPicker`
Expected: FAIL — old component emits `{job_id, job_number}` and has no `selectedItem`.

- [ ] **Step 3: Replace the component**

Replace `frontend/src/components/JobPicker.svelte` with:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (j) => `${j.job_number} — ${j.name ?? j.description ?? ''}`;
  const search = (q) =>
    api.get(`/api/jobs/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/jobs/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(j) => { value = j.job_id; onSelect(j); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search jobs…" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- JobPicker`
Expected: PASS (2 tests). (Consumers are updated in Task 13 — the app may not build cleanly against JobPicker until then; that is expected and isolated to job consumers.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/JobPicker.svelte frontend/tests/components/JobPicker.test.js
git commit -m "refactor(spa): rebuild JobPicker on SearchPicker (value = job_id)"
```

---

## Task 7: Rewrite `ContactPicker.svelte` on the base

**Files:**
- Modify: `frontend/src/components/ContactPicker.svelte` (full replace)
- Modify: `frontend/tests/components/ContactPicker.test.js`

**Interfaces:**
- Produces: `<ContactPicker bind:value selectedItem onSelect disabled />`. `value` = `contact_id` (number) | null (unchanged from old bare-id). `onSelect(contact|null)` now hands back the full contact (incl. nested `business`). Searches `/api/contacts/?search=<q>&page_size=10`.

- [ ] **Step 1: Update the test**

Replace `frontend/tests/components/ContactPicker.test.js` with:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import ContactPicker from '@/components/ContactPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('ContactPicker', () => {
  it('searches and emits the picked contact; value is the id', async () => {
    api.get.mockResolvedValue({ results: [
      { contact_id: 3, name: 'Pat Quinn', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(ContactPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/contact/i), { target: { value: 'pat' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=pat&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /Pat Quinn/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ contact_id: 3 }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- ContactPicker`
Expected: FAIL — old component has no `onSelect`, different placeholder/markup.

- [ ] **Step 3: Replace the component**

Replace `frontend/src/components/ContactPicker.svelte` with:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (c) => c.business ? `${c.name} — ${c.business.business_name}` : c.name;
  const search = (q) =>
    api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/contacts/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(c) => { value = c.contact_id; onSelect(c); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search contacts…" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- ContactPicker`
Expected: PASS.

- [ ] **Step 5: Verify the one consumer still binds an id**

`DuplicateJobPage.svelte` binds `value` to a contact id and reads it on submit. Confirm it does not depend on a `{contact_id,…}` object (the old ContactPicker already emitted a bare id, so no change is expected). If it passes a prefill, pass it as `selectedItem`.

Run: `npm run test:run` (full suite) to confirm no DuplicateJobPage test regressions.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ContactPicker.svelte frontend/tests/components/ContactPicker.test.js
git commit -m "refactor(spa): rebuild ContactPicker on SearchPicker (emits full contact)"
```

---

## Task 8: Rewrite `PurchaseOrderPicker.svelte` (global) + convert BillFormPage PO field to a pulldown

**Files:**
- Modify: `frontend/src/components/PurchaseOrderPicker.svelte` (full replace — now a global search)
- Modify: `frontend/tests/components/PurchaseOrderPicker.test.js`
- Modify: `frontend/src/routes/bills/BillFormPage.svelte` (replace the `PurchaseOrderPicker` usage with a plain vendor-scoped `<select>`)

**Interfaces:**
- Produces: `<PurchaseOrderPicker bind:value selectedItem onSelect disabled />`. `value` = `po_id` (number) | null. `onSelect(po|null)` hands back the full PO. Searches `/api/purchase-orders/?search=<q>&page_size=10` (global — no `businessId` prop anymore).

- [ ] **Step 1: Update the test**

Replace `frontend/tests/components/PurchaseOrderPicker.test.js` with:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PurchaseOrderPicker from '@/components/PurchaseOrderPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('PurchaseOrderPicker', () => {
  it('searches all POs globally and emits the picked PO', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 7, po_number: 'PO-7', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(PurchaseOrderPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/purchase order/i), { target: { value: 'po-7' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/?search=po-7&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /PO-7/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ po_id: 7 }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- PurchaseOrderPicker`
Expected: FAIL — old component is vendor-scoped, client-filtered, takes `businessId`.

- [ ] **Step 3: Replace the component**

Replace `frontend/src/components/PurchaseOrderPicker.svelte` with:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (p) => `${p.po_number}${p.business ? ` — ${p.business.business_name}` : ''}`;
  const search = (q) =>
    api.get(`/api/purchase-orders/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/purchase-orders/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(p) => { value = p.po_id; onSelect(p); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search purchase order…" />
```

- [ ] **Step 4: Convert the BillFormPage PO field to a vendor-scoped pulldown**

Open `frontend/src/routes/bills/BillFormPage.svelte`. The vendor's POs are a small, business-scoped set (per spec, a plain pulldown). Replace the `<PurchaseOrderPicker .../>` usage and its import with a plain `<select>` populated from the bill form's existing vendor-PO list. Concretely:

- Remove the `import PurchaseOrderPicker from ...` line.
- Where the PO field renders, use a `<select bind:value={form.purchase_order}>` listing the POs already loaded for the selected vendor (the page fetches `/api/purchase-orders/?business=<id>` when a business is chosen — reuse that array; if it is not currently kept in a variable, add `let vendorPos = $state([])` populated in the same `$effect`/loader that reacts to the chosen business, mirroring `PurchaseOrderForm`'s `fetchContactsAndAutoSelect` pattern).

Markup:

```svelte
<select id="purchase_order" bind:value={form.purchase_order}>
  <option value="">-- None --</option>
  {#each vendorPos as po (po.po_id)}
    <option value={po.po_id}>{po.po_number}</option>
  {/each}
</select>
```

- [ ] **Step 5: Run tests**

Run: `npm run test:run -- PurchaseOrderPicker`
Expected: PASS.
Run: `npm run test:run -- BillFormPage` (if a test exists; otherwise run the full suite)
Expected: PASS — no remaining references to the old vendor-scoped picker.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PurchaseOrderPicker.svelte frontend/tests/components/PurchaseOrderPicker.test.js frontend/src/routes/bills/BillFormPage.svelte
git commit -m "refactor(spa): make PurchaseOrderPicker a global search; Bill PO field -> pulldown"
```

---

## Task 9: `BillPicker.svelte` (new)

**Files:**
- Create: `frontend/src/components/BillPicker.svelte`
- Test: `frontend/tests/components/BillPicker.test.js`

**Interfaces:**
- Consumes: `SearchPicker`.
- Produces: `<BillPicker bind:value selectedItem onSelect disabled />`. `value` = `bill_id` (number) | null. Searches `/api/bills/?search=<q>&page_size=10`. Label: `vendor_invoice_number` if present, else the linked PO number, plus the vendor name.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/BillPicker.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import BillPicker from '@/components/BillPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BillPicker', () => {
  it('searches and emits the picked bill', async () => {
    api.get.mockResolvedValue({ results: [
      { bill_id: 4, vendor_invoice_number: 'INV-7788', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(BillPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/bill/i), { target: { value: '7788' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/bills/?search=7788&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /INV-7788/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ bill_id: 4 }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- BillPicker`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/BillPicker.svelte`:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const docNo = (b) => b.vendor_invoice_number || b.purchase_order?.po_number || `Bill #${b.bill_id}`;
  const label = (b) => `${docNo(b)}${b.business ? ` — ${b.business.business_name}` : ''}`;
  const search = (q) =>
    api.get(`/api/bills/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/bills/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(b) => { value = b.bill_id; onSelect(b); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search bill…" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- BillPicker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BillPicker.svelte frontend/tests/components/BillPicker.test.js
git commit -m "feat(spa): add BillPicker on SearchPicker base"
```

---

## Task 10: Rename `PriceListItemPicker` → `InventoryItemPicker` (server search + `params`)

**Files:**
- Create: `frontend/src/components/InventoryItemPicker.svelte`
- Delete: `frontend/src/components/PriceListItemPicker.svelte`
- Create: `frontend/tests/components/InventoryItemPicker.test.js`
- Delete: `frontend/tests/components/PriceListItemPicker.test.js`

**Interfaces:**
- Produces: `<InventoryItemPicker value selectedItem onSelect params disabled />`. Keeps the existing props (`value`, `selectedItem`, `onSelect`, `disabled`) and **adds `params`** (object of extra fixed query filters). `onSelect(fullRow|null)` unchanged (consumers read description/units/price/etc.). Offers a "None (freeform)" option via the base `header` snippet. Searches `/api/inventory/?search=<q>&page_size=10` merged with `params`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/InventoryItemPicker.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import InventoryItemPicker from '@/components/InventoryItemPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('InventoryItemPicker', () => {
  it('server-searches with params and emits the full row', async () => {
    api.get.mockResolvedValue({ results: [
      { inventory_item_id: 2, code: 'BOLT-14', description: 'Hex bolt', units: 'each', selling_price: '0.10' },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(InventoryItemPicker, {
      props: { onSelect, params: { is_active: true } },
    });
    await fireEvent.input(getByPlaceholderText(/price list|inventory/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/inventory/?search=bolt'));
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('is_active=true'));
    await fireEvent.click(await findByRole('button', { name: /BOLT-14/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ inventory_item_id: 2, units: 'each' }));
  });

  it('offers a freeform option that emits null', async () => {
    api.get.mockResolvedValue({ results: [] }); // dropdown opens even with no matches
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(InventoryItemPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/price list|inventory/i), { target: { value: 'x' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /freeform/i }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- InventoryItemPicker`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/InventoryItemPicker.svelte`:

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null, onSelect = () => {},
        params = {}, disabled = false } = $props();
  const label = (i) => `${i.code} — ${i.description ?? ''}`;
  function buildQuery(q) {
    const usp = new URLSearchParams({ search: q, page_size: '10' });
    for (const [k, v] of Object.entries(params)) usp.set(k, String(v));
    return usp.toString();
  }
  const search = (q) =>
    api.get(`/api/inventory/?${buildQuery(q)}`).then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/inventory/${id}/`).then(label).catch(() => null);
  function freeform(close) { close(); value = null; onSelect(null); }
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(i) => { value = i.inventory_item_id; onSelect(i); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search price list items…">
  {#snippet header(close)}
    <li><button type="button" onmousedown={() => freeform(close)}>None (freeform)</button></li>
  {/snippet}
</SearchPicker>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- InventoryItemPicker`
Expected: PASS (2 tests).

- [ ] **Step 5: Delete the old component and its test**

```bash
git rm frontend/src/components/PriceListItemPicker.svelte frontend/tests/components/PriceListItemPicker.test.js
```

> Consumers still import `PriceListItemPicker` — they are repointed in Task 15. Do not run the full suite expecting green until Task 15. The InventoryItemPicker test above passes in isolation.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/InventoryItemPicker.svelte frontend/tests/components/InventoryItemPicker.test.js
git commit -m "refactor(spa): rename PriceListItemPicker -> InventoryItemPicker, server search + params"
```

---

## Task 11: Rewrite `CustomerPicker.svelte` on the base

**Files:**
- Modify: `frontend/src/components/CustomerPicker.svelte` (full replace)
- Modify: `frontend/tests/components/CustomerPicker.test.js`

**Interfaces:**
- Produces: `<CustomerPicker bind:value onSelect />`. **Output unchanged:** `value` = `{type:'business'|'contact', id}` | null; `onSelect({type,id}|null)`. Internally rides `SearchPicker` with a dual-source `search` that merges businesses + contacts.

- [ ] **Step 1: Update the test**

Replace `frontend/tests/components/CustomerPicker.test.js` with:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import CustomerPicker from '@/components/CustomerPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('CustomerPicker', () => {
  it('merges businesses and contacts and emits {type,id}', async () => {
    api.get.mockImplementation((url) =>
      url.includes('/businesses/')
        ? Promise.resolve({ results: [{ business_id: 5, business_name: 'Acme' }] })
        : Promise.resolve({ results: [{ contact_id: 3, name: 'Pat', business: { business_name: 'Acme' } }] }));
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(CustomerPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme \(business\)/ }));
    expect(onSelect).toHaveBeenCalledWith({ type: 'business', id: 5 });
  });
});
```

- [ ] **Step 2: Run the test (parity baseline)**

This is a behavior-preserving rewrite, so the test encodes the `{type,id}` contract rather than a new failing behavior. Run it against the **current** component first:

Run: `npm run test:run -- CustomerPicker`
Expected: PASS against the old component if the contract matches (it should — same `{type,id}` output and placeholder). If the old test used a different placeholder/markup, this new test may fail until Step 3; either way, the goal is green after the rewrite. Proceed to Step 3 and keep it green.

- [ ] **Step 3: Replace the component**

Replace `frontend/src/components/CustomerPicker.svelte` with:

```svelte
<script>
  // Dual-source picker (business OR contact). Keeps its own {type,id} output;
  // only the search/emit differ from the single-model pickers — the behavior
  // is shared via SearchPicker.
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), onSelect = () => {}, disabled = false } = $props();

  const rowLabel = (r) => r.label;
  const search = async (q) => {
    const [biz, con] = await Promise.all([
      api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=10`),
      api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`),
    ]);
    const bRows = (biz.results || biz).map((b) => ({
      type: 'business', id: b.business_id, label: `${b.business_name} (business)` }));
    const cRows = (con.results || con).map((c) => ({
      type: 'contact', id: c.contact_id,
      label: `${c.business ? `${c.name} — ${c.business.business_name}` : c.name} (contact)` }));
    return [...bRows, ...cRows];
  };
  const resolveLabel = (v) => {
    if (!v) return Promise.resolve(null);
    const url = v.type === 'business'
      ? `/api/businesses/${v.id}/` : `/api/contacts/${v.id}/`;
    return api.get(url).then((o) => v.type === 'business'
      ? `${o.business_name} (business)`
      : `${o.business ? `${o.name} — ${o.business.business_name}` : o.name} (contact)`)
      .catch(() => null);
  };
</script>

<SearchPicker bind:value {search} {resolveLabel} {rowLabel}
  onPick={(r) => { value = { type: r.type, id: r.id }; onSelect(value); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search customer or vendor…" />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- CustomerPicker`
Expected: PASS.

- [ ] **Step 5: Confirm consumers unaffected**

`InvoiceListPage` and `BillListPage` use `<CustomerPicker bind:value onSelect>` and read `{type,id}` — unchanged. Run their tests if present.

Run: `npm run test:run`
Expected: PASS for CustomerPicker, InvoiceList, BillList (job/inventory consumers still pending Tasks 13/15).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CustomerPicker.svelte frontend/tests/components/CustomerPicker.test.js
git commit -m "refactor(spa): rebuild CustomerPicker on SearchPicker (same {type,id} output)"
```

---

## Task 12: Migrate `BusinessPicker` into the PO form, Bill form, and Contact form

**Files:**
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderForm.svelte`
- Modify: `frontend/src/routes/bills/BillFormPage.svelte`
- Modify: `frontend/src/components/contacts/ContactForm.svelte`

**Interfaces:**
- Consumes: `BusinessPicker` (Task 5). The contact `<select>` stays a business-scoped pulldown in all three; only the **business** field becomes a picker.

- [ ] **Step 1: PurchaseOrderForm — replace the business `<select>`**

In `PurchaseOrderForm.svelte`:
- Add `import BusinessPicker from '../BusinessPicker.svelte';` at the top of the script.
- Replace the business `<p>…<select id="business">…</select></p>` block (lines ~94-102) with:

```svelte
  <p>
    <label><strong>Vendor (Business) *</strong></label><br>
    <BusinessPicker bind:value={form.business}
      selectedItem={po?.business_detail ?? null}
      onSelect={(b) => { pickedBusiness = b; fetchContactsAndAutoSelect(form.business, true); }} />
  </p>
```

- The existing `$effect` that watches `form.business` and calls `fetchContactsAndAutoSelect` still fires when the picker assigns `form.business`, so the `onSelect` call above is belt-and-suspenders; keep both — the effect is the load trigger, `onSelect` captures the picked row for the default-contact lookup.
- Replace `getDefaultContactId` so it prefers the picked business object (which carries `default_contact`) and falls back to the `businesses` prop:

```javascript
  let pickedBusiness = $state(null);
  function getDefaultContactId(businessId) {
    if (pickedBusiness && String(pickedBusiness.business_id) === String(businessId)) {
      return pickedBusiness.default_contact || null;
    }
    const biz = businesses.find(b => String(b.business_id) === String(businessId));
    return biz?.default_contact || null;
  }
```

> The `businesses` prop is now only a fallback for edit-mode default-contact lookup; leave the prop in place (the parent still passes it) — removing it is out of scope.

- [ ] **Step 2: BillFormPage — replace the business `<select>`**

In `BillFormPage.svelte`:
- Add `import BusinessPicker from '../../components/BusinessPicker.svelte';`.
- Replace the business `<select id="business">…</select>` with:

```svelte
<BusinessPicker bind:value={form.business} disabled={!!contextPoId}
  onSelect={(b) => { /* trigger the existing contact-load for the chosen vendor */ }} />
```

- Wire `onSelect` (or the existing business-watching effect) to the page's existing contact-loading logic so the contact pulldown repopulates for the chosen vendor, mirroring `PurchaseOrderForm`. The contact `<select>` stays.

- [ ] **Step 3: ContactForm — replace the business `<select>`**

In `ContactForm.svelte`:
- Add `import BusinessPicker from '../BusinessPicker.svelte';`.
- Replace the business `<select id="business">…</select>` (lines ~111-115, inside the `<label>Business` block) with:

```svelte
<BusinessPicker bind:value={form.business} selectedItem={contact?.business_detail ?? null} />
```

- `form.business` is submitted as-is (the existing `handleSubmit` already maps `'' → null`; the picker uses `null` for empty, which is fine — adjust the guard to `if (data.business === '' || data.business == null) data.business = null;`).

- [ ] **Step 4: Run the suites**

Run: `npm run test:run`
Expected: PASS for contacts/PO/bill form tests (or no regressions). If a form test asserted the old `<select>` options, update it to assert the `BusinessPicker` presence (query by the picker's placeholder).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/purchaseorders/PurchaseOrderForm.svelte frontend/src/routes/bills/BillFormPage.svelte frontend/src/components/contacts/ContactForm.svelte
git commit -m "feat(spa): use BusinessPicker for vendor/business fields in PO/Bill/Contact forms"
```

---

## Task 13: Refactor JobPicker consumers to the new id contract

**Files:**
- Modify: `frontend/src/components/expenses/ExpenseForm.svelte`
- Modify: `frontend/src/components/purchaseorders/LineItemForm.svelte`
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`

**Interfaces:**
- Consumes: `JobPicker` (Task 6) — `value` is now `job_id`; full job comes via `onSelect`. Each consumer stops round-tripping `{job_id, job_number}`.

- [ ] **Step 1: ExpenseForm**

In `ExpenseForm.svelte` (currently `jobSel = {job_id, job_number}`, `jobId = $derived(jobSel?.job_id)`, `<JobPicker bind:value={jobSel} />`):
- Replace the selection state with an id + a captured row:

```javascript
  let jobId = $state(expense?.job ?? null);
  let jobRow = $state(expense?.job ? { job_id: expense.job, job_number: expense.job_number, name: expense?.job_name } : null);
```

- Replace the picker usage:

```svelte
<JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={(j) => { jobRow = j; }} />
```

- Replace any remaining `jobSel?.job_id` reads with `jobId`, and `payload.new_material = { ...newMaterial, job_id: jobId }` stays valid.

- [ ] **Step 2: PO LineItemForm**

In `LineItemForm.svelte` (currently `selectedJob = defaultJob` as `{job_id,…}`, reads `selectedJob?.job_id`):
- Change to an id + row:

```javascript
  let jobId = $state(defaultJob?.job_id ?? null);
  let jobRow = $state(defaultJob ?? null);
```

- Replace the picker:

```svelte
<JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={(j) => { jobRow = j; }} />
```

- Replace `if (selectedJob?.job_id) data.job = selectedJob.job_id;` with `if (jobId) data.job = jobId;`.

- [ ] **Step 3: PurchaseOrderDetail**

In `PurchaseOrderDetail.svelte` (two `<JobPicker>` usages: `editForm.job` and `changeJobPick`, both `{job_id, job_number}`):
- For each, switch the bound variable to an id and keep a row for prefill. Example for the inline edit row:

```javascript
  // was: changeJobPick = li.effective_job_id ? { job_id, job_number } : null;
  let changeJobId = $state(null);
  let changeJobRow = $state(null);
  // when opening: changeJobId = li.effective_job_id ?? null;
  //               changeJobRow = li.effective_job_id ? { job_id: li.effective_job_id, job_number: li.effective_job_number } : null;
```

```svelte
<JobPicker bind:value={changeJobId} selectedItem={changeJobRow} onSelect={(j) => { changeJobRow = j; }} />
```

- Update the change submit (currently `changeJobPick?.job_id ?? null`) to `changeJobId ?? null`, and the `editForm.job` read (`editForm.job?.job_id ?? null`) to the new `editForm`-side id variable. Apply the same pattern to the `editForm.job` `<JobPicker>` usage (introduce `editJobId`/`editJobRow`, bind value to `editJobId`, and read `editJobId` where `editForm.job?.job_id` was read).

- [ ] **Step 4: Run the suites**

Run: `npm run test:run`
Expected: PASS for ExpenseForm and PO detail tests (update any that asserted the old `{job_id, job_number}` binding to set/read the id + `selectedItem`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/expenses/ExpenseForm.svelte frontend/src/components/purchaseorders/LineItemForm.svelte frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte
git commit -m "refactor(spa): adopt JobPicker id contract in expense/PO-line/PO-detail"
```

---

## Task 14: Migrate the three email-association pages to pickers

**Files:**
- Modify: `frontend/src/routes/email/EmailAssociatePage.svelte` (job)
- Modify: `frontend/src/routes/email/EmailAssociatePOPage.svelte` (PO)
- Modify: `frontend/src/routes/email/EmailAssociateBillPage.svelte` (bill)

**Interfaces:**
- Consumes: `JobPicker` (Task 6), `PurchaseOrderPicker` (Task 8), `BillPicker` (Task 9). Each page drops its bulk `?page_size=500` list load.

- [ ] **Step 1: EmailAssociatePage (job)**

In `EmailAssociatePage.svelte`:
- Add `import JobPicker from '../../components/JobPicker.svelte';`.
- Remove `let jobs = $state([])` and the `api.get('/api/jobs/?page_size=500')` call from `load()` (load only the email now): change the `Promise.all` to just `email = await emailApi.get(params.id);`.
- `selectedJobId` becomes the picked id (number). Replace the `<select id="job_id">…</select>` block with:

```svelte
<label><strong>Job *</strong></label><br>
<JobPicker bind:value={selectedJobId} />
```

- The submit guard `if (!selectedJobId)` and `emailApi.linkToJob(params.id, selectedJobId)` both still work with a numeric id.

- [ ] **Step 2: EmailAssociatePOPage (PO)**

In `EmailAssociatePOPage.svelte` (same shape as the job page, with `pos`/`selectedPoId` and `linkToPurchaseOrder` or equivalent):
- Add `import PurchaseOrderPicker from '../../components/PurchaseOrderPicker.svelte';`.
- Remove the bulk PO list load and the `pos` state.
- Replace the `<select id="po_id">…</select>` with:

```svelte
<label><strong>Purchase Order *</strong></label><br>
<PurchaseOrderPicker bind:value={selectedPoId} />
```

- Keep the existing required-guard and submit call (numeric id).

- [ ] **Step 3: EmailAssociateBillPage (bill)**

In `EmailAssociateBillPage.svelte`:
- Add `import BillPicker from '../../components/BillPicker.svelte';`.
- Remove the bulk bill list load and the `bills` state.
- Replace the `<select id="bill_id">…</select>` with:

```svelte
<label><strong>Bill *</strong></label><br>
<BillPicker bind:value={selectedBillId} />
```

- Keep the required-guard and submit call.

- [ ] **Step 4: Run the suite**

Run: `npm run test:run`
Expected: PASS. Update any email-associate page test that populated/queried the old `<select>` to drive the picker (input + click a mocked result).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/email/EmailAssociatePage.svelte frontend/src/routes/email/EmailAssociatePOPage.svelte frontend/src/routes/email/EmailAssociateBillPage.svelte
git commit -m "feat(spa): use type-ahead pickers on the email-association pages (drop page_size=500)"
```

---

## Task 15: Repoint the five InventoryItemPicker consumers

**Files:**
- Modify: `frontend/src/components/LineItemModal.svelte`
- Modify: `frontend/src/components/MaterialModal.svelte`
- Modify: `frontend/src/components/PlanMaterialModal.svelte`
- Modify: `frontend/src/components/expenses/MaterialPicker.svelte`
- Modify: `frontend/src/components/purchaseorders/LineItemForm.svelte`

**Interfaces:**
- Consumes: `InventoryItemPicker` (Task 10). The `onSelect(fullRow)` and `selectedItem` props are unchanged, so consumers only swap the import + tag name. Where a consumer previously relied on the picker loading all `is_active=true` items, pass `params={{ is_active: true }}` to preserve that scoping.

- [ ] **Step 1: Swap import + tag in each consumer**

In each of the five files:
- Change `import PriceListItemPicker from '...';` to `import InventoryItemPicker from '<correct relative path>/InventoryItemPicker.svelte';` (same directory depth as the old import).
- Change `<PriceListItemPicker ... />` to `<InventoryItemPicker ... />`.
- If the old usage depended on active-only items (the previous component fetched `?is_active=true`), add `params={{ is_active: true }}` to the tag.

Example (MaterialPicker.svelte):

```svelte
<InventoryItemPicker onSelect={onPli} params={{ is_active: true }} />
```

- [ ] **Step 2: Run the related suites**

Run: `npm run test:run -- LineItemModal MaterialModal PlanMaterialModal`
Expected: PASS. These tests mock the API; update any that asserted the old bulk `?page_size=9999` call to expect the `?search=` call shape, or that referenced `PriceListItemPicker` by name.

- [ ] **Step 3: Run the full suite**

Run: `npm run test:run`
Expected: PASS — no remaining references to `PriceListItemPicker`.

Verify with:

```bash
grep -rn "PriceListItemPicker" frontend/src frontend/tests
```

Expected: no results.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/LineItemModal.svelte frontend/src/components/MaterialModal.svelte frontend/src/components/PlanMaterialModal.svelte frontend/src/components/expenses/MaterialPicker.svelte frontend/src/components/purchaseorders/LineItemForm.svelte
git commit -m "refactor(spa): repoint material/line-item pickers to InventoryItemPicker"
```

---

## Task 16: Documentation + LATER.md

**Files:**
- Modify: `docs/designs/architecture-and-conventions.md`
- Modify: `docs/designs/jobs-tasks-and-worksheets.md`
- Modify: `docs/designs/materials-inventory-and-purchasing.md`
- Modify: `docs/designs/LATER.md`

- [ ] **Step 1: Document the picker pattern**

In `architecture-and-conventions.md`, under the server-side `?search=` / type-ahead note, add a short subsection describing `SearchPicker` (the behavior core), the per-entity pickers, and the shared contract (`value`=id, `selectedItem` prefill, `onSelect(fullRow)`; `CustomerPicker` keeps `{type,id}`).

- [ ] **Step 2: Update picker references in domain docs**

In `jobs-tasks-and-worksheets.md` (the `ContactPicker`/`JobPicker` references, e.g. the Customer-field and `LineItemForm` notes) and `materials-inventory-and-purchasing.md` (the `PriceListItemPicker` row), update the component names and note they ride `SearchPicker`. Replace any "client-side filter; server-side `?search=` is a future option" wording for inventory with "server-side `?search=`".

- [ ] **Step 3: Close the delivered LATER.md notes**

In `LATER.md`, remove (or trim to only the remaining merge-UX-rework portion):
- "Email-association pickers cap the dropdown at 100 entries" — delivered (all three now type-ahead).
- "Link-email Job picker is an oversized `<select>`" — delivered.
- "Consolidate the customer/contact pickers around `CustomerPicker`" — superseded by the `SearchPicker` consolidation; record that outcome.
- The inventory-merge note: keep it, but delete the "use the search/typeahead picker the other notes call for" clause that this work satisfies, leaving the row-driven-selection + preview rework.

- [ ] **Step 4: Commit**

```bash
git add docs/designs/architecture-and-conventions.md docs/designs/jobs-tasks-and-worksheets.md docs/designs/materials-inventory-and-purchasing.md docs/designs/LATER.md
git commit -m "docs: document SearchPicker pattern; close delivered picker LATER notes"
```

---

## Final verification

- [ ] **Backend:** `python manage.py test tests.test_api_purchasing tests.test_api_bill_list tests.test_api_inventory` → all PASS.
- [ ] **Frontend:** from `frontend/`, `npm run test:run` → all PASS.
- [ ] **Grep:** `grep -rn "PriceListItemPicker\|page_size=500\|page_size=9999" frontend/src` → no results (the bulk loads and old name are gone).
- [ ] **Manual smoke (user-run):** new PO form, new Bill form, the three email-association pages, a material modal, and the invoice/bill customer filters all search-as-you-type and select correctly.
