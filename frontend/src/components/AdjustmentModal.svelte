<script>
  import { api } from '../lib/api.js';
  import Modal from './Modal.svelte';

  let {
    open = false,
    apiBase = '',          // e.g. '/api/estimates/7' or '/api/invoices/3'
    categories = [],       // accounting categories for target selection
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let services = $state([]);         // percentage services fetched on open
  let selectedServiceId = $state('');
  let targetCategoryIds = $state([]); // empty = all categories
  let busy = $state(false);
  let error = $state('');

  // Fetch percentage-algorithm services whenever the modal opens
  $effect(() => {
    if (open) {
      selectedServiceId = '';
      targetCategoryIds = [];
      error = '';
      loadServices();
    }
  });

  async function loadServices() {
    try {
      const resp = await api.get('/api/rate-schemes/?page_size=100');
      const all = resp.results || resp;
      services = all.filter(s => s.algorithm === 'percentage');
    } catch (_) {
      services = [];
    }
  }

  function toggleCategory(id) {
    if (targetCategoryIds.includes(id)) {
      targetCategoryIds = targetCategoryIds.filter(c => c !== id);
    } else {
      targetCategoryIds = [...targetCategoryIds, id];
    }
  }

  async function submit() {
    if (!selectedServiceId) {
      error = 'Please choose a rate before adding.';
      return;
    }
    busy = true;
    error = '';
    try {
      await api.post(`${apiBase}/adjustment-lines/`, {
        adjustment_service: Number(selectedServiceId),
        target_category_ids: targetCategoryIds,
      });
      onSaved();
    } catch (e) {
      error = e.message || 'Could not add adjustment.';
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} label="Add Adjustment" maxWidth="720px">
      <h3>Add Percentage Adjustment</h3>

      <p>
        <select
          id="adj-service"
          aria-label="Percentage rate scheme"
          bind:value={selectedServiceId}
        >
          <option value="">-- Select a rate --</option>
          {#each services as svc}
            <option value={svc.rate_scheme_id}>
              {svc.name} ({svc.rate}%)
            </option>
          {/each}
        </select>
      </p>

      <p><strong>Target Categories</strong> <em>(leave all unchecked to apply to all)</em></p>
      <div class="category-list">
        {#each categories as cat}
          <label class="cat-label">
            <input
              type="checkbox"
              value={cat.id}
              checked={targetCategoryIds.includes(cat.id)}
              onchange={() => toggleCategory(cat.id)}
            >
            {cat.code} - {cat.name}
          </label>
        {/each}
        {#if categories.length === 0}
          <em>No categories available.</em>
        {/if}
      </div>

      <div class="buttons">
        <button type="button" onclick={submit} disabled={busy}>Add Adjustment</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</Modal>


<style>
  .category-list {
    display: flex; flex-direction: column; gap: 4px;
    max-height: 180px; overflow-y: auto;
    border: 1px solid #e5e7eb; border-radius: 3px; padding: 8px;
    margin-bottom: 12px;
  }
  .cat-label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; margin-top: 8px; }
</style>
