# Implementation plan — Unified "Add-line" picker (two surfaces)

> **TDD implementation plan (frontend only).** This is the **third** of three
> sequenced plans behind
> `docs/plans/2026-07-02-add-line-crystallization-and-unified-picker.md` **Part 2**
> ("Two surfaces, one picker — no in-picker branching", the line-shape table,
> "Interaction design (settled with RM)"). Plans 1 & 2 (`is_material` +
> `service_item` on `EstimateLineItem`, `add_line_item_from_service`,
> `add_line_item_from_pli`, `add_line_item(is_material=…)`, and the
> `LineItemMixin` routing on `service_item`) are **assumed landed**. **No backend
> or model work here** — this plan touches only `frontend/`.
>
> Branch: `feature/unification`. Do **not** branch/worktree/commit — RM reviews and
> commits.

## Goal

Resurrect the orphaned `frontend/src/components/PriceListPicker.svelte` as a single,
**surface-agnostic selection emitter** and wire it into **two** surfaces:

1. **Estimate line-item authoring** (`EstimateDetailPage.svelte`) → maps a choice to
   the **deferred-descriptor** endpoints (a document line that crystallizes at
   acceptance).
2. **Job task-list authoring** (`JobTaskListPage.svelte`) → maps a choice to the
   **immediate-atom** endpoints (a real Task / Material / Fee now).

The picker itself carries **zero surface conditionals**. It searches both catalogs,
presents rows, and emits exactly one normalized callback per choice. Each surface
passes its own handler; only the **post-selection form** (estimate wants a *sell
price*; task-list wants *cost / establishment*) differs by surface.

## Architecture

```
                         ┌───────────────────────────────┐
                         │  PriceListPicker.svelte        │
                         │  (pure selection emitter)      │
   type-ahead search ───▶│  search: /api/service-items/   │
   (SearchPicker base)   │          /api/inventory/       │
                         │                                │
                         │  emits onChoose({...}):        │
                         │   {type:'service',  serviceItem}
                         │   {type:'inventory',inventoryItem}
                         │   {type:'freeform', typed, isMaterial}
                         └───────────────┬────────────────┘
                                         │  (one handler per surface, chosen at mount)
                 ┌───────────────────────┴────────────────────────┐
                 ▼                                                 ▼
   ESTIMATE surface handler                          TASK-LIST surface handler
   (EstimateDetailPage.svelte)                       (JobTaskListPage.svelte)
   post-selection form → POST                        routes choice to the existing,
   /api/estimates/{id}/line-items/                   already-tested modals, prefilled:
     service   → {service_item, qty}                   service   → WorkItemForm (template mode)
     inventory → {inventory_item, qty}                 inventory → MaterialModal (PLI-locked)
     freeform  → {description, qty, units,             freeform+material → MaterialModal (freeform)
                  price, accounting_category,          freeform+fee      → FeeModal
                  is_material}
```

**Why this split:** the shared, expensive part (search-all-catalogs + choose-the-type)
is one component with no `if (surface)` logic. The cheap, surface-specific part
(what a chosen thing *costs* / *sells for*, and which endpoint mints it) lives in the
two surface handlers. The task-list surface **reuses** the existing granular modals
(`WorkItemForm`, `MaterialModal`, `FeeModal`) so its cost/establishment forms and their
tests are unchanged — the picker just becomes a new front door that opens them
prefilled. The estimate surface gets a small dedicated post-selection form because its
add path (deferred descriptor) has no existing modal after `AddServiceItemModal` is
retired.

## Tech stack

- Svelte 5 runes (`$state` / `$derived` / `$props` / `$effect`), no CSS frameworks.
- Vitest + `@testing-library/svelte` (v5), jsdom. Run one-shot only:
  `cd frontend && npm run test:run` — **never** watch mode.
- API seam is `@/lib/api.js` (`api.get/post/patch/delete`). Mock the seam, never `fetch`.
- Existing shared base: `SearchPicker.svelte` (debounced search, dropdown, race-guarded
  prefill) — used unchanged.

## Global constraints (bake into every task)

- **TDD, strictly.** For each task: write the failing test first, run
  `npm run test:run <file>`, confirm it fails **for the expected reason**, write the
  minimal implementation, run again green, then stop. Show real test code — no
  placeholders.
- **Assert structure/outcomes, not copy** (query by role/placeholder/label; never
  snapshot). Rewording a label must not break a test.
- **`await` every `fireEvent`**; use `findBy*` / `waitFor` after anything async or after
  the 250ms `SearchPicker` debounce (`await new Promise((r) => setTimeout(r, 300))`).
- **UI Decisions (CLAUDE.md):** links navigate / buttons act; saves are explicit
  (no blur-only commit); confirm only for irreversible actions — adding/removing a draft
  line or opening a modal is reversible, so **no confirm dialogs** in this work.
- `<tr>` must live inside `<tbody>`/`<thead>`/`<tfoot>`.
- **Do not touch:** the estimate **wizard** ("Show Tasks & Materials"), **invoices**, or
  any backend/model file.

