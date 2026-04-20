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
    // kind === 'manual': open blank form
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
          <th>Price</th><th>Category</th><th></th>
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
            <td>{li.accounting_category || '—'}</td>
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

    {#if addOpen}
      <fieldset>
        <legend><strong>New line item</strong></legend>
        <p><label for="new-desc"><strong>Description</strong></label><br>
          <input id="new-desc" type="text" bind:value={newDescription}></p>
        <p><label for="new-qty"><strong>Qty</strong></label><br>
          <input id="new-qty" type="number" step="0.01" bind:value={newQty}></p>
        <p><label for="new-units"><strong>Units</strong></label><br>
          <input id="new-units" type="text" bind:value={newUnits}></p>
        <p><label for="new-price"><strong>Price</strong></label><br>
          <input id="new-price" type="number" step="0.01" bind:value={newPrice}></p>
        <p><label for="new-cat"><strong>Accounting category</strong></label><br>
          <select id="new-cat" bind:value={newCategoryId}>
            <option value="">— None —</option>
            {#each categories as c}
              <option value={c.accounting_category_id}>{c.name}</option>
            {/each}
          </select></p>
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
