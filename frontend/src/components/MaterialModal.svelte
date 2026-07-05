<script>
  import { api } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import InventoryItemPicker from './InventoryItemPicker.svelte';
  import UnitsSelect from './UnitsSelect.svelte';
  import Modal from './Modal.svelte';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    material = null,
    taskId = null,
    jobId = null,
    categories = [],
    presetDescription = '',
    presetPli = null,
    defaultMaterialCategoryId = null,
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
  let formError = $state('');
  let fieldErrs = $state({});
  let pliUnitCost = $state(null);    // PLI's current price, for prompt comparison
  let pliSellPrice = $state(null);
  let showPropagatePrompt = $state(false);
  // Allocation-time stock visibility for a selected catalog/lot item.
  let pliOnHand = $state(null);
  let pliEarmarked = $state(null);
  let pliAvailable = $state(null);

  // Warn when the picked item is partly/fully spoken for, or the requested
  // quantity exceeds what's actually available (the rest is earmarked elsewhere).
  let earmarkWarning = $derived.by(() => {
    if (pliId == null || pliAvailable == null) return '';
    const avail = Number(pliAvailable);
    const earmarked = Number(pliEarmarked ?? 0);
    const want = Number(quantity || 0);
    if (want > avail) {
      return `Only ${pliAvailable} of ${pliOnHand} ${units} available — `
        + `${pliEarmarked} already earmarked for other jobs. `
        + `You can still commit it (it will show a shortfall until restocked).`;
    }
    if (earmarked > 0) {
      return `${pliOnHand} ${units} on hand, ${pliEarmarked} earmarked for other `
        + `jobs (${pliAvailable} available).`;
    }
    return '';
  });

  $effect(() => {
    if (open) {
      if (mode === 'edit' && material) {
        description = material.description || '';
        quantity = material.quantity ?? '';
        units = material.units || 'none';
        unitCost = material.unit_cost ?? '';
        sellPrice = material.sell_price ?? '';
        pliId = material.inventory_item || null;
        pliLocked = !!material.inventory_item;
        accountingCategory = material.accounting_category ?? '';
        // For prompt comparison on price edits, we'd ideally fetch the PLI's
        // current prices here. For simplicity, read them off the material
        // (these reflect the PLI's prices at last sync — _populate_from_pli
        // copied them on create). The prompt fires when the user changes the
        // value to differ from these.
        pliUnitCost = pliLocked ? (material.unit_cost ?? null) : null;
        pliSellPrice = pliLocked ? (material.sell_price ?? null) : null;
      } else {
        // Reset shared fields first
        quantity = '';
        units = 'none';
        unitCost = '';
        sellPrice = '';
        pliUnitCost = null;
        pliSellPrice = null;
        if (presetPli) {
          // PLI preset: auto-select the item (sets description, units, prices, AC, pliLocked)
          pliId = null;
          pliLocked = false;
          description = '';
          accountingCategory = '';
          handlePliSelect(presetPli);
        } else {
          description = (mode === 'create' && !material) ? (presetDescription || '') : '';
          pliId = null;
          pliLocked = false;
          accountingCategory = defaultMaterialCategoryId ?? '';
        }
      }
      formError = '';
      fieldErrs = {};
      showPropagatePrompt = false;
    }
  });

  // Clear stale errors when the user touches any form field. Don't read
  // `formError`/`fieldErrs` inside this effect — that would track them as
  // dependencies and re-fire the effect (clearing the message) the instant
  // the catch block sets them.
  $effect(() => {
    description; quantity; units; unitCost; sellPrice; pliId; accountingCategory;
    formError = '';
    fieldErrs = {};
  });

  function handlePliSelect(pli) {
    if (pli) {
      pliId = pli.inventory_item_id;
      description = pli.description || '';
      units = pli.units || 'none';
      unitCost = pli.purchase_price ?? '';
      sellPrice = pli.selling_price ?? '';
      pliUnitCost = pli.purchase_price ?? null;
      pliSellPrice = pli.selling_price ?? null;
      if (pli.accounting_category) accountingCategory = pli.accounting_category;
      pliLocked = true;
      pliOnHand = pli.qty_on_hand ?? null;
      pliEarmarked = pli.qty_earmarked ?? null;
      pliAvailable = pli.qty_available ?? null;
    } else {
      pliId = null;
      description = '';
      units = 'none';
      unitCost = '';
      sellPrice = '';
      pliUnitCost = null;
      pliSellPrice = null;
      pliLocked = false;
      pliOnHand = null;
      pliEarmarked = null;
      pliAvailable = null;
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
    formError = '';
    fieldErrs = {};
    showPropagatePrompt = false;

    const fullPayload = {
      description,
      quantity: quantity || '0',
      units,
      unit_cost: unitCost || '0',
      sell_price: sellPrice || '0',
      inventory_item: pliId,
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
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open}
  onCancel={() => { if (showPropagatePrompt) showPropagatePrompt = false; else onClose(); }}>
<form onsubmit={(e) => { e.preventDefault(); if (!busy && !showPropagatePrompt) save(); }}>
      <h3>{mode === 'edit' ? 'Edit Material' : 'Add Material'}</h3>

      <p>
        <label><strong>Inventory Item</strong><br>
          <InventoryItemPicker value={pliId} onSelect={handlePliSelect} disabled={false} params={{ is_active: true }} />
        </label>
        <FieldError errors={fieldErrs} field="inventory_item" />
      </p>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} disabled={pliLocked} style="width:100%;box-sizing:border-box;">
        </label>
        <FieldError errors={fieldErrs} field="description" />
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={quantity} disabled={mode === 'edit'}>
        </label>
        <FieldError errors={fieldErrs} field="quantity" />
        {#if mode === 'edit'}
          <small style="color:#666;">To change quantity, use Restock or Draw more on the row.</small>
        {/if}
        {#if earmarkWarning}
          <p class="earmark-warning">{earmarkWarning}</p>
        {/if}
      </p>

      <p>
        <label><strong>Units</strong><br>
          <UnitsSelect bind:value={units} disabled={pliLocked} />
        </label>
        <FieldError errors={fieldErrs} field="units" />
      </p>

      <p>
        <label><strong>Unit Cost</strong><br>
          <input type="number" step="0.01" bind:value={unitCost} disabled={!pliLocked}>
        </label>
        <FieldError errors={fieldErrs} field="unit_cost" />
        {#if !pliLocked}
          <br><small><em>A freeform material's cost comes from a linked expense or PO, not manual entry.</em></small>
        {/if}
      </p>

      <p>
        <label><strong>Sell Price</strong><br>
          <input type="number" step="0.01" bind:value={sellPrice}>
        </label>
        <FieldError errors={fieldErrs} field="sell_price" />
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
        <FieldError errors={fieldErrs} field="accounting_category" />
      </p>

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />

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
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .earmark-warning { margin: 6px 0 0; padding: 6px 8px; background: #fffbe6; border: 1px solid #ffe58f; font-size: 0.9em; }
  .propagate-prompt { margin-top: 12px; padding: 12px; background: #f0f9ff; border: 1px solid #91d5ff; }
</style>