## File structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── PriceListPicker.svelte            ── REWRITE: emit onChoose; freeform "is material?" UX
│   │   ├── estimates/
│   │   │   ├── AddServiceItemModal.svelte    ── DELETE (retired; superseded by picker)
│   │   │   └── EstimateAddLineForm.svelte    ── NEW: estimate post-selection form
│   │   ├── MaterialModal.svelte              ── EDIT: + presetDescription, presetPli, defaultMaterialCategoryId
│   │   ├── FeeModal.svelte                   ── EDIT: add `presetDescription` prop
│   │   ├── WorkItemForm.svelte               ── (unchanged; already has presetTemplateId)
│   │   └── LineItemModal.svelte              ── (unchanged; kept for EDIT only)
│   └── routes/
│       ├── estimates/EstimateDetailPage.svelte  ── EDIT: swap add affordances → picker + form
│       └── jobs/JobTaskListPage.svelte          ── EDIT: replace 4 granular add buttons with one "Add Work" → picker + surface handler
└── tests/
    └── components/
        ├── PriceListPicker.test.js           ── REWRITE to onChoose contract
        ├── EstimateAddLineForm.test.js       ── NEW
        ├── MaterialModal.test.js             ── EXTEND (presetDescription, presetPli, AC default)
        ├── FeeModal.test.js                  ── EXTEND (presetDescription)
        └── AddServiceItemModal.test.js       ── DELETE
