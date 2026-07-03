<!-- frontend/src/components/estimates/AddServiceItemModal.svelte -->
<!--
  Add an estimate line backed by a Service (ServiceItem / task template). Picking a
  ServiceItem mints a deferred service line on the estimate (POST line-items-from-service)
  — no Task is created yet. The Task is crystallized only when the estimate is accepted
  (on_accept). Estimate-only: invoices bill actuals, so spawning a fresh Task there makes
  no sense.
-->
<script>
  import { api } from '../../lib/api.js';
  import { modalKeys } from '../../lib/modalKeys.js';

  let {
    open = false,
    jobId,
    estimateId,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let serviceItems = $state([]);
  let selectedId = $state('');
  let estQty = $state('1');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      selectedId = '';
      estQty = '1';
      error = '';
      loadServiceItems();
    }
  });

  async function loadServiceItems() {
    try {
      const resp = await api.get('/api/service-items/?page_size=100');
      serviceItems = resp.results || resp;
    } catch (e) {
      serviceItems = [];
      error = e.message || 'Could not load services.';
    }
  }

  async function save() {
    if (!selectedId) {
      error = 'Select a service.';
      return;
    }
    busy = true;
    error = '';
    try {
      await api.post(`/api/estimates/${estimateId}/line-items-from-service/`, {
        service_item: Number(selectedId),
        qty: String(estQty || 1),
      });
      onSaved();
    } catch (e) {
      error = e.message || 'Could not add the service.';
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>Add from Service</h3>
      <p>
        <label><strong>Service *</strong><br>
          <select bind:value={selectedId}>
            <option value="">-- Select --</option>
            {#each serviceItems as si (si.template_id)}
              <option value={String(si.template_id)}>{si.template_name}</option>
            {/each}
          </select>
        </label>
      </p>
      <p>
        <label><strong>Estimated quantity</strong><br>
          <input type="number" step="0.01" min="0" bind:value={estQty}>
        </label>
      </p>
      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Add</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: var(--z-modal);
  }
  .modal { background: white; padding: 16px; max-width: 500px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
