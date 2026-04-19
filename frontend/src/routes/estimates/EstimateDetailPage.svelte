<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import EstimateLineItemModal from '../../components/EstimateLineItemModal.svelte';

  let { params = {} } = $props();

  let estimate = $state(null);
  let job = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  let modalOpen = $state(false);
  let modalMode = $state('create');
  let modalItem = $state(null);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  let lineItems = $derived(
    (estimate?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );
  let subtotal = $derived(
    lineItems.reduce((s, li) => s + Number(li.qty) * Number(li.price), 0)
  );
  let categoryById = $derived(
    Object.fromEntries(categories.map(c => [c.id, c]))
  );
  let isSuperseded = $derived(estimate?.status === 'superseded');
  let isDraft = $derived(estimate?.status === 'draft');
  let canEdit = $derived(canManageJobs && isDraft);

  async function loadEstimate() {
    loading = true;
    error = '';
    try {
      estimate = await api.get(`/api/estimates/${params.id}/`);
      if (estimate?.job) {
        try {
          job = await api.get(`/api/jobs/${estimate.job}/`);
        } catch (_) {
          job = null;
        }
      }
    } catch (e) {
      error = e.message || 'Could not load estimate.';
    } finally {
      loading = false;
    }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) {
      categories = [];
    }
  }

  $effect(() => {
    if (params.id) {
      loadEstimate();
      loadCategories();
    }
  });

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString();
  }

  function fmtMoney(n) {
    return `$${Number(n).toFixed(2)}`;
  }

  function lineTotal(li) {
    return Number(li.qty) * Number(li.price);
  }

  function categoryName(id) {
    return categoryById[id]?.name || '—';
  }

  function categoryTaxable(id) {
    const c = categoryById[id];
    if (!c) return '—';
    return c.taxable ? 'Yes' : 'No';
  }

  function sourceLabel(li) {
    if (li.task) return `Task #${li.task}`;
    if (li.price_list_item) return `PLI #${li.price_list_item}`;
    return 'No source';
  }

  function openAddItem() {
    modalItem = null;
    modalMode = 'create';
    modalOpen = true;
  }

  function openEditItem(li) {
    modalItem = li;
    modalMode = 'edit';
    modalOpen = true;
  }

  function handleSaved() {
    modalOpen = false;
    modalItem = null;
    loadEstimate();
  }

  async function handleDeleteItem(li) {
    if (!confirm(`Delete line item "${li.description || 'No description'}"?`)) return;
    try {
      await api.delete(`/api/estimates/${estimate.estimate_id}/line-items/${li.line_item_id}/`);
      await loadEstimate();
    } catch (e) {
      alert(e.message || 'Could not delete line item.');
    }
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(`/api/estimates/${estimate.estimate_id}/line-items/reorder/`, {
        item_ids: itemIds,
      });
      await loadEstimate();
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
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if estimate}
  <h2 class:superseded={isSuperseded}>Estimate: {estimate.estimate_number}</h2>

  <table border="1" class:superseded={isSuperseded}>
    <tbody>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Estimate Number</td><td>{estimate.estimate_number}</td></tr>
      <tr>
        <td>Job</td>
        <td>
          {#if job}
            <a href={`/jobs/${estimate.job}`} use:link>{job.job_number}{job.name ? `: ${job.name}` : ''}</a>
          {:else}
            <a href={`/jobs/${estimate.job}`} use:link>Job #{estimate.job}</a>
          {/if}
        </td>
      </tr>
      <tr><td>Version</td><td>{estimate.version}</td></tr>
      <tr><td>Status</td><td>{estimate.status}</td></tr>
      <tr><td>Created Date</td><td>{fmtDate(estimate.created_date)}</td></tr>
      <tr><td>Sent Date</td><td>{estimate.sent_date ? fmtDate(estimate.sent_date) : 'Not sent yet'}</td></tr>
      <tr><td>Expiration Date</td><td>{estimate.expiration_date ? fmtDate(estimate.expiration_date) : 'Not set'}</td></tr>
      <tr><td>Closed Date</td><td>{estimate.closed_date ? fmtDate(estimate.closed_date) : 'Not closed yet'}</td></tr>
    </tbody>
  </table>

  {#if estimate.parent}
    <p><strong>Parent Estimate:</strong> <a href={`/estimates/${estimate.parent}`} use:link>#{estimate.parent}</a></p>
  {/if}

  {#if isSuperseded}
    <p><em>This estimate has been superseded and cannot be modified.</em></p>
  {/if}

  <h3>Line Items</h3>
  {#if canEdit}
    <p><button type="button" onclick={openAddItem}>Add Line Item</button></p>
  {/if}
  {#if lineItems.length > 0}
    <table border="1" style="border-collapse: collapse; width: 100%; margin-top: 10px;">
      <thead>
        <tr>
          <th>Line #</th>
          <th>Type</th>
          <th>Taxable</th>
          <th>Description</th>
          <th>Source</th>
          <th>Quantity</th>
          <th>Unit</th>
          <th>Price</th>
          <th>Total</th>
          {#if canEdit}<th>Actions</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each lineItems as li, i}
          <tr>
            <td>{li.line_number}</td>
            <td>{categoryName(li.accounting_category)}</td>
            <td>{categoryTaxable(li.accounting_category)}</td>
            <td>{li.description || 'No description'}</td>
            <td>{sourceLabel(li)}</td>
            <td>{li.qty}</td>
            <td>{li.units || '—'}</td>
            <td>{fmtMoney(li.price)}</td>
            <td>{fmtMoney(lineTotal(li))}</td>
            {#if canEdit}
              <td>
                <button type="button" onclick={() => openEditItem(li)}>Edit</button>
                <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
                <button type="button" onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
                <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr style="background-color: #f5f5f5;">
          <td colspan={canEdit ? 8 : 8} style="text-align: right;"><strong>Subtotal:</strong></td>
          <td>{fmtMoney(subtotal)}</td>
          {#if canEdit}<td></td>{/if}
        </tr>
        <tr style="background-color: #e8e8e8;">
          <td colspan={canEdit ? 8 : 8} style="text-align: right;"><strong>Total:</strong></td>
          <td><strong>{fmtMoney(subtotal)}</strong></td>
          {#if canEdit}<td></td>{/if}
        </tr>
      </tfoot>
    </table>
  {:else}
    <p>No line items found for this estimate.</p>
  {/if}

  <p>
    <a href={`/jobs/${estimate.job}`} use:link>View Job Details</a>
  </p>

  <EstimateLineItemModal
    open={modalOpen}
    mode={modalMode}
    estimateId={estimate.estimate_id}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .superseded { opacity: 0.6; }
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }
</style>
