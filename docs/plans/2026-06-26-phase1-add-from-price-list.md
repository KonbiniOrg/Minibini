# Phase 1 — "Add from Price List" picker on the Plan (build view)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the worksheet's two separate primitive add-buttons ("Add Manual
Task" and "Add Material") with a single **"Add from Price List"** picker — a
**type-ahead** over ServiceItems + catalog InventoryItems, in one **untagged** list
(no visible Service/Material badges — selection just creates the right atom), that
routes into the *existing* PlanTask / PlanMaterial forms. A **freeform-material**
option inside the picker preserves adding a material that isn't in the inventory
list. Keep templates as a second action ("Add from Template").

**Architecture:** Frontend-only. The backend endpoints for creating PlanTasks and
PlanMaterials already exist and are unchanged. A new `PriceListPicker.svelte`
fetches both catalogs, merges them into one **untagged type-ahead** list, and on
selection opens the existing `WorkItemForm` (for a ServiceItem → PlanTask) or
`PlanMaterialModal` (for an InventoryItem → PlanMaterial), pre-seeded with the
chosen catalog item so the user doesn't pick twice. The picker tracks the item's
`kind` only to route the selection — it is never shown to the user. This realizes the design draft's "two-level add surface"
(presets vs primitives) — see `docs/plans/2026-06-24-planning-billing-consolidation-draft.md` §8.

**Tech Stack:** Svelte 5 (runes: `$state`/`$derived`/`$effect`/`$props`), Vite,
`frontend/src/lib/api.js` client, Vitest + @testing-library/svelte
(`frontend/tests/`).

## Global Constraints

- **No backend changes in this phase.** No new endpoints, serializers, migrations,
  or model edits. (If you think you need one, stop and flag it — the design intent
  is an explicitly front-end consolidation.)
- **Never write the dev database.** Run only `npm run test:run` from `frontend/`.
  Do not run `manage.py`, the dev server, or any DB-touching command.
- **Svelte 5 runes only** (`$state`, `$derived`, `$effect`, `$props`). Match the
  conventions of the sibling components you touch — read them first.
- **api.js usage:** `api.get(url)` returns parsed JSON; list endpoints may return a
  paginated shape (`{results, count, next, previous}`) **or** a bare array — handle
  both with `resp.results || resp` (this is the established pattern, e.g.
  `WorkItemForm.svelte:35`).
- **ServiceItem picker must exclude adjustments:** request
  `/api/service-items/?task_applicable=true` (excludes the `PERCENTAGE` algorithm —
  those are adjustments, never addable as work).
- **InventoryItem picker shows catalog items only:** the price list is for quoting,
  so show rows where `is_catalog === true` (filter client-side on the serialized
  `is_catalog` field; the serializer returns it — `apps/api/inventory/serializers.py`).
- **Links navigate; buttons act.** The picker and its actions are `<button>`s.
- **Saves stay explicit** — the picker only *selects*; the opened form's existing
  Save button commits. Do not auto-save on pick.
- **No CSS frameworks** — per-component `<style>`, semantic HTML. Wrap `<tr>` in
  `<tbody>` (Svelte 5 strict mode).
- **Vitest, never watch mode.** Run a single file with
  `npm run test:run -- <path>` from `frontend/`. See `docs/designs/frontend-testing.md`.

## Reference: what exists today (read these before starting)

- `frontend/src/routes/worksheets/WorksheetDetailPage.svelte` — the Plan page.
  Buttons at ~lines 276–278: **"Add Task From Template"** (`openAddTemplateTask()`
  ~L116), **"Add Manual Task"** (`openAddManualTask()` ~L110), **"Add Material"**
  (`openAddMaterial()` ~L144). Renders `WorkItemForm` (~L352–362) and
  `PlanMaterialModal` (~L364–373).
- `frontend/src/components/WorkItemForm.svelte` — modes `'manual'` / `'template'`.
  Manual mode loads ServiceItems (~L33–40), has a service `<select>`, a modifier
  checkbox `<fieldset>` (~L284–299), and fields name/description/est_qty/
  est_worker_time. Saves via `POST /api/est-worksheets/{contextId}/tasks/` (~L203).
- `frontend/src/components/PlanMaterialModal.svelte` — picks an InventoryItem (via
  `InventoryItemPicker.svelte`) or freeform; saves via
  `POST /api/est-worksheets/{worksheetId}/plan-materials/` (~L148).
