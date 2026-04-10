<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import WizardSourcePool from '../../components/invoices/WizardSourcePool.svelte';
  import WizardLineItemCard from '../../components/invoices/WizardLineItemCard.svelte';
  import WizardFooter from '../../components/invoices/WizardFooter.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let selectedLineItemId = $state(null);
  let loading = $state(true);
  let error = $state(null);

  function selectLineItem(id) {
    selectedLineItemId = id;
  }

  // Initial load — fetches everything once, including source pool.
  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [inv, items, pool] = await Promise.all([
        api.get(`/api/invoices/${params.id}/`),
        api.get(`/api/invoices/${params.id}/line-items/`),
        api.get(`/api/invoices/${params.id}/source-pool/`),
      ]);
      invoice = inv;
      lineItems = items;
      sourcePool = pool;
      reconcileAtomStates();
    } catch (e) {
      error = e.message || 'Failed to load wizard';
    } finally {
      loading = false;
    }
  }

  // Post-action refresh — fetches ONLY invoice and line items, then updates
  // atom states in the existing source pool. Does NOT re-fetch the pool.
  async function reloadLineItems() {
    try {
      const [inv, items] = await Promise.all([
        api.get(`/api/invoices/${params.id}/`),
        api.get(`/api/invoices/${params.id}/line-items/`),
      ]);
      invoice = inv;
      lineItems = items;
      reconcileAtomStates();
      selectedAtoms = [];
    } catch (e) {
      error = e.message || 'Failed to reload';
    }
  }

  // Walk the source pool and update each atom's state based on current line items.
  // claimed_by_other atoms (snapshotted at mount) are left alone.
  function reconcileAtomStates() {
    if (!sourcePool) return;
    const claimMap = new Map();
    for (const li of lineItems) {
      for (const src of li.sources || []) {
        claimMap.set(`${src.source_type}:${src.source_pk}`, li.line_item_id);
      }
    }
    for (const wo of sourcePool.work_orders) {
      for (const task of wo.tasks) {
        for (const atom of task.atoms) {
          if (atom.state === 'claimed_by_other') continue;
          const key = `${atom.atom_type}:${atom.atom_id}`;
          if (claimMap.has(key)) {
            atom.state = 'claimed_by_current';
            atom.claiming_line_item_id = claimMap.get(key);
          } else {
            atom.state = 'available';
            atom.claiming_line_item_id = null;
          }
        }
      }
    }
    sourcePool = {...sourcePool};  // trigger Svelte reactivity
  }

  onMount(loadAll);
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else if invoice}
  <h2>Build Invoice — {invoice.job_number}</h2>
  <p>Draft {invoice.invoice_number} · {lineItems.length} line items</p>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
    <div>
      <h3>Source pool</h3>
      <WizardSourcePool {sourcePool} bind:selectedAtoms />
    </div>
    <div>
      <h3>Line items</h3>
      {#each lineItems as lineItem}
        <WizardLineItemCard
          {lineItem}
          invoiceId={invoice.invoice_id}
          selected={selectedLineItemId === lineItem.line_item_id}
          onselect={selectLineItem}
          onchange={reloadLineItems}
        />
      {/each}
    </div>
  </div>

  <WizardFooter
    invoiceId={invoice.invoice_id}
    {selectedAtoms}
    {selectedLineItemId}
    onchange={reloadLineItems}
  />
{/if}
