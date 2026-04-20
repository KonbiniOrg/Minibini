# Billable Atoms — Plan B: Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the user-facing wizard experience described in `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md`. Adds the unified `CatalogPicker` Svelte component, the `EstimateWizardPage` (mirroring `InvoiceWizardPage`), an `EstimateDetailPage` with direct line item creation, and the "Send all atoms to estimate" button on the worksheet.

**Architecture:** Mirror the existing invoice wizard's component split (`WizardSourcePool` + `WizardLineItemCard` + `WizardFooter`) for estimates, but adapted for the flat-atoms structure (no task tree). The new `CatalogPicker` is a generic search component used by both worksheet/job atom-creation flows AND estimate/invoice direct line-item flows. Existing `PlanTaskModal` / `PlanMaterialModal` / `PriceListItemPicker` stay in place this round; their migration to `CatalogPicker` is a follow-up.

**Tech Stack:** Svelte 5 (runes: `$state`, `$derived`, `$effect`, `$props`), `svelte-spa-router` (hash routing), `apps/api/` REST endpoints (added in Plan A).

**Reference files (existing patterns to mirror):**
- `frontend/src/routes/invoices/InvoiceWizardPage.svelte` — wizard page shell
- `frontend/src/components/invoices/WizardSourcePool.svelte` — atom selection UI (nested-by-task; estimate version is flat)
- `frontend/src/components/invoices/WizardLineItemCard.svelte` — line item display
- `frontend/src/components/invoices/WizardFooter.svelte` — sticky footer with actions
- `frontend/src/components/PriceListItemPicker.svelte` — picker pattern for catalog search
- `frontend/src/lib/api.js` — request helpers + CSRF/error handling
- `frontend/src/App.svelte:39-78` — route registry

**Frontend testing:** Project has no Svelte unit-test framework. Verification is manual via the dev server.

**Dev server:** `python manage.py runserver` (Django on :8000) + `cd frontend && npm run dev` (Vite on :9000). Use the SPA at `http://localhost:9000` with `?autologin` for instant login as `dev_user`.

---

## Phase 1 — `CatalogPicker` component

### Task 1: Build the `CatalogPicker.svelte` component

**Files:**
- Create: `frontend/src/components/CatalogPicker.svelte`

The component is a search input with a dropdown that mixes `TaskTemplate` + `PriceListItem` results, tagged by source. A "Manual" pseudo-result lets the user fall through to a custom entry form. On selection, the `onSelect` callback receives `{kind: 'task_template'|'price_list_item'|'manual', item: {...}|null}`.

- [ ] **Step 1: Scaffold the component file**

Create `frontend/src/components/CatalogPicker.svelte` with this content:

```svelte
<script>
  import { api } from '../lib/api.js';

  let {
    onSelect = () => {},
    disabled = false,
    placeholder = 'Search catalogs…',
  } = $props();

  let query = $state('');
  let taskTemplates = $state([]);
  let priceListItems = $state([]);
  let showDropdown = $state(false);
  let loading = $state(false);

  // Combined, filtered, tagged results — task templates and PLIs interleaved.
  let results = $derived.by(() => {
    const lower = query.toLowerCase();
    const tts = taskTemplates
      .filter(t => !lower
        || t.template_name.toLowerCase().includes(lower)
        || (t.description || '').toLowerCase().includes(lower))
      .map(t => ({
        kind: 'task_template',
        id: t.template_id,
        label: t.template_name,
        sub: t.description || '',
        meta: t.rate ? `$${t.rate}/${t.units}` : '',
        item: t,
      }));
    const plis = priceListItems
      .filter(p => !lower
        || p.code.toLowerCase().includes(lower)
        || (p.description || '').toLowerCase().includes(lower))
      .map(p => ({
        kind: 'price_list_item',
        id: p.price_list_item_id,
        label: p.code,
        sub: p.description || '',
        meta: `$${p.selling_price}/${p.units}`,
        item: p,
      }));
    return [...tts, ...plis].sort((a, b) => a.label.localeCompare(b.label));
  });

  async function fetchCatalogs() {
    if (taskTemplates.length > 0 && priceListItems.length > 0) return;
    loading = true;
    try {
      const [tts, plis] = await Promise.all([
        api.get('/api/task-templates/?page_size=9999'),
        api.get('/api/price-list-items/?page_size=9999'),
      ]);
      taskTemplates = tts.results || tts;
      priceListItems = plis.results || plis;
    } catch (e) {
      taskTemplates = [];
      priceListItems = [];
    } finally {
      loading = false;
    }
  }

  function handleInput(e) {
    query = e.target.value;
    showDropdown = true;
  }

  function handleFocus() {
    showDropdown = true;
    fetchCatalogs();
  }

  function handleBlur() {
    setTimeout(() => { showDropdown = false; }, 200);
  }

  function pick(result) {
    showDropdown = false;
    query = '';
    onSelect({kind: result.kind, item: result.item});
  }

  function pickManual() {
    showDropdown = false;
    query = '';
    onSelect({kind: 'manual', item: null});
  }
</script>

<div class="catalog-picker">
  <input
    type="text"
    {placeholder}
    {disabled}
    value={query}
    oninput={handleInput}
    onfocus={handleFocus}
    onblur={handleBlur}
  />
  {#if showDropdown}
    <div class="dropdown">
      {#if loading}
        <p class="loading">Loading catalogs…</p>
      {:else}
        {#each results as r (r.kind + ':' + r.id)}
          <button type="button" class="result" onclick={() => pick(r)}>
            <small class="tag">[{r.kind === 'task_template' ? 'task' : 'material'}]</small>
            <strong>{r.label}</strong>
            {#if r.meta}<span class="meta">{r.meta}</span>{/if}
            {#if r.sub}<div class="sub">{r.sub}</div>{/if}
          </button>
        {/each}
        <button type="button" class="result manual" onclick={pickManual}>
          <small class="tag">[manual]</small>
          <strong>Enter manually</strong>
          <div class="sub">Type custom description, qty, and price</div>
        </button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .catalog-picker { position: relative; }
  .catalog-picker input { width: 100%; padding: 0.4rem; }
  .dropdown {
    position: absolute; top: 100%; left: 0; right: 0;
    background: white; border: 1px solid #ccc; max-height: 320px; overflow-y: auto;
    z-index: 50;
  }
  .result {
    display: block; width: 100%; text-align: left;
    padding: 0.5rem; border: none; background: white; cursor: pointer;
    border-bottom: 1px solid #eee;
  }
  .result:hover { background: #f4f4f4; }
  .result.manual { font-style: italic; }
  .tag { color: #888; margin-right: 0.4rem; }
  .meta { color: #666; margin-left: 0.4rem; }
  .sub { color: #666; font-size: 0.85em; margin-top: 0.2rem; }
  .loading { padding: 0.5rem; color: #888; }
</style>
```

- [ ] **Step 2: Verify it loads in the browser**

Start the dev servers:
```bash
python manage.py runserver  # in one terminal
cd frontend && npm run dev  # in another
```

Open `http://localhost:9000?autologin` to log in. The component isn't wired to any route yet — verification is just that `npm run dev` compiles cleanly (no Svelte/Vite errors in the terminal).

Run `cd frontend && npm run build` and confirm it succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CatalogPicker.svelte
git commit -m "feat(frontend): add unified CatalogPicker component"
```

---

## Phase 2 — Worksheet "Send all atoms" action

### Task 2: Add "Send all atoms to estimate" button to `WorksheetDetailPage`

**Files:**
- Modify: `frontend/src/routes/worksheets/WorksheetDetailPage.svelte`

The button calls the Plan A endpoint `POST /api/est-worksheets/<id>/send-all-atoms-to-estimate/`, then navigates the user to the new estimate (route added in Phase 3).

- [ ] **Step 1: Add a `sendAllAtoms` function and a button in the component**

Modify `frontend/src/routes/worksheets/WorksheetDetailPage.svelte`. In the `<script>` block, add the function near the other handlers:

```javascript
import { push } from 'svelte-spa-router';