- `frontend/src/components/InventoryItemPicker.svelte` — existing search picker over
  `/api/inventory/` (uses `search` + `page_size`); model the new picker's inventory
  query and search UX on it.
- Endpoints (unchanged): `GET /api/service-items/?task_applicable=true`,
  `GET /api/inventory/?is_active=true&search=…&page_size=…`,
  `POST /api/est-worksheets/{id}/tasks/`,
  `POST /api/est-worksheets/{id}/plan-materials/`.
- ServiceItem serialized fields: `service_item_id, name, description, algorithm,
  rate, unit_label, modifiers, accounting_category`. InventoryItem:
  `inventory_item_id, code, description, units, selling_price, is_catalog,
  accounting_category, …`.

---

## Task 1: `PriceListPicker.svelte` — the unified type-ahead picker (untagged)

A modal that fetches ServiceItems (task-applicable) + catalog InventoryItems and
presents them as **one untagged type-ahead list** (autofocused search input;
matches narrow as you type; list open while the modal is open, so it's browsable on
focus). Rows show name + description + price — **no Service/Material badge**. It
emits the chosen item along with its `kind` (used by the caller to route, never
displayed). Includes a **"Freeform material"** action for adding a material that
isn't in the inventory list.

**Files:**
- Create: `frontend/src/components/PriceListPicker.svelte`
- Test: `frontend/tests/components/PriceListPicker.test.js`

**Interfaces:**
- Props (`$props`): `{ open = false, onselect, onfreeform, onclose }`.
- Produces — `onselect(payload)` where
  `payload = { kind: 'service', item: <serviceItem> }` or
  `{ kind: 'material', item: <inventoryItem> }`. `onfreeform()` for the freeform
  material action. `onclose()` to dismiss.
- Consumes — `api.get('/api/service-items/?task_applicable=true')` and
  `api.get('/api/inventory/?is_active=true')` (both via `resp.results || resp`),
  filtering inventory to `is_catalog === true`.

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/components/PriceListPicker.test.js
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import PriceListPicker from '../../src/components/PriceListPicker.svelte';
import { api } from '../../src/lib/api.js';

vi.mock('../../src/lib/api.js', () => ({ api: { get: vi.fn() } }));

const SERVICES = [
  { service_item_id: 1, name: 'CNC Cutting', algorithm: 'ELAPSED_TIME', rate: '90.00', unit_label: 'hr' },
  { service_item_id: 2, name: 'Design Fee', algorithm: 'FLAT_FEE', rate: '150.00', unit_label: 'ea' },
];
const INVENTORY = [
  { inventory_item_id: 10, code: 'MDF-3-4', description: '3/4 MDF sheet', selling_price: '42.00', is_catalog: true },
  { inventory_item_id: 11, code: 'LOT-XYZ', description: 'transient lot', selling_price: '5.00', is_catalog: false },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) =>
    Promise.resolve(url.includes('service-items') ? SERVICES : INVENTORY)
  );
});

