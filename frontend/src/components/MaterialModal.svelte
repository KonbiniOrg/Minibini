<script>
  import { api } from '../lib/api.js';
  import PriceListItemPicker from './PriceListItemPicker.svelte';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    material = null,
    taskId = null,
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let description = $state('');
  let quantity = $state('');
  let unitCost = $state('');
  let sellPrice = $state('');
  let pliId = $state(null);
  let pliLocked = $state(false);
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && material) {
        description = material.description || '';
        quantity = material.quantity ?? '';
        unitCost = material.unit_cost ?? '';
        sellPrice = material.sell_price ?? '';
        pliId = material.price_list_item || null;
        pliLocked = !!material.price_list_item;
        accountingCategory = material.accounting_category ?? '';
      } else {
        description = '';
        quantity = '';
        unitCost = '';
        sellPrice = '';
        pliId = null;
        pliLocked = false;
        accountingCategory = '';
      }
      error = '';
    }
  });

  function handlePliSelect(pli) {
    if (pli) {
      pliId = pli.price_list_item_id;
      description = pli.description || '';
      unitCost = pli.purchase_price ?? '';
      sellPrice = pli.selling_price ?? '';
      if (pli.accounting_category) accountingCategory = pli.accounting_category;
      pliLocked = true;
    } else {
      pliId = null;
      description = '';
      unitCost = '';
      sellPrice = '';
      pliLocked = false;
    }
  }

  async function save() {
    busy = true;
    error = '';
    const payload = {
      description,
      quantity: quantity || '0',
      unit_cost: unitCost || '0',
      sell_price: sellPrice || '0',
      price_list_item: pliId,
      accounting_category: accountingCategory || null,
    };
    try {
      if (mode === 'edit' && material) {
        await api.patch(`/api/tasks/${taskId}/materials/${material.material_id}/`, payload);
      } else {
        await api.post(`/api/tasks/${taskId}/materials/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save material.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit Material' : 'Add Material'}</h3>

      <p>
        <label><strong>Price List Item</strong><br>
          <PriceListItemPicker value={pliId} onSelect={handlePliSelect} disabled={false} />
        </label>
      </p>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} disabled={pliLocked} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={quantity}>
        </label>
      </p>

      <p>
        <label><strong>Unit Cost</strong><br>
          <input type="number" step="0.01" bind:value={unitCost} disabled={pliLocked}>
        </label>
      </p>

      <p>
        <label><strong>Sell Price</strong><br>
          <input type="number" step="0.01" bind:value={sellPrice} disabled={pliLocked}>
        </label>
      </p>

      <p>
        <label><strong>Accounting Category</strong><br>
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