let sendingAll = $state(false);

async function sendAllAtoms() {
  if (!confirm('Send all unclaimed atoms to the estimate as 1:1 line items?')) return;
  sendingAll = true;
  try {
    const result = await api.post(
      `/api/est-worksheets/${params.id}/send-all-atoms-to-estimate/`
    );
    push(`/estimates/${result.estimate_id}`);
  } catch (e) {
    alert(e.message || 'Failed to send atoms');
  } finally {
    sendingAll = false;
  }
}

async function openWizard() {
  // Ensure the estimate exists, then route to the wizard.
  try {
    const result = await api.post(
      `/api/est-worksheets/${params.id}/send-all-atoms-to-estimate/`
    );
    // send-all is idempotent for already-claimed atoms; the estimate is now ensured.
    // Navigate to the wizard for further grouping.
    push(`/estimates/${result.estimate_id}/wizard`);
  } catch (e) {
    alert(e.message || 'Failed to open wizard');
  }
}
```

Then in the template (look for the existing action buttons section — around the `Generate Estimate` link if it's still there), add:

```svelte
{#if canEdit}
  <p>
    <button onclick={sendAllAtoms} disabled={sendingAll}>
      {sendingAll ? 'Sending…' : 'Send all atoms to estimate'}
    </button>
    <button onclick={openWizard}>Open wizard to group atoms</button>
  </p>
{/if}
```

- [ ] **Step 2: Verify in the browser**

With both servers running, open a worksheet at `http://localhost:9000/#/worksheets/<id>`. Confirm the two buttons appear (when you have `can_manage_jobs` and the worksheet is in draft).

- [ ] **Step 3: Test the send-all flow manually**

Pick a worksheet that has unclaimed PlanCharge / PlanMaterial atoms. Click "Send all atoms to estimate." After confirming the dialog, you should be navigated to `/#/estimates/<id>`. (Plan B Phase 3 builds that page; until then, route resolves to a 404 — that's expected at this point in the plan.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/worksheets/WorksheetDetailPage.svelte
git commit -m "feat(frontend): add send-all-atoms and open-wizard buttons on worksheet"
```

---

## Phase 3 — Estimate UI

### Task 3: Create `EstimateDetailPage.svelte`

**Files:**
- Create: `frontend/src/routes/estimates/EstimateDetailPage.svelte`

A list of line items with their sources (when present), plus an "Add line item" affordance that pops a `CatalogPicker`. Submitting the picker opens a small inline form (description / qty / units / price / category) pre-filled from the picked catalog entry, then POSTs to the existing line item endpoint.

- [ ] **Step 1: Create the directory and file**

Create directory: `mkdir -p frontend/src/routes/estimates`

Create `frontend/src/routes/estimates/EstimateDetailPage.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import CatalogPicker from '../../components/CatalogPicker.svelte';

  let { params = {} } = $props();

  let estimate = $state(null);
  let lineItems = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Add-line-item form state
  let addOpen = $state(false);
  let newDescription = $state('');
  let newQty = $state('1');
  let newUnits = $state('each');
  let newPrice = $state('0.00');
  let newCategoryId = $state('');
  let newSourceTemplateId = $state(null);
  let newPliId = $state(null);
  let busy = $state(false);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );
  const isDraft = $derived(estimate?.status === 'draft');
  const canEdit = $derived(canManageJobs && isDraft);

  async function load() {
    loading = true;
    error = '';
    try {
      const [est, items, cats] = await Promise.all([
        api.get(`/api/estimates/${params.id}/`),
        api.get(`/api/estimates/${params.id}/line-items/`),
        api.get('/api/accounting-categories/?page_size=100'),
      ]);
      estimate = est;
      lineItems = items.results || items;
      categories = cats.results || cats;
    } catch (e) {
      error = e.message || 'Failed to load estimate.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (params.id) load();
  });

  function resetForm() {
    newDescription = '';
    newQty = '1';
    newUnits = 'each';
    newPrice = '0.00';
    newCategoryId = '';
    newSourceTemplateId = null;
    newPliId = null;
  }

  function onCatalogSelect({kind, item}) {
    resetForm();
    if (kind === 'task_template') {
      newDescription = item.template_name;
      newUnits = item.units || 'each';
      newPrice = item.rate?.toString() || '0.00';
      newCategoryId = item.accounting_category || '';
      newSourceTemplateId = item.template_id;
    } else if (kind === 'price_list_item') {
      newDescription = item.description || item.code;
      newUnits = item.units || 'each';
      newPrice = item.selling_price?.toString() || '0.00';
      newCategoryId = item.accounting_category || '';
      newPliId = item.price_list_item_id;
    }
    addOpen = true;
  }

  async function submitNewLineItem() {
    busy = true;
    try {
      const payload = {
        description: newDescription,
        qty: newQty,
        units: newUnits,
        price: newPrice,
        accounting_category: newCategoryId || null,
      };
      if (newSourceTemplateId) payload.source_template = newSourceTemplateId;
      if (newPliId) payload.price_list_item = newPliId;
      await api.post(`/api/estimates/${params.id}/line-items/`, payload);
      addOpen = false;
      resetForm();
      await load();
    } catch (e) {
      alert(e.message || 'Failed to create line item.');
    } finally {
      busy = false;
    }
  }

  async function deleteLineItem(li) {
    if (!confirm('Delete this line item?')) return;
    try {
      await api.delete(`/api/estimates/${params.id}/line-items/${li.line_item_id}/`);
      await load();
    } catch (e) {
      alert(e.message || 'Delete failed.');
    }
  }
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p style="color: red;">{error}</p>
{:else if estimate}
  <h2>Estimate {estimate.estimate_number}</h2>
  <p>Status: {estimate.status} · Version {estimate.version}</p>

  <h3>Line items</h3>
  {#if lineItems.length === 0}
    <p><em>No line items yet.</em></p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>#</th><th>Description</th><th>Qty</th><th>Units</th>
          <th>Price</th><th>Category</th><th>Sources</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each lineItems as li (li.line_item_id)}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td>{li.qty}</td>
            <td>{li.units}</td>
            <td>${li.price}</td>
            <td>{li.accounting_category_name || '—'}</td>
            <td>{li.sources?.length || 0}</td>
            <td>
              {#if canEdit}
                <button onclick={() => deleteLineItem(li)}>Delete</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if canEdit}
    <h3>Add line item</h3>
    <CatalogPicker onSelect={onCatalogSelect} />

    <p>
      <button onclick={() => { resetForm(); addOpen = true; }}>
        Or enter manually
      </button>
    </p>

    {#if addOpen}
      <fieldset>
        <legend><strong>New line item</strong></legend>
        <p><label><strong>Description</strong><br>
          <input type="text" bind:value={newDescription}></label></p>
        <p><label><strong>Qty</strong><br>
          <input type="number" step="0.01" bind:value={newQty}></label></p>
        <p><label><strong>Units</strong><br>
          <input type="text" bind:value={newUnits}></label></p>
        <p><label><strong>Price</strong><br>
          <input type="number" step="0.01" bind:value={newPrice}></label></p>
        <p><label><strong>Accounting category</strong><br>
          <select bind:value={newCategoryId}>
            <option value="">— None —</option>
            {#each categories as c}
              <option value={c.accounting_category_id}>{c.name}</option>
            {/each}
          </select></label></p>
        <p>
          <button onclick={submitNewLineItem} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button onclick={() => { addOpen = false; resetForm(); }}>Cancel</button>
        </p>
      </fieldset>
    {/if}

    <p>
      <a href={`#/estimates/${estimate.estimate_id}/wizard`}>Open wizard to group atoms</a>
    </p>
  {/if}
{/if}
```

- [ ] **Step 2: Register the route in `App.svelte`**

Modify `frontend/src/App.svelte`. Add the import near the other route imports:

```javascript
import EstimateDetailPage from './routes/estimates/EstimateDetailPage.svelte';
```

In the `routes` object, add:

```javascript
'/estimates/:id': EstimateDetailPage,
```

- [ ] **Step 3: Verify in browser**

`cd frontend && npm run build` to catch compile errors. Then visit `http://localhost:9000/#/estimates/<id>` for an existing estimate. Confirm the line items display, the catalog picker appears, and "Add line item" works for both template-picked and manual entry.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/estimates/ frontend/src/App.svelte
git commit -m "feat(frontend): add EstimateDetailPage with catalog-picker line item add"
```

---

### Task 4: Create estimate wizard supporting components

**Files:**
- Create: `frontend/src/components/estimates/WizardSourcePool.svelte`
- Create: `frontend/src/components/estimates/WizardLineItemCard.svelte`
- Create: `frontend/src/components/estimates/WizardFooter.svelte`

These mirror the invoice wizard components but adapted for the estimate's flat atom pool (no task tree).

- [ ] **Step 1: Create the directory**

`mkdir -p frontend/src/components/estimates`

- [ ] **Step 2: Create `WizardSourcePool.svelte`**

Create `frontend/src/components/estimates/WizardSourcePool.svelte`:

```svelte
<script>
  let { sourcePool = null, selectedAtoms = $bindable([]) } = $props();

  function toggleAtom(atomType, atomId) {
    const key = `${atomType}:${atomId}`;
    const existing = selectedAtoms.find(a => `${a.type}:${a.id}` === key);
    if (existing) {
      selectedAtoms = selectedAtoms.filter(a => `${a.type}:${a.id}` !== key);
    } else {
      selectedAtoms = [...selectedAtoms, {type: atomType, id: atomId}];
    }
  }

  function isSelected(atomType, atomId) {
    return selectedAtoms.some(a => a.type === atomType && a.id === atomId);
  }
</script>

{#if !sourcePool || sourcePool.atoms.length === 0}
  <p><em>No atoms on this worksheet.</em></p>
{:else}
  <ul style="list-style: none; padding: 0;">
    {#each sourcePool.atoms as atom (atom.type + ':' + atom.id)}
      <li>
        {#if atom.state === 'available'}
          <label>
            <input
              type="checkbox"
              checked={isSelected(atom.type, atom.id)}
              onchange={() => toggleAtom(atom.type, atom.id)}
            >
            <small>[{atom.type === 'plan_charge' ? 'task' : 'material'}]</small>
            {atom.description}
            &mdash; ${atom.amount}
          </label>
        {:else if atom.state === 'claimed_by_current'}
          <span style="color: #777;">
            <input type="checkbox" checked disabled>
            <em>{atom.description} &mdash; ${atom.amount}</em>
            <small>&rarr; line {atom.claiming_line_item_id}</small>
          </span>
        {:else if atom.state === 'claimed_by_other'}
          <span style="color: #999;">
            <input type="checkbox" disabled>
            <em>{atom.description} &mdash; ${atom.amount}</em>
            <small>&rarr; estimate {atom.claiming_estimate_number}</small>
          </span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}
```

- [ ] **Step 3: Create `WizardLineItemCard.svelte`**

Create `frontend/src/components/estimates/WizardLineItemCard.svelte`:

```svelte
<script>
  let {
    lineItem = null,
    onAddSelected = () => {},
    onRemoveSource = () => {},
    canAddHere = false,
  } = $props();
</script>

<fieldset>
  <legend>
    <strong>Line {lineItem.line_number}</strong>
    &mdash; ${lineItem.price} × {lineItem.qty} {lineItem.units}
  </legend>

  <p>{lineItem.description || '(no description)'}</p>

  {#if lineItem.sources && lineItem.sources.length > 0}
    <p><strong>Sources ({lineItem.sources.length}):</strong></p>
    <ul>
      {#each lineItem.sources as src (src.source_id)}
        <li>
          [{src.source_type}] #{src.source_pk}
          <button type="button" onclick={() => onRemoveSource(src.source_id)}>
            Remove
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <p>
    <button
      type="button"
      onclick={() => onAddSelected(lineItem.line_item_id)}
      disabled={!canAddHere}
    >
      Add selected atoms here
    </button>
  </p>
</fieldset>
```

- [ ] **Step 4: Create `WizardFooter.svelte`**

Create `frontend/src/components/estimates/WizardFooter.svelte`:

```svelte
<script>
  let {
    selectedCount = 0,
    onCreateNew = () => {},
    canAct = false,
  } = $props();
</script>

<div class="wizard-footer">
  <span>{selectedCount} atom(s) selected</span>
  <button type="button" onclick={onCreateNew} disabled={!canAct}>
    Create new line item from selected
  </button>
</div>

<style>
  .wizard-footer {
    position: sticky; bottom: 0; background: #f0f0f0;
    padding: 0.6rem; border-top: 1px solid #ccc; margin-top: 1rem;
  }
  .wizard-footer button { margin-left: 1rem; }
</style>
```

- [ ] **Step 5: Verify build**

Run `cd frontend && npm run build`. Expect a clean build.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/estimates/
git commit -m "feat(frontend): add estimate wizard support components"
```

---

### Task 5: Create `EstimateWizardPage.svelte`

**Files:**
- Create: `frontend/src/routes/estimates/EstimateWizardPage.svelte`
- Modify: `frontend/src/App.svelte` (add route)

Same shape as `InvoiceWizardPage` — load estimate + line items + source pool, compose the source pool / line item card / footer pieces, dispatch wizard API calls.

- [ ] **Step 1: Create the page**

Create `frontend/src/routes/estimates/EstimateWizardPage.svelte`:

```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import WizardSourcePool from '../../components/estimates/WizardSourcePool.svelte';
  import WizardLineItemCard from '../../components/estimates/WizardLineItemCard.svelte';
  import WizardFooter from '../../components/estimates/WizardFooter.svelte';

  const { params = {} } = $props();

  let estimate = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let loading = $state(true);
  let error = $state(null);

  const canAddHere = $derived(selectedAtoms.length > 0);

  async function addAtomsToLineItem(lineItemId) {
    try {
      await api.post(
        `/api/estimates/${estimate.estimate_id}/line-items/${lineItemId}/add-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadAfterAction();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another estimate. Reload the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to add atoms');
      }
    }
  }

  async function createNewLineItem() {
    try {
      await api.post(
        `/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadAfterAction();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another estimate. Reload the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to create line item');
      }
    }
  }

  async function removeSource(lineItemId, sourceId) {
    try {
      await api.post(
        `/api/estimates/${estimate.estimate_id}/line-items/${lineItemId}/remove-atoms/`,
        {source_ids: [sourceId]},
      );
      await reloadAfterAction();
    } catch (e) {
      alert(e.message || 'Failed to remove source');
    }
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [est, items, pool] = await Promise.all([
        api.get(`/api/estimates/${params.id}/`),
        api.get(`/api/estimates/${params.id}/line-items/`),
        api.get(`/api/estimates/${params.id}/source-pool/`),
      ]);
      estimate = est;
      lineItems = items.results || items;
      sourcePool = pool;
      reconcileAtomStates();
    } catch (e) {
      error = e.message || 'Failed to load wizard';
    } finally {
      loading = false;
    }
  }

  async function reloadAfterAction() {
    try {
      const [est, items] = await Promise.all([
        api.get(`/api/estimates/${params.id}/`),
        api.get(`/api/estimates/${params.id}/line-items/`),
      ]);
      estimate = est;
      lineItems = items.results || items;
      reconcileAtomStates();
      selectedAtoms = [];
    } catch (e) {
      error = e.message || 'Failed to reload';
    }
  }

  // Walk the source pool and update each atom's state from current line items.
  // claimed_by_other atoms (snapshot at mount) are left alone.
  function reconcileAtomStates() {
    if (!sourcePool) return;
    const claimMap = new Map();
    for (const li of lineItems) {
      for (const src of li.sources || []) {
        claimMap.set(`${src.source_type}:${src.source_pk}`, {
          line_item_id: li.line_item_id,
        });
      }
    }
    sourcePool = {
      atoms: sourcePool.atoms.map(a => {
        const key = `${a.type}:${a.id}`;
        if (claimMap.has(key)) {
          return {...a, state: 'claimed_by_current', claiming_line_item_id: claimMap.get(key).line_item_id};
        }
        if (a.state === 'claimed_by_current') {
          // Was claimed by current but no longer claimed → release back to available
          return {...a, state: 'available', claiming_line_item_id: null};
        }
        return a;
      }),
    };
  }

  onMount(loadAll);
</script>

{#if loading}
  <p>Loading wizard…</p>
{:else if error}
  <p style="color: red;">{error}</p>
{:else if estimate}
  <h2>Estimate Wizard — {estimate.estimate_number}</h2>
  <p>
    <a href={`#/estimates/${estimate.estimate_id}`}>← Back to estimate</a>
  </p>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
    <div>
      <h3>Source pool (worksheet atoms)</h3>
      <WizardSourcePool {sourcePool} bind:selectedAtoms />
    </div>
    <div>
      <h3>Line items</h3>
      {#if lineItems.length === 0}
        <p><em>No line items yet. Select atoms and "Create new line item from selected" below.</em></p>
      {/if}
      {#each lineItems as li (li.line_item_id)}
        <WizardLineItemCard
          lineItem={li}
          onAddSelected={addAtomsToLineItem}
          onRemoveSource={(srcId) => removeSource(li.line_item_id, srcId)}
          {canAddHere}
        />
      {/each}
    </div>
  </div>

  <WizardFooter
    selectedCount={selectedAtoms.length}
    onCreateNew={createNewLineItem}
    canAct={canAddHere}
  />
{/if}
```

- [ ] **Step 2: Register the route**

Modify `frontend/src/App.svelte`. Add the import:

```javascript
import EstimateWizardPage from './routes/estimates/EstimateWizardPage.svelte';
```

Add to `routes`:

```javascript
'/estimates/:id/wizard': EstimateWizardPage,
```

- [ ] **Step 3: Verify build**

Run `cd frontend && npm run build`. Expect a clean build.

- [ ] **Step 4: Manual end-to-end verification**

With both servers running:

1. Open a worksheet that has at least one PlanCharge and one PlanMaterial.
2. Click "Open wizard to group atoms" — should land on `/#/estimates/<id>/wizard`.
3. Verify both atoms appear as available checkboxes in the source pool.
4. Tick one atom and click "Create new line item from selected" — a new line item card should appear.
5. Tick another atom and click "Add selected atoms here" on the existing card — line item should now show 2 sources.
6. Click "Remove" on one source — line item drops to 1 source.
7. Click "Remove" on the last source — line item disappears.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/estimates/EstimateWizardPage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add EstimateWizardPage mirroring invoice wizard"
```

---

## Phase 4 — Wire the JobDetail estimate links

### Task 6: Link to new Svelte estimate routes from `JobDetail`

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

Today the JobDetail accordion section for estimates links to the old HTML `generate-estimate` view. Update those to point at the new Svelte routes.

- [ ] **Step 1: Find existing estimate links**

Open `frontend/src/components/jobs/JobDetail.svelte`. Search for:
- `generate-estimate` (HTML view link, around line 200)
- `currentEstimate` references (used for the estimate accordion section)

- [ ] **Step 2: Replace links with SPA hash routes**

Change the "Generate Estimate" link to point at the worksheet's "send all atoms" / "open wizard" buttons that already exist on the WorksheetDetailPage. Replace:

```svelte
<a href="#/worksheets/{currentWorksheet.est_worksheet_id}/generate-estimate">Generate Estimate</a>
```

With:

```svelte
<a href={`#/worksheets/${currentWorksheet.est_worksheet_id}`}>Open worksheet to send atoms</a>
```

For the current estimate display, add a link to the new SPA route:

```svelte
{#if currentEstimate}
  <a href={`#/estimates/${currentEstimate.estimate_id}`}>
    View estimate {currentEstimate.estimate_number}
  </a>
{/if}
```

(Place this in the same section that currently shows estimate metadata — search for `currentEstimate.estimate_number`.)

- [ ] **Step 3: Verify in browser**

Reload the SPA and visit a job detail page. Confirm:
- The estimate accordion section shows a link to the new SPA estimate page.
- Clicking it lands on `/#/estimates/<id>` and renders the Plan B page.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat(frontend): link JobDetail to new Svelte estimate routes"
```

---

## Phase 5 — Verification

### Task 7: End-to-end manual verification

- [ ] **Step 1: Build the frontend**

Run `cd frontend && npm run build`. Expect a clean build with no errors.

- [ ] **Step 2: Backend test suite**

Run `python manage.py test -v 1`. All tests should pass (Plan A's tests, plus everything pre-existing).

- [ ] **Step 3: Smoke test the wizard end-to-end**

Start both servers. Log in via `?autologin`. Walk through:

1. **Create a worksheet** with at least 2 PlanCharges and 1 PlanMaterial (use the existing PlanTaskModal/PlanMaterialModal flows).
2. **Open the worksheet** — confirm the new "Send all atoms" and "Open wizard" buttons appear.
3. **Send all atoms** — should navigate to the estimate page with one line item per atom.
4. **Open the wizard** from the estimate page — confirm all atoms show as `claimed_by_current`.
5. **Remove a source** from one of the line items in the wizard. Confirm the source pool atom moves back to `available`.
6. **Tick the freed atom + another atom** and click "Create new line item from selected" — confirm a new line item appears with 2 sources.
7. **Direct line item via catalog picker:** back on the estimate page, type in the picker, pick a TaskTemplate. Confirm the inline form pre-fills with template values. Save.
8. **Direct line item from PriceListItem:** repeat with a price list item.
9. **Manual line item:** click "Or enter manually." Confirm form opens blank. Enter values and save.

- [ ] **Step 4: Commit (if any cleanup needed)**

If verification surfaced fixes, commit them. Otherwise no commit.

---

## Self-review

**Spec coverage:** Plan B implements the design's "Catalog flow + UI" section, the worksheet "Send all" / "Group via wizard" operations, and the wizard UI for estimates (mirroring the invoice wizard). Direct estimate line items can be created via the catalog picker (TaskTemplate or PriceListItem) or manually, fulfilling the gap-fill described in the spec.

**Out of scope (deferred to follow-ups or Plan C):**
- Refactoring `PlanTaskModal` / `PlanMaterialModal` to use `CatalogPicker` (cosmetic; the existing modals continue to work)
- Wiring `CatalogPicker` into Job (for atom creation) and Invoice (for direct line items) — both work today via existing pickers and modals
- Removing the old "generate estimate" Django HTML view (Plan C cleanup)
- New Job state `in_progress` and Job Board color updates (Plan C)
- Atom carry-over service on Estimate `accepted` (Plan C)
- Modifier toggle UI in the catalog picker form (deferred per spec "Open questions")

**Placeholder scan:** No "TBD" or vague language. Each step has either a code block or a specific manual-verification action.

**Type consistency:** The `onSelect` callback on `CatalogPicker` returns `{kind, item}` consistently. Atom shape `{type: 'plan_charge'|'plan_material', id: number}` matches Plan A's API. The wizard endpoints called here (`source-pool`, `line-items-from-atoms`, `add-atoms`, `remove-atoms`, `send-all-atoms-to-estimate`) all match Plan A's URL conventions.
