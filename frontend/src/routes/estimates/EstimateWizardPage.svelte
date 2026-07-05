<script>
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import WizardSourcePool from '../../components/estimates/WizardSourcePool.svelte';
  import WizardLineItemCard from '../../components/wizards/WizardLineItemCard.svelte';
  import WizardActions from '../../components/wizards/WizardActions.svelte';
  import FormMessage from '../../components/FormMessage.svelte';
  import { showError } from '../../stores/messages.js';
  import { createFlushRegistry } from '../../lib/wizardFlush.js';

  const { params = {} } = $props();

  const flushRegistry = createFlushRegistry();

  let estimate = $state(null);
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
        `/api/estimates/${estimate.estimate_id}/line-items/${lineItemId}/add-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadAfterAction();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, 'Some atoms were claimed by another estimate.');
      } else {
        showError(errorMessage(e, 'Failed to add atoms.'));
      }
    }
  }

  async function createNewLineItem() {
    conflictError = '';
    try {
      await api.post(
        `/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`,
        {atoms: selectedAtoms},
      );
      await reloadAfterAction();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, 'Some atoms were claimed by another estimate.');
      } else {
        showError(errorMessage(e, 'Failed to create line item.'));
      }
    }
  }

  function reloadFromConflict() {
    conflictError = '';
    loadAll();
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
      if (est?.job) {
        // Pre-select the job overview's estimate pillar so discarding the draft
        // (which returns to the job overview) lands on the estimate section.
        try { sessionStorage.setItem(`jobDetailActiveSection_${est.job}`, 'estimate'); } catch (_) {}
        try {
          job = await api.get(`/api/jobs/${est.job}/`);
          if (job?.contact) {
            try { contact = await api.get(`/api/contacts/${job.contact}/`); }
            catch (_) { contact = null; }
          }
        } catch (_) { job = null; contact = null; }
      }
      lineItems = items.results || items;
      sourcePool = pool;
      reconcileAtomStates();
    } catch (e) {
      error = e.message || 'Failed to load wizard';
    } finally {
      loading = false;
    }
  }

  // Post-action refresh — fetches estimate and line items, then updates
  // atom states in the existing source pool. Does NOT re-fetch the pool.
  async function sendAllAtoms() {
    try {
      await api.post(`/api/estimates/${estimate.estimate_id}/send-all-atoms/`);
      await reloadAfterAction();
    } catch (e) {
      showError(errorMessage(e, 'Could not send all atoms.'));
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

  // Walk the flat source pool atoms and update state from current line items.
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
        if (a.state === 'claimed_by_other') return a;
        const key = `${a.type}:${a.id}`;
        if (claimMap.has(key)) {
          return {
            ...a,
            state: 'claimed_by_current',
            claiming_line_item_id: claimMap.get(key).line_item_id,
          };
        }
        if (a.state === 'claimed_by_current') {
          // Was claimed by current but no longer in claim map → release to available
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
  {#if job}
    <JobHeader {job} {contact} />
  {/if}
  <div class="toolbar">
    <a href={`/estimates/${estimate.estimate_id}`} use:link class="back-link">&laquo; back to Estimate</a>
    <span class="page-title">Tasks &amp; Materials: {estimate.estimate_number}</span>
  </div>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
    <div>
      <h3>Source pool (job atoms)</h3>
      <p><button type="button" onclick={sendAllAtoms}
        title="Create one line item per available atom">Send all to Estimate</button></p>
      <WizardSourcePool {sourcePool} bind:selectedAtoms />
    </div>
    <div>
      <h3>Line items</h3>
      {#each lineItems as li (li.line_item_id)}
        <WizardLineItemCard
          lineItem={li}
          apiBase={`/api/estimates/${estimate.estimate_id}`}
          {canAddHere}
          onAddHere={addAtomsToLineItem}
          onchange={reloadAfterAction}
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
    </div>
  </div>

  <WizardActions
    apiBase={`/api/estimates/${estimate.estimate_id}`}
    detailRoute={`/estimates/${estimate.estimate_id}`}
    discardRoute={estimate.job ? `/jobs/${estimate.job}` : '/'}
    onDone={flushRegistry.flushAll}
  />
{/if}

<style>
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 24px; }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }
</style>