```

> Route files (`routes/**`) are not yet under Vitest coverage (per
> `docs/designs/frontend-testing.md`), so the two surface-handler *route* edits are
> verified by testing the extracted pieces (`PriceListPicker`, `EstimateAddLineForm`,
> the prefilled modals) plus a manual browser check. Keep the route-level logic thin so
> the tested components carry the behavior.

---

## Pinned shared interfaces (do not rename)

Emitted by the picker (the **only** contract the surfaces depend on):

```js
onChoose({ type: 'service',   serviceItem })    // serviceItem = a ServiceItem row from /api/service-items/
onChoose({ type: 'inventory', inventoryItem })  // inventoryItem = an InventoryItem row from /api/inventory/
onChoose({ type: 'freeform',  typed, isMaterial })  // typed = the search text; isMaterial = checkbox
```

Estimate endpoints (RECONCILED with Plan 2: the **service** pick uses Plan 2's dedicated
`line-items-from-service` action — `LineItemMixin` is generic across estimate/invoice/PO/bill and must
not learn about `service_item`; **inventory + freeform** use the shared `line-items/` POST):

```
POST /api/estimates/{id}/line-items-from-service/  { service_item: <id>, qty }   (→ add_line_item_from_service)
POST /api/estimates/{id}/line-items/
  inventory → { inventory_item: <id>, qty }                        (→ add_line_item_from_pli)
  freeform  → { description, qty, units, price,                    (→ add_line_item(..., is_material=…))
               accounting_category, is_material }
```

Task-list endpoints (immediate atoms — confirmed present in the current code):

```
service            → POST /api/jobs/{id}/add-from-template/  { service_item_id, est_qty, name, description, active_modifiers, est_worker_time }   (via WorkItemForm template mode)
inventory          → POST /api/jobs/{id}/materials/          { inventory_item, quantity, units, unit_cost, sell_price, accounting_category }       (via MaterialModal, PLI-locked)
freeform+material  → POST /api/jobs/{id}/materials/          { description, quantity, units, unit_cost, sell_price, inventory_item: null, accounting_category }   (via MaterialModal, freeform)
freeform+fee       → POST /api/jobs/{id}/fees/               { description, quantity, unit_rate, accounting_category, task: null }                  (via FeeModal)
```

Search backends (already exist, unchanged): `/api/service-items/?search=`,
`/api/inventory/?is_active=true&is_catalog=true&search=`.

---

## Task 1 — Refactor `PriceListPicker` to a pure `onChoose` emitter

**Goal:** one normalized callback; freeform escape becomes an inline "Is this a
material?" checkbox + commit button; the "Add custom task" button is **removed** (no
freeform task). Search behavior is unchanged.

**Files**
- `frontend/src/components/PriceListPicker.svelte` (rewrite script + markup)
- `frontend/tests/components/PriceListPicker.test.js` (rewrite to new contract)

**Interfaces**
- Props: `{ open = false, onChoose = null, onclose = null }` (drop `onselect`,
  `oncustomtask`, `onfreeform`).
- Row pick → `onChoose({ type, serviceItem | inventoryItem })`.
- Freeform commit → `onChoose({ type: 'freeform', typed, isMaterial })`.
- Local state: `pickerQuery` (bound into `SearchPicker`), `isMaterial = $state(false)`
  (default unchecked → Fee).

### Steps

- [ ] **1a. Rewrite the test first.** Replace `PriceListPicker.test.js` with the new
  contract. Real code:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PriceListPicker from '@/components/PriceListPicker.svelte';

const SVC_ITEM = {
  template_id: 11, template_name: 'CNC Routing', description: 'Router pass',
  rate_scheme: 5,
  rate_scheme_detail: { rate_scheme_id: 5, name: 'Machine time', rate: '75.00', unit_label: 'hr' },
};
const INV_ITEM = {
  inventory_item_id: 22, code: 'BOLT-14', description: 'Hex bolt',
  selling_price: '0.50', units: 'ea', is_catalog: true, is_active: true,
};

function mockApiForQuery() {
  api.get.mockImplementation((url) => {
    if (url.includes('/api/service-items/')) return Promise.resolve({ results: [SVC_ITEM], count: 1 });
    if (url.includes('/api/inventory/')) return Promise.resolve({ results: [INV_ITEM], count: 1 });
    return Promise.resolve({ results: [], count: 0 });
  });
}
const baseProps = () => ({ open: true, onChoose: vi.fn(), onclose: vi.fn() });

beforeEach(() => { api.get.mockReset(); });

describe('PriceListPicker (onChoose emitter)', () => {
  it('fetches nothing and shows no list before typing', () => {
    api.get.mockResolvedValue({ results: [], count: 0 });
    const { queryByRole } = render(PriceListPicker, { props: baseProps() });
    expect(api.get).not.toHaveBeenCalled();
    expect(queryByRole('listbox')).toBeNull();
  });

  it('searches both catalogs after typing (past debounce)', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    expect(await findByText('CNC Routing')).toBeInTheDocument();
    expect(await findByText('BOLT-14')).toBeInTheDocument();
    const invCall = api.get.mock.calls.find((c) => c[0].includes('/api/inventory/'));
    expect(invCall[0]).toContain('is_catalog=true');
    expect(invCall[0]).toContain('search=cnc');
  });

  it('emits {type:service, serviceItem} when a service row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    await fireEvent.mouseDown(await findByRole('button', { name: /CNC Routing/ }));
    expect(props.onChoose).toHaveBeenCalledWith({
      type: 'service',
      serviceItem: expect.objectContaining({ template_id: 11 }),
    });
  });

  it('emits {type:inventory, inventoryItem} when an inventory row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await fireEvent.mouseDown(await findByRole('button', { name: /BOLT-14/ }));
    expect(props.onChoose).toHaveBeenCalledWith({
      type: 'inventory',
      inventoryItem: expect.objectContaining({ inventory_item_id: 22 }),
    });
  });

  it('freeform commit defaults to a fee (isMaterial false)', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'Rush charge' } });
    await fireEvent.click(await findByRole('button', { name: /use .*Rush charge/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: 'Rush charge', isMaterial: false });
  });

  it('freeform commit with the material checkbox set emits isMaterial true', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: '3/4 plywood' } });
    await fireEvent.click(await findByRole('checkbox', { name: /material/i }));
    await fireEvent.click(await findByRole('button', { name: /use .*plywood/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: '3/4 plywood', isMaterial: true });
  });

  it('offers no freeform commit before anything is typed', () => {
    const { queryByRole } = render(PriceListPicker, { props: baseProps() });
    expect(queryByRole('button', { name: /^use /i })).toBeNull();
  });
});
```

- [ ] **1b. Run it red:** `cd frontend && npm run test:run tests/components/PriceListPicker.test.js`
  — expect failures (old props `onselect`/`oncustomtask` gone, no `onChoose`, no
  checkbox). Confirm the failures are contract mismatches, not harness errors.

- [ ] **1c. Rewrite the component.** Keep the `search` function and `SearchPicker`
  wiring; change props, the `onPick` mapping, and the footer. Real code (script head +
  markup delta):

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';

  let { open = false, onChoose = null, onclose = null } = $props();
  let pickerQuery = $state('');
  let isMaterial = $state(false); // freeform: unchecked → Fee, checked → Material

  const search = async (q) => {
    const enc = encodeURIComponent(q);
    const [svc, inv] = await Promise.all([
      api.get(`/api/service-items/?search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
      api.get(`/api/inventory/?is_active=true&is_catalog=true&search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
    ]);
    const svcRows = svc.results || svc;
    const invRows = inv.results || inv;
    const rows = [
      ...svcRows.map((s) => ({ kind: 'service', id: s.template_id, label: s.template_name,
        sub: s.description || '', price: s.rate_scheme_detail?.rate, unit: s.rate_scheme_detail?.unit_label, item: s })),
      ...invRows.map((m) => ({ kind: 'inventory', id: m.inventory_item_id, label: m.code,
        sub: m.description || '', price: m.selling_price, unit: m.units, item: m })),
    ];
    return { rows, total: (svc.count ?? svcRows.length) + (inv.count ?? invRows.length) };
  };

  const rowLabel = (r) => r.label;
  const resolveLabel = () => Promise.resolve(null);

  function emitRow(r) {
    if (r.kind === 'service') onChoose?.({ type: 'service', serviceItem: r.item });
    else onChoose?.({ type: 'inventory', inventoryItem: r.item });
  }
  function emitFreeform() {
    onChoose?.({ type: 'freeform', typed: pickerQuery, isMaterial });
  }
</script>

{#if open}
  <div class="plp-overlay" role="dialog" aria-modal="true">
    <div class="plp-modal">
      <div class="plp-header">
        <strong>Add line</strong>
        <button type="button" onclick={onclose}>Close</button>
      </div>

      <div class="plp-body">
        <SearchPicker
          bind:query={pickerQuery}
          {search} {resolveLabel} {rowLabel}
          onPick={emitRow}
          placeholder="Search services or materials…"
        >
          {#snippet row(r)}
            <span class="plp-row">
              <span class="plp-row-label">{r.label}</span>
              <span class="plp-row-sub">{r.sub}</span>
              {#if r.price != null}<span class="plp-row-price">${Number(r.price).toFixed(2)}</span>{/if}
              {#if r.unit}<span class="plp-row-unit">/ {r.unit}</span>{/if}
            </span>
          {/snippet}
        </SearchPicker>
      </div>

      {#if pickerQuery.trim()}
        <div class="plp-freeform">
          <label><input type="checkbox" bind:checked={isMaterial}> Is this a material?</label>
          <button type="button" onclick={emitFreeform}>
            Use “{pickerQuery.trim()}” as {isMaterial ? 'material' : 'fee'}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
```

  Keep the existing `<style>` block; rename `.plp-footer` → `.plp-freeform` (same
  padding/border rules). The `role="dialog"` div and the checkbox get accessible names
  from their label text — the tests query by `role: checkbox, name: /material/i` and
  `role: button, name: /use /i`.

- [ ] **1d. Run it green:** `npm run test:run tests/components/PriceListPicker.test.js`.
  All pass.

---

## Task 2 — Estimate post-selection form (`EstimateAddLineForm`)

**Goal:** after a choice on the estimate surface, collect the surface-specific fields
(**sell price** / qty; freeform also description + AC + units) and POST the right
deferred-descriptor payload to `/api/estimates/{id}/line-items/`. Catalog picks
(service/inventory) snapshot price server-side, so the form only needs **qty** for them;
freeform needs the full manual shape. A freeform **fee** requires an AC (`add_line_item`
enforces it on hand-lines); a freeform **material** does **not** — its AC defaults from
`default_material_accounting_category` (Plan 1 Task 4), so the form prefills that default
(overridable) and never blocks save on a missing AC for materials.

**Files**
- `frontend/src/components/estimates/EstimateAddLineForm.svelte` (new)
- `frontend/tests/components/EstimateAddLineForm.test.js` (new)

**Interfaces**
- Props:
  `{ open, choice, estimateId, categories = [], defaultMaterialCategoryId = null, onSaved = () => {}, onClose = () => {} }`
  where `choice` is the `onChoose` payload (or `null` when closed).
  `defaultMaterialCategoryId` is the AC pk from `default_material_accounting_category`; the
  estimate page reads it the same way the app reads other settings —
  `const s = await api.get('/api/settings/'); s.default_material_accounting_category` — and
  passes it down.
- On save, POST to `/api/estimates/${estimateId}/line-items/`:
  - `choice.type === 'service'`   → `{ service_item: choice.serviceItem.template_id, qty }`
  - `choice.type === 'inventory'` → `{ inventory_item: choice.inventoryItem.inventory_item_id, qty }`
  - `choice.type === 'freeform'`  → `{ description, qty, units, price, accounting_category, is_material: choice.isMaterial }`
- `description` for freeform prefills from `choice.typed` and is editable; for
  service/inventory the description is **not** collected here (the service line's
  description is editable after creation via the existing `openEditItem` path — Settled
  decision 1 in the spec).
- A freeform **material** (`choice.isMaterial`) prefills `accounting_category` from
  `defaultMaterialCategoryId` (overridable) and does **not** block save when it's empty
  (the backend fills the default). A freeform **fee** blocks save when AC is empty.

### Steps

- [ ] **2a. Test first.** `EstimateAddLineForm.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import EstimateAddLineForm from '@/components/estimates/EstimateAddLineForm.svelte';

const cats = [{ id: 7, code: 'MAT', name: 'Materials' }];
beforeEach(() => { api.post.mockReset(); api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('EstimateAddLineForm', () => {
  it('service choice posts service_item + qty', async () => {
    const onSaved = vi.fn();
    const choice = { type: 'service', serviceItem: { template_id: 11, template_name: 'CNC Routing' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '3' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items-from-service/',
      { service_item: 11, qty: '3' });
    expect(onSaved).toHaveBeenCalled();
  });

  it('inventory choice posts inventory_item + qty', async () => {
    const choice = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      { inventory_item: 22, qty: '10' });
  });

  it('freeform fee posts manual payload with is_material false; description prefilled from typed', async () => {
    const choice = { type: 'freeform', typed: 'Rush charge', isMaterial: false };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '50' } });
    await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ description: 'Rush charge', is_material: false, accounting_category: 7, price: '50' }));
  });

  it('freeform material prefills AC from the default and carries is_material true (no manual AC)', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats,
        defaultMaterialCategoryId: 7, onSaved: vi.fn() },
    });
    // AC is prefilled from the default — the user enters no AC.
    expect(getByLabelText(/accounting category/i)).toHaveValue('7');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ is_material: true, accounting_category: 7 }));
  });

  it('freeform material does not block save when no default is configured (backend fills it)', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats,
        defaultMaterialCategoryId: null, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    // Not blocked on AC — material defers to the backend default.
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ is_material: true }));
  });

  it('freeform fee blocks save with no accounting category (hand-line rule)', async () => {
    const choice = { type: 'freeform', typed: 'x', isMaterial: false };
    const { getByLabelText, getByRole, findByText } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
  });
});
```

- [ ] **2b. Run red:** `npm run test:run tests/components/EstimateAddLineForm.test.js`.

- [ ] **2c. Implement.** Model it on `LineItemModal`'s manual branch + `AddServiceItemModal`'s
  qty field. Sketch:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import { modalKeys } from '../../lib/modalKeys.js';

  let { open = false, choice = null, estimateId, categories = [], defaultMaterialCategoryId = null, onSaved = () => {}, onClose = () => {} } = $props();

  let qty = $state('1');
  let description = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  const isFreeform = $derived(choice?.type === 'freeform');
  const title = $derived(
    choice?.type === 'service' ? `Add: ${choice.serviceItem.template_name}` :
    choice?.type === 'inventory' ? `Add: ${choice.inventoryItem.code}` :
    'Add line'
  );

  $effect(() => {
    if (!open || !choice) return;
    qty = '1'; units = 'none'; price = ''; error = '';
    description = choice.type === 'freeform' ? (choice.typed || '') : '';
    // Freeform material prefills the AC from the config default (overridable); everything
    // else starts blank.
    accountingCategory = (choice.type === 'freeform' && choice.isMaterial && defaultMaterialCategoryId != null)
      ? String(defaultMaterialCategoryId) : '';
  });

  async function save() {
    // Service pick uses the dedicated action (Plan 2 Task 4); inventory + freeform
    // use the shared line-items/ POST. LineItemMixin is generic and doesn't know service_item.
    let url = `/api/estimates/${estimateId}/line-items/`;
    let payload;
    if (choice.type === 'service') {
      url = `/api/estimates/${estimateId}/line-items-from-service/`;
      payload = { service_item: choice.serviceItem.template_id, qty };
    } else if (choice.type === 'inventory') {
      payload = { inventory_item: choice.inventoryItem.inventory_item_id, qty };
    } else {
      // Fees require an AC; materials default it server-side (Plan 1 Task 4).
      if (!accountingCategory && !choice.isMaterial) { error = 'Accounting Category is required.'; return; }
      payload = { description, qty: qty || '0', units, price: price || '0',
        accounting_category: accountingCategory ? Number(accountingCategory) : null,
        is_material: choice.isMaterial };
    }
    busy = true; error = '';
    try {
      await api.post(url, payload);
      onSaved();
    } catch (e) {
      error = e.message || 'Could not add line.';
    } finally { busy = false; }
  }
</script>

{#if open && choice}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{title}</h3>
      {#if isFreeform}
        <p><label>Description<br><input type="text" bind:value={description} style="width:100%;box-sizing:border-box;"></label></p>
      {/if}
      <p><label>Quantity<br><input type="number" step="0.01" min="0" bind:value={qty}></label></p>
      {#if isFreeform}
        <p><label>Units<br><UnitsSelect bind:value={units} /></label></p>
        <p><label>Price<br><input type="number" step="0.01" bind:value={price}></label></p>
        <p><label>Accounting Category
          <br><select bind:value={accountingCategory}>
            <option value="">-- Select --</option>
            {#each categories as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
          </select></label></p>
      {/if}
      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Add</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}
```

  (Match the `.overlay`/`.modal`/`.error` styles from `LineItemModal`.) Note: labels must
  be associated so `getByLabelText` works — the `<label>Quantity<br><input></label>`
  wrapping used across the codebase already yields that association.

- [ ] **2d. Run green:** `npm run test:run tests/components/EstimateAddLineForm.test.js`.

---

## Task 3 — Wire the picker into the estimate surface; retire old add affordances

**Goal:** replace the "Add Line Item" and "Add from Service" buttons with a single
**Add line** button that opens `PriceListPicker`; route `onChoose` into
`EstimateAddLineForm`; keep the **Add Adjustment** button and the **Show Tasks &
Materials** wizard link unchanged; keep `LineItemModal` mounted for **editing** existing
lines only.

**Files**
- `frontend/src/routes/estimates/EstimateDetailPage.svelte` (edit)
- Delete `frontend/src/components/estimates/AddServiceItemModal.svelte` and
  `frontend/tests/components/AddServiceItemModal.test.js`.

**Interfaces** (route wiring — verified via manual check + the Task 1/2 component tests):

- [ ] **3a.** Swap imports: remove `AddServiceItemModal`; add
  `import PriceListPicker from '../../components/PriceListPicker.svelte';` and
  `import EstimateAddLineForm from '../../components/estimates/EstimateAddLineForm.svelte';`.

- [ ] **3b.** Replace the add-affordance state + handlers. Remove `serviceItemModalOpen`
  and the create-mode branch of the `modalOpen`/`openAddItem` machinery (keep
  `openEditItem`/`handleSaved` for **edit**). Add:

```js
let pickerOpen = $state(false);
let addChoice = $state(null);      // the onChoose payload feeding EstimateAddLineForm

function handleChoose(choice) {
  pickerOpen = false;
  addChoice = choice;              // opens EstimateAddLineForm
}
function handleLineAdded() {
  addChoice = null;
  loadEstimate();
}
```

- [ ] **3c.** Replace the buttons (the `{#if canEdit}` block ~line 248) — the two add
  buttons collapse to one; adjustment + wizard link stay:

```svelte
{#if canEdit}
  <p>
    <button type="button" onclick={() => { pickerOpen = true; }}>Add line</button>
    <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
    <a href={`/estimates/${estimate.estimate_id}/wizard`} use:link>Show Tasks &amp; Materials</a>
  </p>
{/if}
```

- [ ] **3d.** Replace the `<AddServiceItemModal .../>` block with the picker + form; keep
  `<LineItemModal>` but for **edit only** (drop `mode="create"` usage — it is now only
  opened by `openEditItem`, which already sets `modalMode = 'edit'`):

```svelte
<PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />

<EstimateAddLineForm
  open={addChoice != null}
  choice={addChoice}
  estimateId={estimate.estimate_id}
  {categories}
  {defaultMaterialCategoryId}
  onSaved={handleLineAdded}
  onClose={() => { addChoice = null; }}
/>
```

  Leave the existing `<LineItemModal ... mode={modalMode} .../>` in place (its only
  caller now is `openEditItem`). Confirm no remaining reference to `openAddItem` or
  `serviceItemModalOpen`. Read the material AC default the same way the page reads its
  other settings and expose it as `defaultMaterialCategoryId` — e.g. alongside the
  existing settings/category load:
  `const s = await api.get('/api/settings/'); defaultMaterialCategoryId = s.default_material_accounting_category != null ? Number(s.default_material_accounting_category) : null;`
  (declare `let defaultMaterialCategoryId = $state(null);`).

- [ ] **3e.** Delete `AddServiceItemModal.svelte` + its test:
  `git rm frontend/src/components/estimates/AddServiceItemModal.svelte frontend/tests/components/AddServiceItemModal.test.js`
  (staging only — RM commits). Then
  `cd frontend && grep -rn "AddServiceItemModal" src/ tests/` must return nothing.

- [ ] **3f.** Full suite green + build:
  `cd frontend && npm run test:run && npm run build`. (The `build` catches any
  Svelte-5 markup errors the route edit introduced, since routes aren't unit-tested.)

- [ ] **3g. Manual browser check (RM or agent):** on a draft estimate, "Add line" →
  type → pick a service → set qty → line appears with the service name as description,
  editable via Edit; pick inventory → line appears with snapshot price; freeform +
  material checkbox and freeform fee both create the right line. No `Task`/`Material`
  minted yet (deferred — confirm on the job task-list that no atom appeared).

---

## Task 4 — Add `presetDescription` to `MaterialModal` and `FeeModal`

**Goal:** the task-list surface reuses these modals for the freeform paths and must seed
the typed text as the description. Add a small optional prop (mirrors `WorkItemForm`'s
`presetName`). Keep every existing behavior/test intact.

**Files**
- `frontend/src/components/MaterialModal.svelte`, `FeeModal.svelte` (edit)
- Extend `frontend/tests/components/MaterialModal.test.js`, `FeeModal.test.js`.

**Interfaces**
- New prop `presetDescription = ''`. On open in **create** mode with no existing
  record, seed `description` from `presetDescription` (only when non-empty; never
  override an edited/PLI-locked value).

### Steps

- [ ] **4a. MaterialModal test (append).**

```js
it('seeds description from presetDescription on create', async () => {
  const { getByLabelText } = render(MaterialModal, {
    props: { open: true, mode: 'create', jobId: 5, categories: [], presetDescription: 'plywood' },
  });
  expect(getByLabelText(/description/i)).toHaveValue('plywood');
});
```

- [ ] **4b.** Implement in `MaterialModal`'s open-effect create branch:
  change `description = '';` →
  `description = (mode === 'create' && !material) ? (presetDescription || '') : '';`
  and add `presetDescription = ''` to `$props()`.

- [ ] **4c. FeeModal test (append).**

```js
it('seeds description from presetDescription on create', async () => {
  const { getByLabelText } = render(FeeModal, {
    props: { open: true, mode: 'create', jobId: 5, categories: [], presetDescription: 'Rush charge' },
  });
  expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
});
```

- [ ] **4d.** Implement in `FeeModal`'s open-effect create branch:
  `description = (mode === 'edit' && fee) ? (fee.description || '') : (presetDescription || '');`
  and add `presetDescription = ''` to `$props()`.

- [ ] **4e.** Green:
  `npm run test:run tests/components/MaterialModal.test.js tests/components/FeeModal.test.js`.

---

## Task 5 — Wire the picker into the job task-list surface

**Goal:** the task-list's primary add affordance becomes a **single "Add Work" button**
that opens `PriceListPicker`; route `onChoose` to the existing immediate-atom modals,
prefilled. **Remove** the granular top-level launcher buttons ("Add Task From Template /
Add Manual Task / Add Material / Add Fee") — the picker is now the one front door. The
modals themselves (`WorkItemForm` / `MaterialModal` / `FeeModal`) are **still used** — the
picker's handler opens them prefilled; they are just no longer launched by their own
dedicated buttons. No new endpoints — reuse the modals' existing POSTs.

**Files**
- `frontend/src/routes/jobs/JobTaskListPage.svelte` (edit)

**Interfaces** (route wiring — verified by the reused modals' own tests + manual check):

- [ ] **5a.** Import the picker:
  `import PriceListPicker from '../../components/PriceListPicker.svelte';`.

- [ ] **5b.** Add state + the surface handler that opens the right existing modal:

```js
let pickerOpen = $state(false);

function handleChoose(choice) {
  pickerOpen = false;
  if (choice.type === 'service') {
    // Real Task now, via WorkItemForm template mode, prefilled to the picked ServiceItem.
    taskModalTask = null;
    taskModalMode = 'template';
    taskPresetTemplateId = choice.serviceItem.template_id;
    taskModalOpen = true;
  } else if (choice.type === 'inventory') {
    // Job-level Material, PLI-locked, via MaterialModal.
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalJobId = job.job_id;
    materialModalMode = 'create';
    materialPresetPli = choice.inventoryItem;   // MaterialModal prefills via its InventoryItemPicker
    materialPresetDescription = '';
    materialModalOpen = true;
  } else if (choice.isMaterial) {
    // Freeform material → MaterialModal, description seeded from typed text.
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalJobId = job.job_id;
    materialModalMode = 'create';
    materialPresetPli = null;
    materialPresetDescription = choice.typed;
    materialModalOpen = true;
  } else {
    // Freeform fee → FeeModal, description seeded from typed text.
    feeModalFee = null;
    feeModalMode = 'create';
    feePresetDescription = choice.typed;
    feeModalOpen = true;
  }
}
```

  Add the backing `$state` decls: `taskPresetTemplateId`, `materialPresetPli`,
  `materialPresetDescription`, `feePresetDescription` (all default `null`/`''`).

- [ ] **5c.** Consolidate the toolbar (`{#if !jobLocked}` block). **Remove** the four
  work-related granular launcher buttons and replace them with a single **Add Work**
  button that opens the picker. Leave **Add Expense** and **Mark Work Complete** alone
  (Expense is not a picker atom). Before:

```svelte
{#if !jobLocked}
  <button type="button" onclick={openAddTemplateTask}>Add Task From Template</button>
  <button type="button" onclick={openAddManualTask}>Add Manual Task</button>
  <button type="button" onclick={openAddJobMaterial}>Add Material</button>
  <button type="button" onclick={openAddJobFee}>Add Fee</button>
  <button type="button" onclick={() => { editingExpense = null; expenseModalOpen = true; }}>Add Expense</button>
```

After:

```svelte
{#if !jobLocked}
  <button type="button" onclick={() => { pickerOpen = true; }}>Add Work</button>
  <button type="button" onclick={() => { editingExpense = null; expenseModalOpen = true; }}>Add Expense</button>
```

  The `WorkItemForm` / `MaterialModal` / `FeeModal` instances stay mounted (the picker
  handler in 5b opens them prefilled); they are only losing their dedicated launcher
  buttons. The now-unused `openAddTemplateTask` / `openAddManualTask` /
  `openAddJobMaterial` / `openAddJobFee` launcher helpers can be removed or folded into
  `handleChoose` — grep for stragglers after the edit.

- [ ] **5d.** Pass the presets into the existing modal instances and mount the picker:

```svelte
<PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />
```
  - `WorkItemForm`: add `presetTemplateId={taskPresetTemplateId}` (it already reads this
    in template mode).
  - `MaterialModal`: add `presetDescription={materialPresetDescription}`,
    `presetPli={materialPresetPli}`, **and** `defaultMaterialCategoryId={defaultMaterialCategoryId}`.
    `presetPli` is a **firm** part of this plan: the task-list inventory pick auto-fills
    the item in `MaterialModal` (via its existing `handlePliSelect`) so it matches the
    estimate surface — no re-picking. A `null` `presetPli` (the freeform-material path)
    leaves the item unselected, seeds the description, and prefills the AC from
    `defaultMaterialCategoryId` (overridable) — the same material-AC default the estimate
    surface uses.
  - `FeeModal`: add `presetDescription={feePresetDescription}`.

  Read the default on the page the same way its other settings load —
  `const s = await api.get('/api/settings/'); defaultMaterialCategoryId = s.default_material_accounting_category != null ? Number(s.default_material_accounting_category) : null;`
  (declare `let defaultMaterialCategoryId = $state(null);`).

- [ ] **5e.** Build `presetPli` + the material-AC default on `MaterialModal`, with tests:

```js
it('prefills from presetPli on create (PLI-locked)', async () => {
  const pli = { inventory_item_id: 22, code: 'BOLT-14', description: 'Hex bolt',
    purchase_price: '0.25', selling_price: '0.50', units: 'ea' };
  const { getByLabelText } = render(MaterialModal, {
    props: { open: true, mode: 'create', jobId: 5, categories: [], presetPli: pli },
  });
  expect(getByLabelText(/description/i)).toHaveValue('Hex bolt');
});

it('freeform create (no presetPli) prefills AC from defaultMaterialCategoryId', async () => {
  const cats = [{ id: 7, code: 'MAT', name: 'Materials' }];
  const { getByLabelText } = render(MaterialModal, {
    props: { open: true, mode: 'create', jobId: 5, categories: cats, defaultMaterialCategoryId: 7 },
  });
  expect(getByLabelText(/accounting category/i)).toHaveValue('7');
});
```
  Add `presetPli = null` and `defaultMaterialCategoryId = null` to `$props()`. In the
  open-effect **create** branch: if `presetPli` is set, call `handlePliSelect(presetPli)`
  (which sets the AC from the item); otherwise, when `defaultMaterialCategoryId != null`,
  seed `accountingCategory = String(defaultMaterialCategoryId)` (overridable). The
  inventory pick's PLI-derived AC always wins over the default.

- [ ] **5f.** Suite + build green: `cd frontend && npm run test:run && npm run build`.

- [ ] **5g. Manual browser check:** on an unlocked job task-list, confirm the four
  granular add buttons are gone and a single **Add Work** button remains (plus Add
  Expense). "Add Work" → pick a
  service → the task template modal opens prefilled → save → a real Task appears; pick
  inventory → material modal opens (PLI-locked / seeded) → save → Material appears;
  freeform material → material modal seeded with the typed description; freeform fee →
  fee modal seeded. Confirm these mint atoms **immediately** (unlike the estimate
  surface).

---

## Task 6 — Final verification

- [ ] `cd frontend && npm run test:run` — whole suite green; read the summary line
  (`Test Files … passed`), do not trust a piped exit code.
- [ ] `cd frontend && npm run build` — production build succeeds (Svelte-5 markup check
  for the two route edits).
- [ ] `grep -rn "AddServiceItemModal\|oncustomtask\|onfreeform" frontend/src frontend/tests`
  returns nothing (old callbacks + retired modal fully gone).
- [ ] `grep -rn "PriceListPicker" frontend/src` shows exactly the two surfaces importing it.
- [ ] `grep -rn "Add Task From Template\|Add Manual Task\|Add Material\|Add Fee" frontend/src/routes/jobs/JobTaskListPage.svelte`
  returns nothing — the four granular launcher buttons are gone, replaced by one "Add
  Work" button (Add Expense may still match a different string; verify by eye).
- [ ] Leave the branch as-is for RM's review (no commit/merge/PR).

---

## Assumptions & open questions (confirm with RM)

1. **RECONCILED with Plan 2 — service uses a dedicated action.** Plan 2 built a dedicated
   `POST /api/estimates/{id}/line-items-from-service/` (body `{service_item, qty}`) rather than
   overloading the generic `LineItemMixin.line_items` POST — correct, because `LineItemMixin` is shared
   across estimate/invoice/PO/bill and must not learn the estimate-only `service_item`. So
   `EstimateAddLineForm` now routes: **service** → `line-items-from-service/`; **inventory + freeform**
   → the shared `line-items/` POST (which already branches on `inventory_item`, and to which Plan 1
   added `is_material` pass-through). The service test asserts the `line-items-from-service/` URL. (This
   was the one cross-plan discrepancy; resolved in favor of Plan 2's backend design.)
2. **RESOLVED — freeform AC differs by kind.** A freeform **fee** still requires an
   explicit AC (`add_line_item` enforces it on hand-lines, `services.py:277`). A freeform
   **material** does **not**: Plan 1 Task 4 defaults a material line's AC from the
   `default_material_accounting_category` config, so `EstimateAddLineForm` (and the
   task-list `MaterialModal`) **prefills** that default (overridable) and never blocks save
   on a missing AC for materials. Both the estimate form and the task-list material modal
   read the default via `/api/settings/` (`default_material_accounting_category`), passed
   down as `defaultMaterialCategoryId`.
3. **RESOLVED — task-list add affordances consolidate under one "Add Work" button.** The
   four granular launcher buttons ("Add Task From Template / Add Manual Task / Add Material
   / Add Fee") are **removed**; the task-list's primary add affordance is a single **Add
   Work** button that opens the picker. The `WorkItemForm` / `MaterialModal` / `FeeModal`
   modals are **still used** — the picker's handler opens them prefilled — they just no
   longer have their own dedicated launcher buttons. (Add Expense stays; it isn't a picker
   atom.) The estimate side's retirement (`AddServiceItemModal` + the manual/inventory
   `LineItemModal` *add* path) is unchanged.
4. **`LineItemModal` is kept for editing only** on the estimate surface (its create/`pli`
   add path is superseded by the picker + `EstimateAddLineForm`). It is still mounted and
   opened by `openEditItem`. Not deleted.
5. **RESOLVED — `presetPli` on `MaterialModal` (Task 5e) is firm.** The task-list
   inventory pick auto-fills the item in `MaterialModal` (via `handlePliSelect`) so it has
   parity with the estimate surface — no re-picking. This is built, not skipped.
6. **Confirmed endpoint paths (from current code):** task-list service →
   `POST /api/jobs/{id}/add-from-template/` (`WorkItemForm.svelte:193`); job material →
   `POST /api/jobs/{id}/materials/` (`MaterialModal.svelte:177`); job fee →
   `POST /api/jobs/{id}/fees/` (`FeeModal.svelte:61`). Search backends
   `/api/service-items/?search=` and `/api/inventory/?is_active=true&is_catalog=true&search=`
   (`PriceListPicker.svelte:16`).
7. **Routes aren't unit-tested** (`docs/designs/frontend-testing.md`), so the two
   `routes/**` edits (Tasks 3 & 5) are covered indirectly by the extracted-component
   tests plus `npm run build` and a manual browser pass, not by new route tests.
