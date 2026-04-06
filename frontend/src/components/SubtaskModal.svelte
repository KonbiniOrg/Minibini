<script>
  import { api } from '../lib/api.js';
  import UnitsSelect from './UnitsSelect.svelte';

  let {
    open = false,
    parentTaskId = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let name = $state('');
  let description = $state('');
  let units = $state('none');
  let rate = $state('');
  let estQty = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      name = '';
      description = '';
      units = 'none';
      rate = '';
      estQty = '';
      error = '';
    }
  });

  async function save() {
    busy = true;
    error = '';
    try {
      await api.post(`/api/tasks/${parentTaskId}/subtasks/`, {
        name,
        description,
        units,
        rate: rate || null,
        est_qty: estQty || null,
      });
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not create subtask.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>Add Subtask</h3>

      <p>
        <label><strong>Name *</strong><br>
          <input type="text" bind:value={name} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Units</strong><br>
          <UnitsSelect bind:value={units} />
        </label>
      </p>

      <p>
        <label><strong>Rate</strong><br>
          <input type="number" step="0.01" bind:value={rate}>
        </label>
      </p>

      <p>
        <label><strong>Estimated Quantity</strong><br>
          <input type="number" step="0.01" bind:value={estQty}>
        </label>
      </p>

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
