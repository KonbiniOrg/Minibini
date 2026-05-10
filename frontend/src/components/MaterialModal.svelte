<script>
  import { api } from '../lib/api.js';
  import PriceListItemPicker from './PriceListItemPicker.svelte';
  import UnitsSelect from './UnitsSelect.svelte';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    material = null,
    taskId = null,
    jobId = null,
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let description = $state('');
  let quantity = $state('');
  let units = $state('none');
  let unitCost = $state('');
  let sellPrice = $state('');
  let pliId = $state(null);
  let pliLocked = $state(false);
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');
  let pliUnitCost = $state(null);    // PLI's current price, for prompt comparison
  let pliSellPrice = $state(null);
  let showPropagatePrompt = $state(false);

  $effect(() => {
    if (open) {
      if (mode === 'edit' && material) {
        description = material.description || '';
        quantity = material.quantity ?? '';
        units = material.units || 'none';
        unitCost = material.unit_cost ?? '';
        sellPrice = material.sell_price ?? '';
        pliId = material.price_list_item || null;
        pliLocked = !!material.price_list_item;
        accountingCategory = material.accounting_category ?? '';
        // For prompt comparison on price edits, we'd ideally fetch the PLI's
        // current prices here. For simplicity, read them off the material
        // (these reflect the PLI's prices at last sync — _populate_from_pli
        // copied them on create). The prompt fires when the user changes the
        // value to differ from these.
        pliUnitCost = pliLocked ? (material.unit_cost ?? null) : null;
        pliSellPrice = pliLocked ? (material.sell_price ?? null) : null;
      } else {
        description = '';
        quantity = '';
        units = 'none';
        unitCost = '';
        sellPrice = '';
        pliId = null;
        pliLocked = false;
        accountingCategory = '';
        pliUnitCost = null;
        pliSellPrice = null;
      }
      error = '';
      showPropagatePrompt = false;
    }
  });

  // Clear stale error when the user touches any form field. Don't read
  // `error` inside this effect — that would track it as a dependency and
  // re-fire the effect (clearing the message) the instant the catch block
  // sets it.
  $effect(() => {
    description; quantity; units; unitCost; sellPrice; pliId; accountingCategory;
    error = '';
  });

  function handlePliSelect(pli) {
    if (pli) {
      pliId = pli.price_list_item_id;
      description = pli.description || '';
      units = pli.units || 'none';
      unitCost = pli.purchase_price ?? '';
      sellPrice = pli.selling_price ?? '';
      pliUnitCost = pli.purchase_price ?? null;
      pliSellPrice = pli.selling_price ?? null;
      if (pli.accounting_category) accountingCategory = pli.accounting_category;
      pliLocked = true;
    } else {
      pliId = null;
      description = '';
      units = 'none';
      unitCost = '';
      sellPrice = '';
      pliUnitCost = null;
      pliSellPrice = null;
      pliLocked = false;
    }
  }

  async function save() {
    // On edit of a PLI-linked material, if any pricing changed vs. the PLI's
    // current value, prompt the user to propagate.
    if (
      mode === 'edit' && pliLocked &&
      pliUnitCost !== null &&
      (Number(unitCost) !== Number(pliUnitCost) || Number(sellPrice) !== Number(pliSellPrice))
    ) {
      showPropagatePrompt = true;
      return;
    }
    await actuallySave(false);
  }

  async function actuallySave(propagate) {
    busy = true;
    error = '';
    showPropagatePrompt = false;

    const fullPayload = {
      description,
      quantity: quantity || '0',
      units,
      unit_cost: unitCost || '0',
      sell_price: sellPrice || '0',
      price_list_item: pliId,
      accounting_category: accountingCategory || null,
    };

    try {
      if (mode === 'edit' && material) {
        // PATCH: send only fields appropriate to the row's PLI state.
        const patch = pliLocked
          ? {
              unit_cost: fullPayload.unit_cost,
              sell_price: fullPayload.sell_price,
              propagate_to_pli: propagate,
            }
          : {
              description,
              units,
              unit_cost: fullPayload.unit_cost,
              sell_price: fullPayload.sell_price,
              accounting_category: fullPayload.accounting_category,
            };
        await api.patch(`/api/materials/${material.material_id}/`, patch);
      } else if (taskId) {
        await api.post(`/api/tasks/${taskId}/materials/`, fullPayload);
      } else {
        await api.post(`/api/jobs/${jobId}/materials/`, fullPayload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || e.data?.detail || 'Could not save material.';
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

      {#if pliLocked}
        <p style="background:#fff7e6;border:1px solid #ffc53d;padding:8px;">
          Linked to a price list item. Delete and re-add as freeform to change description, units, or category.
        </p>
      {/if}

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} disabled={pliLocked} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={quantity} disabled={mode === 'edit'}>
        </label>
        {#if mode === 'edit'}
          <small style="color:#666;">To change quantity, use Restock or Draw more on the row.</small>
        {/if}
      </p>

      <p>
        <label><strong>Units</strong><br>
          <UnitsSelect bind:value={units} disabled={pliLocked} />
        </label>
      </p>

      <p>
        <label><strong>Unit Cost</strong><br>
          <input type="number" step="0.01" bind:value={unitCost}>
        </label>
      </p>

      <p>
        <label><strong>Sell Price</strong><br>
          <input type="number" step="0.01" bind:value={sellPrice}>
        </label>
      </p>

      <p>
        <label><strong>Accounting Category</strong><br>
          <select bind:value={accountingCategory} disabled={pliLocked}>
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

      {#if showPropagatePrompt}
        <div class="propagate-prompt">
          <p><strong>Update PLI with the new values?</strong></p>
          <div class="buttons">
            <button type="button" onclick={() => actuallySave(true)} disabled={busy}>Yes, update PLI</button>
            <button type="button" onclick={() => actuallySave(false)} disabled={busy}>No, just this material</button>
            <button type="button" onclick={() => (showPropagatePrompt = false)} disabled={busy}>Cancel</button>
          </div>
        </div>
      {/if}
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
  .propagate-prompt { margin-top: 12px; padding: 12px; background: #f0f9ff; border: 1px solid #91d5ff; }
</style>
