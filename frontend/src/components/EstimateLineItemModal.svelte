<script>
  import { api } from '../lib/api.js';
  import UnitsSelect from './UnitsSelect.svelte';

  let {
    open = false,
    mode = 'create',
    estimateId = null,
    item = null,
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && item) {
        description = item.description || '';
        qty = item.qty ?? '';
        units = item.units || 'none';
        price = item.price ?? '';
        accountingCategory = item.accounting_category ?? '';
      } else {
        description = '';
        qty = '';
        units = 'none';
        price = '';
        accountingCategory = '';
      }
      error = '';
    }
  });

  async function save() {
    busy = true;
    error = '';
    const payload = {
      description,
      qty: qty || '0',
      units,
      price: price || '0',
      accounting_category: accountingCategory || null,
    };
    try {
      if (mode === 'edit' && item) {
        await api.patch(
          `/api/estimates/${estimateId}/line-items/${item.line_item_id}/`,
          payload,
        );
      } else {
        await api.post(`/api/estimates/${estimateId}/line-items/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save line item.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit Line Item' : 'Add Line Item'}</h3>

      <p>
        <label><strong>Description *</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={qty}>
        </label>
      </p>

      <p>
        <label><strong>Units</strong><br>
          <UnitsSelect bind:value={units} />
        </label>
      </p>

      <p>
        <label><strong>Price</strong><br>
          <input type="number" step="0.01" bind:value={price}>
        </label>
      </p>

      <p>
        <label><strong>Line Item Type</strong><br>
          <select bind:value={accountingCategory}>
            <option value="">-- None --</option>
            {#each categories as cat}
              <option value={cat.id}>{cat.code} - {cat.name}</option>
            {/each}
          </select>
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
