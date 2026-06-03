# Direct-Create + Catalog Line Items (Estimates & Invoices) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user create an estimate or invoice directly from a job (empty, by hand) and edit its line items — **manual** or from the **price-list catalog** — in the Svelte SPA, with a clean "Create / View" button model on the job overview and a renamed source-pull view ("Show Worksheet" / "Show Billables").

**Architecture:** The backend already exposes everything: `POST /api/estimates/` (→ `EstimateService.create_for_job`), `POST /api/invoices/` (to be routed through `InvoiceWizardService.open_for_job`), and a shared `LineItemMixin` whose `POST .../line-items/` branches on `price_list_item` (catalog) vs manual fields. The work is mostly frontend: one shared `LineItemModal.svelte` (manual ⇄ "From Price List" toggle, reusing `PriceListItemPicker`) replaces the manual-only `EstimateLineItemModal` and powers a new editing toolbar on the invoice detail page; the job-overview pillars collapse to **Create** + **View**; the standalone atom-pull pages get renamed entry points and headers that match the detail pages.

**Tech Stack:** Django 5.2 + DRF (backend), Svelte 5 runes SPA + Vite (frontend), MySQL, Django `TestCase` for tests.

## Locked design decisions (brainstorming 2026-06-02)

**Button model — job overview (both object types):** Per container, the overview shows only **View** (always, when one exists) and a conditional **Create** (empty container → its detail page). No Revise, no wizard button on the overview. All editing lives on the detail page.

**Estimate Create gate (one estimate tree per job — frontend-enforced; backend unchanged):**
`canManageJobs && job.status ∈ {draft, submitted} && !currentEstimate`. Once any non-superseded estimate exists, or the job advances past `submitted`, Create disappears — from then on it's change orders only. Never in terminal (`completed`/`rejected`/`cancelled`) or `on_hold`.

**Invoice Create gate (many invoices allowed):**
`(canManageJobs || canManageFinancials) && job.status ∈ {approved, in_progress, work_complete, completed, cancelled} && !draftInvoice`. (Job-status set widened to match the backend `BILLABLE_JOB_STATUSES`.)

**Invoice creation goes through a service** (`open_for_job`, get-or-create + guard), not a bare `serializer.save()`.

**Catalog = PriceListItems only.** The manual/catalog toggle appears only when **adding**; editing an existing line edits its fields only (even if PLI-derived).

**Source-pull view ("wizard") rename + gating:** "Show Worksheet" on the estimate detail page, shown **only when the estimate has a worksheet**. "Show Billables" on the invoice detail page, shown **only when the job has billable atoms (tasks)**. Both are **approach (a)**: the button navigates to the existing `/…/:id/wizard` route. (Approach (b) — folding the pull view into the detail page as an in-place toggle — is logged in `docs/designs/LATER.md`.)

**Headers of the detail ("normal") view and the source-pull ("wizard") view must match** for both object types, so navigating between them feels continuous (Task 8).

**Revise:** removed from both overviews (the overview links were dead routes anyway). Estimate revise already works on its detail page. **Invoice revise is added to the invoice detail page as a disabled placeholder** — invoice revisions are out of scope for this batch (no backend exists).

**POs keep their own `LineItemForm`** (different pricing — `purchase_price` — and a job picker). Not unified here.

