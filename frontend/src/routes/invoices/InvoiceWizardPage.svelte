<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import WizardSourcePool from '../../components/invoices/WizardSourcePool.svelte';
  import WizardLineItemCard from '../../components/wizards/WizardLineItemCard.svelte';
  import WizardActions from '../../components/wizards/WizardActions.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let loading = $state(true);
  let error = $state(null);

  const canAddHere = $derived(selectedAtoms.length > 0);

  async function addAtomsToLineItem(lineItemId) {
    try {
      await api.post(
        `/api/invoices/${invoice.invoice_id}/line-items/${lineItemId}/add-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another invoice. Reopen the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to add atoms');
      }
    }
  }

  async function createNewLineItem() {
    try {
      await api.post(
        `/api/invoices/${invoice.invoice_id}/line-items-from-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another invoice. Reopen the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to create line item');
      }
    }
  }

  async function addManualLineItem() {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/line-items/`, {
        description: '', qty: '1', units: 'each', price: '0.00',
      });
      await reloadLineItems();
    } catch (e) {
      alert(e.message || 'Failed to add manual line item');
    }
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
        claimMap.set(`${src.source_type}:${src.source_pk}`, {
          line_item_id: li.line_item_id,
          line_number: li.line_number,
        });
      }
    }
    for (const task of sourcePool.tasks) {
      for (const atom of task.atoms) {
        if (atom.state === 'claimed_by_other') continue;
        const key = `${atom.atom_type}:${atom.atom_id}`;
        if (claimMap.has(key)) {
          const claim = claimMap.get(key);
          atom.state = 'claimed_by_current';
          atom.claiming_line_item_id = claim.line_item_id;
          atom.claiming_line_number = claim.line_number;
        } else {
          atom.state = 'available';
          atom.claiming_line_item_id = null;
          atom.claiming_line_number = null;
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
  <p>
    <a href={`#/jobs/${invoice.job}`}>&laquo; Back to Job {invoice.job_number}{invoice.job_name ? ` - ${invoice.job_name}` : ''}</a>
  </p>
  {#if invoice.job_description}
    <p>{invoice.job_description}</p>
  {/if}
  <p>Draft {invoice.invoice_number} · {lineItems.length} line items</p>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
    <div>
      <h3>Tasks and Materials</h3>
      <WizardSourcePool {sourcePool} bind:selectedAtoms />
    </div>
    <div>
      <h3>Line items</h3>
      {#each lineItems as lineItem}
        <WizardLineItemCard
          {lineItem}
          apiBase={`/api/invoices/${invoice.invoice_id}`}
          {canAddHere}
          onAddHere={addAtomsToLineItem}
          onchange={reloadLineItems}
        />
      {/each}
      <div style="border: 1px dashed #aaa; padding: 8px; margin-bottom: 8px; color: #777;">
        <em>New line item</em>
        <button
          onclick={createNewLineItem}
          disabled={!canAddHere}
          style="float: right;"
          title={canAddHere ? 'Create a new line item from selected atoms' : 'Select atoms first'}
        >Add Here</button>
      </div>
      <button type="button" onclick={addManualLineItem}>+ Manual</button>
    </div>
  </div>

  <WizardActions
    apiBase={`/api/invoices/${invoice.invoice_id}`}
    detailRoute={`/invoices/${invoice.invoice_id}`}
    discardConfirm="Delete this draft invoice and release all atoms?"
  />
{/if}
