<script>
  // Post-picker form for adding a change-order line (action 'add') — the CO
  // parallel of EstimateAddLineForm. The PriceListPicker's choice decides the
  // payload: service → line-items-from-service (deferred Task descriptor),
  // inventory → line-items with inventory_item (from-pli path), freeform →
  // manual line with AC + is_material marker.
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';

  let {
    open = false,
    choice = null,
    coId,
    categories = [],
    defaultMaterialCategoryId = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let qty = $state('1');
  let description = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  const isFreeform = $derived(choice?.type === 'freeform');
  const title = $derived(
    choice?.type === 'service' ? `Add: ${choice.serviceItem.template_name}` :
    choice?.type === 'inventory' ? `Add: ${choice.inventoryItem.code}` :
    'Add line'
  );
  // The base object's unit, shown next to qty for reference (service/inventory
  // picks carry a fixed unit; freeform has its own editable Units select).
  const baseUnits = $derived(
    choice?.type === 'service' ? (choice.serviceItem?.rate_scheme_detail?.unit_label || '') :
    choice?.type === 'inventory' ? (choice.inventoryItem?.units || '') :
    ''
  );

  $effect(() => {
    if (!open || !choice) return;
    qty = '1'; units = 'none'; price = ''; error = '';
    description = choice.type === 'freeform' ? (choice.typed || '') : '';
    // Freeform material prefills the AC from the config default (overridable);
    // everything else starts blank. Keep as the raw number so Svelte 5's
    // strict-=== option-matching in the select finds the correct option.
    accountingCategory = (choice.type === 'freeform' && choice.isMaterial && defaultMaterialCategoryId != null)
      ? defaultMaterialCategoryId : '';
  });

  async function save() {
    let url = `/api/change-orders/${coId}/line-items/`;
    let payload;
    if (choice.type === 'service') {
      url = `/api/change-orders/${coId}/line-items-from-service/`;
      payload = { service_item: choice.serviceItem.template_id, qty };
    } else if (choice.type === 'inventory') {
      payload = { action: 'add', inventory_item: choice.inventoryItem.inventory_item_id, qty };
    } else {
      // Plain (non-material) hand lines require an AC before send — the document
      // transit needs it; materials default it server-side.
      if (!accountingCategory && !choice.isMaterial) { error = 'Accounting Category is required.'; return; }
      payload = {
        action: 'add',
        description,
        qty: qty || '0',
        units,
        price: price || '0',
        accounting_category: accountingCategory ? Number(accountingCategory) : null,
        is_material: choice.isMaterial,
      };
    }
    busy = true; error = '';
    try {
      await api.post(url, payload);
      onSaved();
    } catch (e) {
      error = e.message || 'Could not add line.';
    } finally { busy = false; }
  }
</script>

<Modal open={open && choice} onCancel={onClose}>
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
      <h3>{title}</h3>
      {#if isFreeform}
        <p><label>Description<br><input type="text" bind:value={description} style="width:100%;box-sizing:border-box;"></label></p>
      {/if}
      <p><label>Quantity<br><input type="number" step="0.01" min="0" value={qty} oninput={(e) => qty = e.target.value}>{#if !isFreeform && baseUnits}<span class="qty-units">{baseUnits}</span>{/if}</label></p>
      {#if isFreeform}
        <p><label>Units<br><UnitsSelect bind:value={units} /></label></p>
        <p><label>Price<br><input type="number" step="0.01" value={price} oninput={(e) => price = e.target.value}></label></p>
        <p><label>Accounting Category
          <br><select bind:value={accountingCategory}>
            <option value="">-- Select --</option>
            {#each categories as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
          </select></label></p>
      {/if}
      <div class="buttons">
        <button type="submit" disabled={busy}>Add</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</form>
</Modal>


<style>
  .qty-units { margin-left: 8px; color: #666; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