A related deferred question (re-billing a Task's grown actuals across multiple invoices) is logged in `docs/designs/LATER.md` and is **not** part of this plan.

---

## File Structure

**Backend (1 file modified):**
- `apps/api/invoicing/views.py` — `InvoiceViewSet.perform_create` → `InvoiceWizardService.open_for_job` with a 400 on the guard error.

**Frontend — new shared component:**
- `frontend/src/components/LineItemModal.svelte` — add/edit modal; manual ⇄ catalog toggle on add; manual-only on edit; owns POST/PATCH against a parameterized `apiBase`.

**Frontend — modified:**
- `frontend/src/routes/estimates/EstimateDetailPage.svelte` — use `LineItemModal`; rename atom link → "Show Worksheet".
- `frontend/src/routes/invoices/InvoiceDetailPage.svelte` — add editing toolbar + `LineItemModal`; "Show Billables" link; placeholder Revise.
- `frontend/src/routes/estimates/EstimateWizardPage.svelte` — header matches the detail page (JobHeader + toolbar).
- `frontend/src/routes/invoices/InvoiceWizardPage.svelte` — header matches the detail page (JobHeader + toolbar).
- `frontend/src/components/jobs/JobDetail.svelte` — estimate & invoice pillars → Create/View model; new `createEstimate` / `createInvoiceManual` handlers; new `canCreateEstimate` / `canCreateInvoice` derived.
- `frontend/src/routes/jobs/JobDetailPage.svelte` — remove the now-unused `startWizard` / `onStartWizard` wiring.

**Frontend — deleted:**
- `frontend/src/components/EstimateLineItemModal.svelte` — superseded by `LineItemModal`.

**Docs:** `docs/designs/estimates-and-prices.md`, `docs/designs/invoicing-and-expenses.md`.

---

## Task 1: Route invoice creation through the service layer

`InvoiceViewSet.perform_create` is a bare `serializer.save()` that bypasses the billable-job guard and the `unique_draft_invoice_per_job` constraint (→ 500 on a second create). Funnel it through `InvoiceWizardService.open_for_job`, mirroring `EstimateViewSet.perform_create` → `create_for_job`.

**Files:**
- Modify: `apps/api/invoicing/views.py` (imports + `perform_create`, lines 1-10 and 44-45)
- Test: `tests/test_api_invoice_direct_create.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_invoice_direct_create.py`:

```python
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.invoicing.models import Invoice


class InvoiceDirectCreateAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.billable_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )

    def test_direct_create_returns_draft_invoice(self):
        resp = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['status'], Invoice.STATUS_DRAFT)
        self.assertTrue(resp.data['invoice_number'])

    def test_direct_create_is_idempotent_for_existing_draft(self):
        first = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        second = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        self.assertIn(second.status_code, [200, 201])
        self.assertEqual(first.data['invoice_id'], second.data['invoice_id'])
        self.assertEqual(Invoice.objects.filter(job=self.billable_job).count(), 1)

    def test_direct_create_rejected_for_non_billable_job(self):
        draft_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002',
        )
        resp = self.client.post('/api/invoices/', {'job': draft_job.pk}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Invoice.objects.filter(job=draft_job).count(), 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python manage.py test tests.test_api_invoice_direct_create -v 2`
Expected: the idempotency test fails (500/IntegrityError) and the non-billable test fails (got 201, not 400).

- [ ] **Step 3: Implement the service-routed `perform_create`**

In `apps/api/invoicing/views.py`, update the imports (add `serializers as drf_serializers` to the rest_framework import and `InvoiceWizardService` to the services import):

```python
from rest_framework import serializers as drf_serializers, status, viewsets
from apps.invoicing.services import InvoiceService, InvoiceWizardService
```

Replace `perform_create`:

```python
    def perform_create(self, serializer):
        job = serializer.validated_data.get('job')
        try:
            invoice = InvoiceWizardService.open_for_job(job)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            raise drf_serializers.ValidationError({'detail': msg})
        serializer.instance = invoice
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python manage.py test tests.test_api_invoice_direct_create -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Regression check on the wizard suites**

Run: `python manage.py test tests.test_invoice_wizard_api tests.test_invoice_wizard_service -v 2`
Expected: PASS (the wizard already used `open_for_job`).

- [ ] **Step 6: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_api_invoice_direct_create.py
git commit -m "fix(invoicing): route invoice create through open_for_job service"
```

---

## Task 2: Backend tests for catalog (PLI) line-item adds

Lock the catalog behavior the frontend depends on: posting `{price_list_item, qty}` creates a line whose description/units/price come from the PLI's `selling_price`.

**Files:**
- Test: `tests/test_catalog_line_item_adds.py` (create)

- [ ] **Step 1: Write the test**

Create `tests/test_catalog_line_item_adds.py`:

```python
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.inventory.models import PriceListItem


class CatalogLineItemAddTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.category = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_superuser(username='boss', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.pli = PriceListItem.objects.create(
            code='WIDGET-1', description='Standard widget', units='ea',
            selling_price=Decimal('42.50'), accounting_category=self.category,
        )

    def test_estimate_catalog_add_copies_pli_fields(self):
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )
        resp = self.client.post(
            f'/api/estimates/{est.pk}/line-items/',
            {'price_list_item': self.pli.pk, 'qty': '3'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['price_list_item'], self.pli.pk)
        self.assertEqual(resp.data['description'], 'Standard widget')
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))

    def test_invoice_catalog_add_copies_pli_fields(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        resp = self.client.post(
            f'/api/invoices/{inv.pk}/line-items/',
            {'price_list_item': self.pli.pk, 'qty': '2'}, format='json',
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.data['price_list_item'], self.pli.pk)
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))
```

- [ ] **Step 2: Run the test**

Run: `python manage.py test tests.test_catalog_line_item_adds -v 2`
Expected: PASS. If a `PriceListItem` field name differs, adjust the `create(...)` call to match the model — keep the assertion that `price` equals the PLI's selling price.

- [ ] **Step 3: Commit**

```bash
git add tests/test_catalog_line_item_adds.py
git commit -m "test: lock catalog (PLI) line-item add for estimates and invoices"
```

---

## Task 3: Create the shared `LineItemModal.svelte`

One modal serves both estimate and invoice detail pages. On **add**: Manual ⇄ "From Price List" toggle. On **edit**: manual fields only. Owns the API call against a parameterized `apiBase` (e.g. `/api/estimates/123`).

**Files:**
- Create: `frontend/src/components/LineItemModal.svelte`
- Reference (read only): `frontend/src/components/EstimateLineItemModal.svelte`, `frontend/src/components/purchaseorders/LineItemForm.svelte`, `frontend/src/components/PriceListItemPicker.svelte`, `frontend/src/components/UnitsSelect.svelte`, `frontend/src/lib/modalKeys.js`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/LineItemModal.svelte`:

```svelte
<script>
  import { api } from '../lib/api.js';
  import UnitsSelect from './UnitsSelect.svelte';
  import PriceListItemPicker from './PriceListItemPicker.svelte';
  import { modalKeys } from '../lib/modalKeys.js';

  let {
    open = false,
    mode = 'create',          // 'create' | 'edit'
    apiBase = '',             // e.g. '/api/estimates/123' or '/api/invoices/123'
    item = null,              // line item being edited (edit mode)
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let entryMode = $state('manual'); // 'manual' | 'pli' — catalog only on add
  let selectedPLI = $state(null);

  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      entryMode = 'manual';
      selectedPLI = null;
      if (mode === 'edit' && item) {
        description = item.description || '';
        qty = item.qty ?? '';
        units = item.units || 'none';
        price = item.price ?? '';
        accountingCategory = item.accounting_category ?? '';
      } else {
        description = '';
        qty = '';
        units = 'none';
        price = '';
        accountingCategory = '';
      }
      error = '';
    }
  });

  function handlePLISelect(pli) {
    selectedPLI = pli;
    if (pli) {
      // Preview only; the server copies authoritative values from the PLI.
      description = pli.description || '';
      units = pli.units || 'none';
      price = pli.selling_price ?? '';
      accountingCategory = pli.accounting_category ?? '';
    }
  }

  async function save() {
    busy = true;
    error = '';
    try {
      if (mode === 'create' && entryMode === 'pli') {
        if (!selectedPLI) {
          error = 'Select a price list item.';
          busy = false;
          return;
        }
        await api.post(`${apiBase}/line-items/`, {
          price_list_item: selectedPLI.price_list_item_id,
          qty: qty || '1',
        });
      } else {
        const payload = {
          description,
          qty: qty || '0',
          units,
          price: price || '0',
          accounting_category: accountingCategory || null,
        };
        if (mode === 'edit' && item) {
          await api.patch(`${apiBase}/line-items/${item.line_item_id}/`, payload);
        } else {
          await api.post(`${apiBase}/line-items/`, payload);
        }
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save line item.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit Line Item' : 'Add Line Item'}</h3>

      {#if mode === 'create'}
        <p>
          <label><input type="radio" bind:group={entryMode} value="manual"> Manual</label>
          <label><input type="radio" bind:group={entryMode} value="pli"> From Price List</label>
        </p>
      {/if}

      {#if mode === 'create' && entryMode === 'pli'}
        <p>
          <label><strong>Price List Item *</strong></label><br>
          <PriceListItemPicker
            value={selectedPLI?.price_list_item_id}
            selectedItem={selectedPLI}
            onSelect={handlePLISelect}
          />
        </p>
        <p>
          <label><strong>Quantity *</strong><br>
            <input type="number" step="0.01" min="0" bind:value={qty}>
          </label>
        </p>
      {:else}
        <p>
          <label><strong>Description *</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Quantity</strong><br>
            <input type="number" step="0.01" bind:value={qty}>
          </label>
        </p>
        <p>
          <label><strong>Units</strong><br>
            <UnitsSelect bind:value={units} />
          </label>
        </p>
        <p>
          <label><strong>Price</strong><br>
            <input type="number" step="0.01" bind:value={price}>
          </label>
        </p>
        <p>
          <label><strong>Line Item Type</strong><br>
            <select bind:value={accountingCategory}>
              <option value="">-- None --</option>
              {#each categories as cat}
                <option value={cat.id}>{cat.code} - {cat.name}</option>
              {/each}
            </select>
          </label>
        </p>
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal { background: white; padding: 16px; max-width: 500px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds (component not yet wired into a route; this only checks it parses).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/LineItemModal.svelte
git commit -m "feat(frontend): shared LineItemModal with manual/catalog toggle"
```

---

## Task 4: Estimate detail page — `LineItemModal` + "Show Worksheet"

Point the estimate detail page at the shared modal (gaining catalog adds) and rename the atom-pull link. (Estimate revise already exists here and is unchanged.)

**Files:**
- Modify: `frontend/src/routes/estimates/EstimateDetailPage.svelte` (import line 5; atom link line 264; modal lines 287-295)
- Delete: `frontend/src/components/EstimateLineItemModal.svelte`

- [ ] **Step 1: Swap the import**

Change line 5:

```svelte
  import EstimateLineItemModal from '../../components/EstimateLineItemModal.svelte';
```

to:

```svelte
  import LineItemModal from '../../components/LineItemModal.svelte';
```

- [ ] **Step 2: Rename the atom-pull link to "Show Worksheet"**

Replace line 264:

```svelte
        <a href={`/estimates/${estimate.estimate_id}/wizard`} use:link>Open atoms wizard</a>
```

with:

```svelte
        <a href={`/estimates/${estimate.estimate_id}/wizard`} use:link>Show Worksheet</a>
```

(The surrounding `{#if estimate.worksheet}` guard at line 263 stays — the pull view is offered only when a worksheet is attached.)

- [ ] **Step 3: Swap the modal element**

Replace lines 287-295:

```svelte
  <EstimateLineItemModal
    open={modalOpen}
    mode={modalMode}
    estimateId={estimate.estimate_id}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
```

with:

```svelte
  <LineItemModal
    open={modalOpen}
    mode={modalMode}
    apiBase={`/api/estimates/${estimate.estimate_id}`}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
```

- [ ] **Step 4: Delete the superseded modal and confirm no references remain**

Run: `git rm frontend/src/components/EstimateLineItemModal.svelte`
Run: `grep -rn "EstimateLineItemModal" frontend/src/`
Expected: no matches.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/estimates/EstimateDetailPage.svelte
git commit -m "feat(estimates): catalog line items + Show Worksheet rename"
```

---

## Task 5: Estimate pillar — Create/View model on the job overview

Collapse the estimate pillar's actions to **View Full Estimate** (when an estimate exists) plus a conditional **Create Estimate** button. Remove the dead Revise link. Keep the change-order button untouched.

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte` (new derived + handler near line 300; markup at lines 633-649)

- [ ] **Step 1: Add the derived gate and handler**

Near the existing `createChangeOrder` handler (around line 300), add:

```javascript
  let creatingEstimate = $state(false);

  let canCreateEstimate = $derived(
    canManageJobs &&
    (job.status === 'draft' || job.status === 'submitted') &&
    !currentEstimate
  );

  async function createEstimate() {
    creatingEstimate = true;
    try {
      const est = await api.post('/api/estimates/', { job: job.job_id });
      window.location.hash = `/estimates/${est.estimate_id}`;
    } catch (e) {
      alert(e.data?.detail || e.message || 'Failed to create estimate.');
    } finally {
      creatingEstimate = false;
    }
  }
```

- [ ] **Step 2: Replace the estimate top-bar actions**

Replace the block at lines 633-649:

```svelte
        <span class="top-bar-actions">
          {#if displayedVersion?.kind === 'co'}
            <a href="#/change-orders/{displayedVersion.co.change_order_id}">View Change Order</a>
          {:else if displayedEstimate}
            <a href="#/estimates/{displayedEstimate.estimate_id}">View Full Estimate</a>
            {#if canManageJobs && (displayedEstimate.status === 'open' || displayedEstimate.status === 'accepted')}
              <a href="#/estimates/{displayedEstimate.estimate_id}/revise">Revise Estimate</a>
            {/if}
          {/if}
          {#if canManageJobs && !currentEstimate}
            <a href="#/jobs/{job.job_id}/create-estimate">Create Estimate</a>
          {/if}
          {#if canManageJobs && job.status === 'on_hold' && !hasLiveChangeOrder}
            <button type="button" onclick={createChangeOrder} disabled={creatingCo}>
              {creatingCo ? 'Creating…' : '+ New change order'}
            </button>
          {/if}
        </span>
```

with:

```svelte
        <span class="top-bar-actions">
          {#if displayedVersion?.kind === 'co'}
            <a href="#/change-orders/{displayedVersion.co.change_order_id}">View Change Order</a>
          {:else if displayedEstimate}
            <a href="#/estimates/{displayedEstimate.estimate_id}">View Full Estimate</a>
          {/if}
          {#if canCreateEstimate}
            <button type="button" onclick={createEstimate} disabled={creatingEstimate}>
              {creatingEstimate ? 'Creating…' : 'Create Estimate'}
            </button>
          {/if}
          {#if canManageJobs && job.status === 'on_hold' && !hasLiveChangeOrder}
            <button type="button" onclick={createChangeOrder} disabled={creatingCo}>
              {creatingCo ? 'Creating…' : '+ New change order'}
            </button>
          {/if}
        </span>
```

- [ ] **Step 3: Confirm no remaining dead estimate links**

Run: `grep -rn "create-estimate\|estimates/.*revise" frontend/src/`
Expected: no matches (the `/estimates/:id/revise` overview link is gone; estimate revise stays as the in-page button on the detail page, which posts to the API and does not use that route).

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual verification**

As `can_manage_jobs`: on a `draft`/`submitted` job with no estimate → **Create Estimate** appears, creates a draft, lands on `#/estimates/<id>`; the detail page shows Add Line Item (manual/catalog). Once the estimate exists, only **View Full Estimate** shows. On an `approved`+ job, no Create — only View. On `on_hold`, the change-order button still appears.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat(estimates): Create/View pillar model on job overview"
```

---

## Task 6: Invoice detail page — line-item editing, "Show Billables", placeholder Revise

Bring the invoice detail page to parity: Add/Edit/Delete/reorder toolbar (draft + `can_manage_financials`), a "Show Billables" link (only when the job has billable atoms), and a disabled Revise placeholder for sent invoices.

**Files:**
- Modify: `frontend/src/routes/invoices/InvoiceDetailPage.svelte`

- [ ] **Step 1: Add imports and editing state**

After the `LineItemTable` import (line 8), add:

```svelte
  import LineItemModal from '../../components/LineItemModal.svelte';
```

After the `canEditInvoice` derived (lines 20-23), add:

```javascript
  const canManageFinancials = $derived(
    $user?.permissions?.includes('can_manage_financials') ?? false
  );
  let canEditLineItems = $derived(canManageFinancials && invoice?.status === 'draft');
  // "Show Billables" when the job has anything billable to pull from — tasks
  // OR materials. (A job can carry materials with no tasks; Material.job is a
  // direct FK and JobSerializer exposes both `tasks` and `materials`.) The pool
  // may still be empty of logged actuals — that's fine, we still offer the view.
  let hasBillables = $derived(
    (job?.tasks?.length ?? 0) > 0 || (job?.materials?.length ?? 0) > 0
  );
  // Revise placeholder: visible on sent invoices, not yet functional.
  let canSeeRevise = $derived(
    canManageFinancials && (invoice?.status === 'open' || invoice?.status === 'partly-paid')
  );

  let modalOpen = $state(false);
  let modalMode = $state('create');
  let modalItem = $state(null);

  let lineItems = $derived(
    (invoice?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );

  function openAddItem() { modalItem = null; modalMode = 'create'; modalOpen = true; }
  function openEditItem(li) { modalItem = li; modalMode = 'edit'; modalOpen = true; }
  function handleSaved() { modalOpen = false; modalItem = null; loadInvoice(); }

  async function handleDeleteItem(li) {
    if (!confirm(`Delete line item "${li.description || 'No description'}"?`)) return;
    try {
      await api.delete(`/api/invoices/${invoice.invoice_id}/line-items/${li.line_item_id}/`);
      await loadInvoice();
    } catch (e) {
      alert(e.message || 'Could not delete line item.');
    }
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/line-items/reorder/`, { item_ids: itemIds });
      await loadInvoice();
    } catch (e) {
      alert(e.message || 'Could not reorder line items.');
    }
  }

  function moveUp(index) {
    if (index === 0) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    handleReorder(ids);
  }

  function moveDown(index) {
    if (index >= lineItems.length - 1) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
    handleReorder(ids);
  }
```

- [ ] **Step 2: Add a Revise placeholder to the toolbar**

In the toolbar, after the existing Send link block (lines 83-87), add:

```svelte
    {#if canSeeRevise}
      <button type="button" disabled title="Invoice revisions are not available yet.">
        Revise (coming soon)
      </button>
    {/if}
```

- [ ] **Step 3: Replace the read-only line-items section**

Replace lines 113-114:

```svelte
  <h3>Line Items</h3>
  <LineItemTable lineItems={invoice.line_items || []} {categories} />
```

with:

```svelte
  <h3>Line Items</h3>
  {#if canEditLineItems}
    <p>
      <button type="button" onclick={openAddItem}>Add Line Item</button>
      {#if hasBillables}
        <a href={`/invoices/${invoice.invoice_id}/wizard`} use:link>Show Billables</a>
      {/if}
    </p>
  {/if}

  {#snippet actionsSnippet(li, i)}
    <button type="button" onclick={() => openEditItem(li)}>Edit</button>
    <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
    <button type="button" onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
    <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
  {/snippet}

  <LineItemTable
    {lineItems}
    {categories}
    showSource={true}
    actions={canEditLineItems ? actionsSnippet : null}
  />

  <LineItemModal
    open={modalOpen}
    mode={modalMode}
    apiBase={`/api/invoices/${invoice.invoice_id}`}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
```

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual verification**

As `can_manage_financials`, on a draft invoice: Add Line Item works (manual + catalog); Edit/Delete/▲/▼ work; **Show Billables** appears when the job has tasks **or** materials (verify a job with only materials still shows it) and navigates to the pull view. On a sent (open) invoice: editing buttons gone, **Revise (coming soon)** shows disabled. A `can_manage_jobs`-only user sees no editing buttons.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/invoices/InvoiceDetailPage.svelte
git commit -m "feat(invoicing): detail-page editing, Show Billables, Revise placeholder"
```

---

## Task 7: Invoice pillar — Create/View model on the job overview

Collapse the invoice pillar to **View Invoice** (when one exists) + conditional **Create Invoice**. Remove the wizard button (it now lives on the detail page as "Show Billables") and the dead Revise link.

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte` (replace `canBuildInvoice` derived at lines 400-403; add handler near `createEstimate`; markup at lines 993-1005)
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte` (remove unused `startWizard` / `onStartWizard`)

- [ ] **Step 1: Replace `canBuildInvoice` with `canCreateInvoice` and add the handler**

Replace the derived at lines 400-403:

```javascript
  let canBuildInvoice = $derived(
    (canManageJobs || canManageFinancials) &&
    (job.status === 'approved' || job.status === 'work_complete' || job.status === 'completed')
  );
```

with:

```javascript
  const BILLABLE_JOB_STATUSES = [
    'approved', 'in_progress', 'work_complete', 'completed', 'cancelled',
  ];
  let creatingInvoice = $state(false);
  let canCreateInvoice = $derived(
    (canManageJobs || canManageFinancials) &&
    BILLABLE_JOB_STATUSES.includes(job.status) &&
    !draftInvoice
  );

  async function createInvoiceManual() {
    creatingInvoice = true;
    try {
      const inv = await api.post('/api/invoices/', { job: job.job_id });
      window.location.hash = `/invoices/${inv.invoice_id}`;
    } catch (e) {
      alert(e.data?.detail || e.message || 'Failed to create invoice.');
    } finally {
      creatingInvoice = false;
    }
  }
```

- [ ] **Step 2: Replace the invoice top-bar actions**

Replace lines 993-1005:

```svelte
        <span class="top-bar-actions">
          {#if displayedInvoice}
            <a href="#/invoices/{displayedInvoice.invoice_id}">View Full Invoice</a>
          {/if}
          {#if canManageJobs && displayedInvoice && (displayedInvoice.status === 'open' || displayedInvoice.status === 'partly-paid')}
            <a href="#/invoices/{displayedInvoice.invoice_id}/revise">Revise Invoice</a>
          {/if}
          {#if canBuildInvoice}
            <button onclick={() => onStartWizard?.()}>
              {draftInvoice ? `Continue draft (${draftInvoice.invoice_number})` : 'Build invoice'}
            </button>
          {/if}
        </span>
```

with:

```svelte
        <span class="top-bar-actions">
          {#if displayedInvoice}
            <a href="#/invoices/{displayedInvoice.invoice_id}">View Invoice</a>
          {/if}
          {#if canCreateInvoice}
            <button type="button" onclick={createInvoiceManual} disabled={creatingInvoice}>
              {creatingInvoice ? 'Creating…' : 'Create Invoice'}
            </button>
          {/if}
        </span>
```

- [ ] **Step 3: Remove the now-unused `onStartWizard` prop usage**

In `frontend/src/components/jobs/JobDetail.svelte`, the `onStartWizard` prop (declared around line 21 as `onStartWizard = null,`) is no longer referenced. Remove that line from the `$props()` destructuring.

In `frontend/src/routes/jobs/JobDetailPage.svelte`:
- Remove the `startWizard` function (lines 45-51).
- Remove the `onStartWizard={startWizard}` prop on the `<JobDetail … />` element (line 83).

- [ ] **Step 4: Confirm cleanup is complete**

Run: `grep -rn "onStartWizard\|startWizard\|canBuildInvoice\|Build invoice\|invoices/.*revise" frontend/src/`
Expected: no matches.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Manual verification**

On a billable job with no draft: **Create Invoice** appears, creates an empty draft, lands on `#/invoices/<id>` where Add Line Item and **Show Billables** are available. With a draft present: Create hidden, **View Invoice** shows. On a sent invoice (no draft) on a billable job: **View Invoice** + **Create Invoice** both show. On a non-billable job: no Create (View only if an invoice exists).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte frontend/src/routes/jobs/JobDetailPage.svelte
git commit -m "feat(invoicing): Create/View pillar model on job overview"
```

---

## Task 8: Match the detail-view and source-pull-view headers

Both atom-pull pages currently render a bare `<h2>` + back link, while the detail pages render `JobHeader` + a toolbar. Make the pull pages use the same `JobHeader` + toolbar so switching between "Show Worksheet"/"Show Billables" and the detail view is visually continuous.

**Files:**
- Modify: `frontend/src/routes/estimates/EstimateWizardPage.svelte`
- Modify: `frontend/src/routes/invoices/InvoiceWizardPage.svelte`
- Reference (read only): `frontend/src/routes/estimates/EstimateDetailPage.svelte` (JobHeader + toolbar markup, lines 181-216), `frontend/src/components/jobs/JobHeader.svelte`

- [ ] **Step 1: Estimate pull page — load job/contact and render the matching header**

In `frontend/src/routes/estimates/EstimateWizardPage.svelte`:

Add the imports (after the existing `api` import):

```svelte
  import { link } from 'svelte-spa-router';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
```

Add state next to the existing `let estimate = $state(null);`:

```javascript
  let job = $state(null);
  let contact = $state(null);
```

In `loadAll`, after `estimate = est;`, fetch the job context:

```javascript
      if (est?.job) {
        try {
          job = await api.get(`/api/jobs/${est.job}/`);
          if (job?.contact) {
            try { contact = await api.get(`/api/contacts/${job.contact}/`); }
            catch (_) { contact = null; }
          }
        } catch (_) { job = null; contact = null; }
      }
```

Replace the header block (lines 139-143):

```svelte
  <h2>Estimate Wizard — {estimate.estimate_number}</h2>
  <p>
    <a href={`#/jobs/${estimate.job}`}>&laquo; Back to Job {estimate.job_number}{estimate.job_name ? ` - ${estimate.job_name}` : ''}</a>
  </p>
```

with:

```svelte
  {#if job}
    <JobHeader {job} {contact} />
  {/if}
  <div class="toolbar">
    <a href={`/estimates/${estimate.estimate_id}`} use:link class="back-link">&laquo; back to estimate</a>
    <span class="page-title">Worksheet: {estimate.estimate_number}</span>
  </div>
```

Add this `.toolbar` style to the component's `<style>` (create a `<style>` block at the end of the file if none exists):

```css
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 24px; }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }
```

- [ ] **Step 2: Invoice pull page — load job/contact and render the matching header**

In `frontend/src/routes/invoices/InvoiceWizardPage.svelte`:

Add imports (after the existing `api` import):

```svelte
  import { link } from 'svelte-spa-router';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
```

Add state next to `let invoice = $state(null);`:

```javascript
  let job = $state(null);
  let contact = $state(null);
```

In `loadAll`, after `invoice = inv;`, fetch the job context:

```javascript
      if (inv?.job) {
        try {
          job = await api.get(`/api/jobs/${inv.job}/`);
          if (job?.contact) {
            try { contact = await api.get(`/api/contacts/${job.contact}/`); }
            catch (_) { contact = null; }
          }
        } catch (_) { job = null; contact = null; }
      }
```

Replace the header block (lines 140-147):

```svelte
  <h2>Build Invoice — {invoice.job_number}</h2>
  <p>
    <a href={`#/jobs/${invoice.job}`}>&laquo; Back to Job {invoice.job_number}{invoice.job_name ? ` - ${invoice.job_name}` : ''}</a>
  </p>
  {#if invoice.job_description}
    <p>{invoice.job_description}</p>
  {/if}
  <p>Draft {invoice.invoice_number} · {lineItems.length} line items</p>
```

with:

```svelte
  {#if job}
    <JobHeader {job} {contact} />
  {/if}
  <div class="toolbar">
    <a href={`/invoices/${invoice.invoice_id}`} use:link class="back-link">&laquo; back to invoice</a>
    <span class="page-title">Billables: {invoice.invoice_number}</span>
  </div>
```

Add the same `.toolbar` styles to this component's `<style>` block:

```css
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 24px; }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }
```

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual verification**

Open an estimate with a worksheet → detail page; click **Show Worksheet**. Expected: the same `JobHeader` (job number/name/contact) sits at the top of both views; only the title line ("Estimate: …" vs "Worksheet: …") and body differ. Repeat for an invoice with billables via **Show Billables**.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/estimates/EstimateWizardPage.svelte frontend/src/routes/invoices/InvoiceWizardPage.svelte
git commit -m "feat(frontend): match detail/source-pull headers for estimates and invoices"
```

---

## Task 9: Update design docs

**Files:**
- Modify: `docs/designs/estimates-and-prices.md`, `docs/designs/invoicing-and-expenses.md`

- [ ] **Step 1: Estimates doc**

Note: (a) the job overview shows **Create Estimate** only while the job is `draft`/`submitted` and no estimate yet exists (one estimate tree per job — UI-enforced; backend unchanged), else **View** only; (b) `Create Estimate` POSTs `{job}` → `EstimateService.create_for_job` (new draft) and lands on the detail page; (c) draft line items support manual + catalog (PriceListItem) adds via `LineItemModal`, catalog posts `{price_list_item, qty}` (server copies description/units/`selling_price`); (d) the atom-pull view is reached via **Show Worksheet** on the detail page, shown only when a worksheet is attached; (e) TaskTemplate catalog adds remain unwired.

- [ ] **Step 2: Invoicing doc**

Note: (a) invoice creation always routes through `InvoiceWizardService.open_for_job` (get-or-create + billable-job guard) for both the pull view and direct `POST /api/invoices/`; (b) the job overview shows **Create Invoice** (when billable + no draft) and **View Invoice** (when one exists), which can appear together; (c) the detail page supports manual + catalog line-item editing on drafts (`can_manage_financials`), reaches the atom-pull view via **Show Billables** (when the job has tasks or materials), and shows a disabled **Revise (coming soon)** placeholder on sent invoices (invoice revisions unimplemented); (d) the detail and pull views share a matching `JobHeader`.

- [ ] **Step 3: Commit**

```bash
git add docs/designs/estimates-and-prices.md docs/designs/invoicing-and-expenses.md
git commit -m "docs: Create/View model + catalog line items for estimates and invoices"
```

---

## Self-Review notes

- **Spec coverage:** invoice create via service → Task 1; catalog backend lock → Task 2; shared modal → Task 3; estimate catalog + Show Worksheet → Task 4; estimate Create/View pillar (one-tree gate, draft/submitted only) → Task 5; invoice detail editing + Show Billables + Revise placeholder → Task 6; invoice Create/View pillar (widened billable statuses, !draftInvoice) → Task 7; matching headers → Task 8; docs → Task 9. Approach (b) and the multi-invoice re-billing question are logged in `docs/designs/LATER.md` (out of scope).
- **Type/name consistency:** `apiBase`, `canCreateEstimate`, `canCreateInvoice`, `creatingEstimate`, `creatingInvoice`, `canEditLineItems`, `hasBillables`, `canSeeRevise`, `currentEstimate`, `draftInvoice` are each defined once and referenced consistently; field names (`estimate_id`, `invoice_id`, `line_item_id`, `price_list_item_id`, `selling_price`, `job.tasks`) match the serializers/components inspected.
- **Dead-route fixes folded in:** Task 5 removes the dead `#/jobs/:id/create-estimate` and `#/estimates/:id/revise` overview links; Task 7 removes the dead `#/invoices/:id/revise` link and the overview wizard button.
- **Frontend testing:** no JS unit-test harness in this repo — frontend tasks verify via `npm run build` + explicit manual steps; backend branching is covered by Django `TestCase` (Tasks 1-2). Run backend tests single-threaded (shared MySQL — never parallel `manage.py test`).
- **DB-write rule:** all DB mutation happens only inside Django tests (separate test DB). No task runs `migrate`, `loaddata`, or dev-DB ORM writes.
