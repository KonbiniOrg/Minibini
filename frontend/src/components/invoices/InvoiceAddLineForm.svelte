<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';

  let {
    open = false,
    choice = null,
    invoiceId,
    categories = [],
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
    accountingCategory = '';
  });

  async function save() {
    // Service pick uses the dedicated action; inventory + freeform use the
    // shared line-items/ POST.
    let url = `/api/invoices/${invoiceId}/line-items/`;
    let payload;
    if (choice.type === 'service') {
      url = `/api/invoices/${invoiceId}/line-items-from-service/`;
      payload = { service_item: choice.serviceItem.template_id, qty };
    } else if (choice.type === 'inventory') {
      payload = { inventory_item: choice.inventoryItem.inventory_item_id, qty };
    } else {
      // Freeform requires an AC; invoices have no material hand-line concept
      // (that's estimate-only), so there's no default-AC exemption here.
      if (!accountingCategory) { error = 'Accounting Category is required.'; return; }
      payload = {
        description,
        qty: qty || '0',
        units,
        price: price || '0',
        accounting_category: accountingCategory ? Number(accountingCategory) : null,
      };
    }
    busy = true; error = '';
    try {
      await api.post(url, payload);
      onSaved();
    } catch (e) {
      // Freeform has no FieldError slot of its own for accounting_category
      // (it's a plain <select>) — surface that field's coaching text on the
      // form-level error line instead.
      const t = triageError(e);
      error = (t.fields.accounting_category && t.fields.accounting_category[0])
        || t.message || 'Could not add line.';
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
            {#each categories.filter((c) => !c.is_fallback) as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
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
