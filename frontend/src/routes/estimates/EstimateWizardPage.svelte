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

  // Post-action refresh — fetches estimate and line items, then updates
  // atom states in the existing source pool. Does NOT re-fetch the pool.
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
  // NOTE: EstimateLineItemSerializer does not include nested `sources`, so
  // claimMap will always be empty until that serializer is extended.
  // Atoms claimed by this estimate will remain shown as available after
  // actions until the serializer is updated. See Task 5 concern.
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
