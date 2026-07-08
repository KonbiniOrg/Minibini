<script>
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import WizardSourcePool from '../../components/invoices/WizardSourcePool.svelte';
  import AgreementAdjustmentsPanel from '../../components/invoices/AgreementAdjustmentsPanel.svelte';
  import WizardLineItemCard from '../../components/wizards/WizardLineItemCard.svelte';
  import WizardActions from '../../components/wizards/WizardActions.svelte';
  import FormMessage from '../../components/FormMessage.svelte';
  import { showError } from '../../stores/messages.js';
  import { createFlushRegistry } from '../../lib/wizardFlush.js';

  const { params = {} } = $props();

  const flushRegistry = createFlushRegistry();

  let invoice = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let loading = $state(true);
  let error = $state(null);
  // Set when an add bounced off the atoms-claimed 409 — the message under the
  // add controls then offers "Reload wizard" (the conflict's next step).
  let conflictError = $state('');

  const canAddHere = $derived(selectedAtoms.length > 0);

  async function addAtomsToLineItem(lineItemId) {
    conflictError = '';
    try {
      await api.post(
        `/api/invoices/${invoice.invoice_id}/line-items/${lineItemId}/add-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, 'Some atoms were claimed by another invoice.');
      } else {
        showError(errorMessage(e, 'Failed to add atoms.'));
      }
    }
  }

  async function createNewLineItem() {
    conflictError = '';
    try {
      await api.post(
        `/api/invoices/${invoice.invoice_id}/line-items-from-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, 'Some atoms were claimed by another invoice.');
      } else {
        showError(errorMessage(e, 'Failed to create line item.'));
      }
    }
  }

  function reloadFromConflict() {
    conflictError = '';
    loadAll();
  }

  async function addManualLineItem() {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/line-items/`, {
        description: '', qty: '1', units: 'each', price: '0.00',
      });
      await reloadLineItems();
    } catch (e) {
      showError(errorMessage(e, 'Failed to add manual line item.'));
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
      if (inv?.job) {
        // Pre-select the job overview's invoices pillar so discarding the draft
        // (which returns to the job overview) lands on the invoice section.
        try { sessionStorage.setItem(`jobDetailActiveSection_${inv.job}`, 'invoices'); } catch (_) {}
        try {
          job = await api.get(`/api/jobs/${inv.job}/`);
          if (job?.contact) {
            try { contact = await api.get(`/api/contacts/${job.contact}/`); }
            catch (_) { contact = null; }
          }
        } catch (_) { job = null; contact = null; }
      }
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
  async function sendAllAtoms() {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/send-all-atoms/`);
      await loadAll();
    } catch (e) {
      showError(errorMessage(e, 'Could not send all atoms.'));
    }
  }

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
        // Both claimed_by_other (another invoice) and not_billable (task not
        // complete / material not consumed) are properties the backend decides
        // independently of THIS invoice's line items — never reconcile them to
        // 'available', or the wizard would offer un-billable atoms.
        if (atom.state === 'claimed_by_other' || atom.state === 'not_billable') continue;
        const key = `${atom.type}:${atom.id}`;
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
  {#if job}
    <JobHeader {job} {contact} />
  {/if}
  <div class="page-body">
  <div class="toolbar">
    <a href={`/invoices/${invoice.invoice_id}`} use:link class="back-link">&laquo; back to invoice</a>
    <span class="page-title">Billables: {invoice.invoice_number}</span>
  </div>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
    <div>
      <h3>Tasks and Materials</h3>
      <p><button type="button" onclick={sendAllAtoms}
        title="Create one line item per available atom">Send all to Invoice</button></p>
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
          registerFlush={flushRegistry.register}
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
      <FormMessage error={conflictError}>
        <button type="button" onclick={reloadFromConflict}>Reload wizard</button>
      </FormMessage>
      <button type="button" onclick={addManualLineItem}>+ Manual</button>
      <AgreementAdjustmentsPanel invoiceId={invoice.invoice_id} onLineItemAdded={reloadLineItems} />
    </div>
  </div>

  <WizardActions
    apiBase={`/api/invoices/${invoice.invoice_id}`}
    detailRoute={`/invoices/${invoice.invoice_id}`}
    discardRoute={invoice.job ? `/jobs/${invoice.job}` : '/'}
    onDone={flushRegistry.flushAll}
  />
  </div>
{/if}

<style>
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 0; }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }
</style>