describe('PriceListPicker', () => {
  it('lists services and catalog materials in one untagged list, excludes non-catalog', async () => {
    render(PriceListPicker, { open: true });
    expect(await screen.findByText('CNC Cutting')).toBeInTheDocument();
    expect(screen.getByText('MDF-3-4')).toBeInTheDocument();
    // non-catalog inventory is hidden
    expect(screen.queryByText('LOT-XYZ')).not.toBeInTheDocument();
    // no visible type badge on rows — picker routes by kind behind the scenes
    expect(screen.queryByText(/^service$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^material$/i)).not.toBeInTheDocument();
  });

  it('requests task-applicable services (excludes adjustments)', async () => {
    render(PriceListPicker, { open: true });
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('task_applicable=true'))
    );
  });

  it('filters the merged list by the search box', async () => {
    render(PriceListPicker, { open: true });
    await screen.findByText('CNC Cutting');
    await fireEvent.input(screen.getByPlaceholderText(/search/i), { target: { value: 'mdf' } });
    expect(screen.queryByText('CNC Cutting')).not.toBeInTheDocument();
    expect(screen.getByText('MDF-3-4')).toBeInTheDocument();
  });

  it('emits onselect with kind+item when a row is chosen', async () => {
    const onselect = vi.fn();
    render(PriceListPicker, { open: true, onselect });
    await fireEvent.click(await screen.findByText('CNC Cutting'));
    expect(onselect).toHaveBeenCalledWith({ kind: 'service', item: expect.objectContaining({ service_item_id: 1 }) });
  });

  it('emits onfreeform for the freeform material action', async () => {
    const onfreeform = vi.fn();
    render(PriceListPicker, { open: true, onfreeform });
    await fireEvent.click(await screen.findByRole('button', { name: /freeform material/i }));
    expect(onfreeform).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `cd frontend && npm run test:run -- tests/components/PriceListPicker.test.js`
Expected: FAIL — module `PriceListPicker.svelte` does not exist.

- [ ] **Step 3: Implement `PriceListPicker.svelte`**

Build the component to satisfy the test. Match sibling conventions (read
`InventoryItemPicker.svelte` and `WorkItemForm.svelte` first for the modal shell,
`$state` usage, and the `resp.results || resp` pattern). Shape:

```svelte
<script>
  import { api } from '../lib/api.js';

  let { open = false, onselect, onfreeform, onclose } = $props();

  let services = $state([]);
  let materials = $state([]);
  let q = $state('');
  let loaded = $state(false);

  async function load() {
    const [svc, inv] = await Promise.all([
      api.get('/api/service-items/?task_applicable=true'),
      api.get('/api/inventory/?is_active=true'),
    ]);
    services = (svc.results || svc).map((s) => ({
      kind: 'service', id: s.service_item_id, label: s.name,
      sub: s.description || '', price: s.rate, item: s,
    }));
    materials = (inv.results || inv)
      .filter((m) => m.is_catalog)
      .map((m) => ({
        kind: 'material', id: m.inventory_item_id, label: m.code,
        sub: m.description || '', price: m.selling_price, item: m,
      }));
    loaded = true;
  }

  $effect(() => { if (open && !loaded) load(); });

  const rows = $derived(
    [...services, ...materials].filter((r) => {
      const t = q.trim().toLowerCase();
      return !t || r.label.toLowerCase().includes(t) || r.sub.toLowerCase().includes(t);
    })
  );
</script>

{#if open}
  <div class="overlay" role="dialog" aria-label="Add from Price List">
    <header>
      <h2>Add from Price List</h2>
      <button onclick={() => onclose?.()}>Close</button>
    </header>
    <!-- type-ahead: autofocus; the list below narrows as you type -->
    <!-- svelte-ignore a11y_autofocus -->
    <input type="search" placeholder="Search price list…" bind:value={q} autofocus />
    <ul>
      {#each rows as r (r.kind + r.id)}
        <li>
          <button onclick={() => onselect?.({ kind: r.kind, item: r.item })}>
            <span class="label">{r.label}</span>
            <span class="sub">{r.sub}</span>
            <span class="price">{r.price}</span>
          </button>
        </li>
      {/each}
    </ul>
    <footer>
      <button onclick={() => onfreeform?.()}>+ Freeform material</button>
    </footer>
  </div>
{/if}

<style>
  /* per-component styles; follow the look of existing modals/pickers */
</style>
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `cd frontend && npm run test:run -- tests/components/PriceListPicker.test.js`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PriceListPicker.svelte frontend/tests/components/PriceListPicker.test.js
git commit -m "feat(worksheet): PriceListPicker — unified tagged service+material picker"
```

---

## Task 2: `WorkItemForm` accepts a pre-selected ServiceItem (manual mode)

So the picker drives the service choice and the form goes straight to the follow-up
fields (name, qty, modifiers, time) instead of showing its own service `<select>`.

**Files:**
- Modify: `frontend/src/components/WorkItemForm.svelte`
- Test: `frontend/tests/components/WorkItemForm.test.js` (create if absent)

**Interfaces:**
- Add prop `serviceItem` (a full ServiceItem object, optional). When provided in
  `'manual'` mode: pre-select it (drive `service_item`, its modifier menu, and
  `unit_label`), and **hide the internal service `<select>`**, showing the chosen
  service as a read-only header instead. When absent: behave exactly as today.
- `'template'` mode is unchanged.

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/components/WorkItemForm.test.js
import { render, screen } from '@testing-library/svelte';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import WorkItemForm from '../../src/components/WorkItemForm.svelte';
import { api } from '../../src/lib/api.js';

vi.mock('../../src/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue([]); });

const SERVICE = {
  service_item_id: 1, name: 'CNC Cutting', algorithm: 'ELAPSED_TIME',
  rate: '90.00', unit_label: 'hr',
  modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
};

describe('WorkItemForm with a pre-selected serviceItem', () => {
  it('shows the chosen service as a header and hides the service selector', async () => {
    render(WorkItemForm, { mode: 'manual', context: 'worksheet', contextId: 5, serviceItem: SERVICE });
    expect(await screen.findByText(/CNC Cutting/)).toBeInTheDocument();
    // the internal service <select> should not be rendered when pre-seeded
    expect(screen.queryByLabelText(/service item/i)).not.toBeInTheDocument();
  });

  it('renders the pre-selected service’s modifier choices', async () => {
    render(WorkItemForm, { mode: 'manual', context: 'worksheet', contextId: 5, serviceItem: SERVICE });
    expect(await screen.findByText(/Rush/)).toBeInTheDocument();
  });
});
```

(Adjust the `queryByLabelText`/role selectors to match the actual label text in
`WorkItemForm.svelte` — read the file and use its real labels.)

- [ ] **Step 2: Run, confirm it fails** —
  `cd frontend && npm run test:run -- tests/components/WorkItemForm.test.js`
  Expected: FAIL (header text / hidden select assertion).

- [ ] **Step 3: Implement** — add the `serviceItem` prop; when set in manual mode,
  initialize the form's `service_item`, modifier menu, and `unit_label` from it,
  branch the template so the service `<select>` is replaced by a read-only
  "Service: {name}" header. Leave all save logic and template mode untouched.

- [ ] **Step 4: Run, confirm pass.**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/WorkItemForm.svelte frontend/tests/components/WorkItemForm.test.js
git commit -m "feat(worksheet): WorkItemForm accepts a pre-selected serviceItem"
```

---

## Task 3: `PlanMaterialModal` accepts a pre-selected InventoryItem

So picking a material in the price list opens the modal already bound to that
catalog item (price/desc/units pre-filled from it), without re-picking.

**Files:**
- Modify: `frontend/src/components/PlanMaterialModal.svelte`
- Test: `frontend/tests/components/PlanMaterialModal.test.js` (create if absent)

**Interfaces:**
- Add prop `inventoryItem` (a full InventoryItem object, optional). When provided:
  pre-bind it as the modal's `inventory_item`, pre-fill `description`/`units`/
  `sell_price`/`unit_cost`/`accounting_category` from it, and skip/hide the internal
  `InventoryItemPicker`. When absent: behave exactly as today (freeform / internal
  picker), so the existing per-task "+mat" path and the "Freeform material" action
  keep working.

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/components/PlanMaterialModal.test.js
import { render, screen } from '@testing-library/svelte';
import { vi, describe, it, expect } from 'vitest';
import PlanMaterialModal from '../../src/components/PlanMaterialModal.svelte';

vi.mock('../../src/lib/api.js', () => ({ api: { get: vi.fn().mockResolvedValue([]), post: vi.fn() } }));

const PLI = {
  inventory_item_id: 10, code: 'MDF-3-4', description: '3/4 MDF sheet',
  units: 'sheet', selling_price: '42.00', purchase_price: '30.00', is_catalog: true,
};

describe('PlanMaterialModal with a pre-selected inventoryItem', () => {
  it('pre-fills from the catalog item and hides the picker', async () => {
    render(PlanMaterialModal, { open: true, worksheetId: 5, inventoryItem: PLI });
    expect(await screen.findByDisplayValue('3/4 MDF sheet')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/search inventory/i)).not.toBeInTheDocument();
  });
});
```

(Match the real prop names — the explore shows the modal takes a worksheet id; read
`PlanMaterialModal.svelte` and `WorksheetDetailPage.svelte:364-373` for the exact
prop names it’s rendered with, and align the test.)

- [ ] **Step 2: Run, confirm it fails.**
- [ ] **Step 3: Implement** the `inventoryItem` prop pre-fill + hide-picker branch.
- [ ] **Step 4: Run, confirm pass.**
- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PlanMaterialModal.svelte frontend/tests/components/PlanMaterialModal.test.js
git commit -m "feat(worksheet): PlanMaterialModal accepts a pre-selected inventoryItem"
```

---

## Task 4: Wire the picker into `WorksheetDetailPage` (the two-action surface)

Replace the two primitive buttons with one **"Add from Price List"** that opens the
picker and routes the selection into the seeded forms; keep/relabel the template
button as **"Add from Template."**

**Files:**
- Modify: `frontend/src/routes/worksheets/WorksheetDetailPage.svelte`
- Modify: `frontend/tests/components/worksheets/WorksheetDetailPage.test.js`

**Interfaces:**
- Consumes Tasks 1–3 (`PriceListPicker`, `WorkItemForm.serviceItem`,
  `PlanMaterialModal.inventoryItem`).
- Behavior: button row is now **[Add from Template] [Add from Price List]**.
  "Add from Price List" opens `PriceListPicker`; on `onselect`:
  - `kind: 'service'` → close picker, open `WorkItemForm` (mode `'manual'`,
    `serviceItem` = item).
  - `kind: 'material'` → close picker, open `PlanMaterialModal`
    (`inventoryItem` = item).
  - `onfreeform` → close picker, open `PlanMaterialModal` with no `inventoryItem`
    (today's freeform behavior).
  - The existing per-task "+mat" path and the template flow are unchanged (template
    button is just relabeled).

- [ ] **Step 1: Write the failing test** (extend the existing file)

```js
// add to frontend/tests/components/worksheets/WorksheetDetailPage.test.js
it('shows two add actions: Template and Price List (not Manual Task / Material)', async () => {
  // …render with a can_manage worksheet fixture as the existing tests do…
  expect(screen.getByRole('button', { name: /add from price list/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add from template/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /add manual task/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^add material$/i })).not.toBeInTheDocument();
});

it('opening Price List and choosing a service opens the task form seeded', async () => {
  // mock api.get to return one service; click Add from Price List → click the service row
  // assert the WorkItemForm header shows that service name (from Task 2 behavior)
});
```

(Follow the existing test's render/fixture/mocking setup — reuse its `can_manage`
worksheet fixture and api mocks. Fill in the second test body using the same
patterns as `PriceListPicker.test.js`.)

- [ ] **Step 2: Run, confirm it fails** —
  `cd frontend && npm run test:run -- tests/components/worksheets/WorksheetDetailPage.test.js`

- [ ] **Step 3: Implement** — in `WorksheetDetailPage.svelte`: remove the
  "Add Manual Task" and "Add Material" buttons; add an "Add from Price List" button
  that toggles `PriceListPicker` open; relabel "Add Task From Template" →
  "Add from Template". Add the `onselect`/`onfreeform` handlers that set the seed
  props and open the existing modals. Render `<PriceListPicker … />`. Keep
  `openAddTemplateTask`, the per-task material add, and all save wiring intact.

- [ ] **Step 4: Run, confirm pass** — that file, then the full suite:
  `cd frontend && npm run test:run`
  Expected: all green (no regressions in WorkItemForm / PlanMaterialModal / worksheet tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/worksheets/WorksheetDetailPage.svelte frontend/tests/components/worksheets/WorksheetDetailPage.test.js
git commit -m "feat(worksheet): two-action add surface — Add from Price List + Add from Template"
```

---

## Done-when

- The worksheet (Plan) page shows exactly two add actions: **Add from Template** and
  **Add from Price List**.
- "Add from Price List" is a **type-ahead** over ServiceItems (excluding
  PERCENTAGE) and catalog InventoryItems in **one untagged list** (no visible
  Service/Material badges), plus a **Freeform material** action for materials not in
  the inventory list.
- Choosing a service opens the task form pre-seeded (no second service pick);
  choosing a material opens the material modal pre-seeded; freeform opens the
  material modal as before.
- Existing save endpoints unchanged; full `npm run test:run` is green.
- No backend files changed.

## Out of scope (later phases — see the design draft §14)

- Auto-creating the Plan on estimate create; the Express scaffold-from-template path
  (Phase 2).
- Adding a **WorkTemplate** (multi-atom) to an existing worksheet (template flow here
  stays TaskTemplate-only).
- Routing the per-task "+mat" add through the picker (kept as-is for now).
- The Estimate-pillar toggle, the combined Tasks & Materials pillar, vocabulary
  rename, line-item slimming, invoicing — all later phases.
- The Fee atom and billing groups (deferred — design draft §15).
