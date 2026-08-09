<script>
  import { api } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import UnitsSelect from './UnitsSelect.svelte';
  import InventoryItemPicker from './InventoryItemPicker.svelte';
  import Modal from './Modal.svelte';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';

  let {
    open = false,
    mode = 'create',          // 'create' | 'edit'
    apiBase = '',             // e.g. '/api/estimates/123' or '/api/invoices/123'
    item = null,              // line item being edited (edit mode)
    categories = [],
    showMaterialMarker = false,        // estimate surface only
    defaultMaterialCategoryId = null,  // AC pk from default_material_accounting_category
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let entryMode = $state('manual'); // 'manual' | 'pli' — catalog only on add
  let selectedPLI = $state(null);

  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let isMaterial = $state(false);
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  $effect(() => {
    if (open) {
      entryMode = 'manual';
      selectedPLI = null;
      if (mode === 'edit' && item) {
        description = item.description || '';
        qty = item.qty ?? '';
        units = item.units || 'none';
        price = item.price ?? '';
        accountingCategory = item.accounting_category ?? '';
        isMaterial = item.is_material ?? false;
      } else {
        description = '';
        qty = '';
        units = 'none';
        price = '';
        accountingCategory = '';
        isMaterial = false;
      }
      formError = '';
      fieldErrs = {};
    }
  });

  function handlePLISelect(pli) {
    selectedPLI = pli;
    if (pli) {
      // Preview only; the server copies authoritative values from the PLI.
      description = pli.description || '';
      units = pli.units || 'none';
      price = pli.selling_price ?? '';
      accountingCategory = pli.accounting_category ?? '';
    }
  }

  function onMaterialToggle(event) {
    // onchange fires before bind:checked updates isMaterial; read the DOM state directly.
    // Keep the value as a number so Svelte's option-value comparison (===) matches cat.id.
    if (event.target.checked && !accountingCategory && defaultMaterialCategoryId != null) {
      accountingCategory = defaultMaterialCategoryId;
    }
  }

  async function save() {
    busy = true;
    formError = '';
    fieldErrs = {};
    try {
      if (mode === 'create' && entryMode === 'pli') {
        if (!selectedPLI) {
          fieldErrs = { inventory_item: ['Select an inventory item.'] };
          busy = false;
          return;
        }
        await api.post(`${apiBase}/line-items/`, {
          inventory_item: selectedPLI.inventory_item_id,
          qty: qty || '1',
        });
      } else {
        const isMaterialLine = showMaterialMarker && isMaterial;
        // Accounting category is required on plain (non-material) hand lines —
        // the document/invoice transit needs it; materials default server-side.
        if (!accountingCategory && !isMaterialLine) {
          fieldErrs = { accounting_category: ['Accounting Category is required.'] };
          busy = false;
          return;
        }
        const payload = {
          description,
          qty: qty || '0',
          units,
          price: price || '0',
          accounting_category: accountingCategory ? Number(accountingCategory) : null,
        };
        if (showMaterialMarker) {
          payload.is_material = isMaterial;
        }
        if (mode === 'edit' && item) {
          await api.patch(`${apiBase}/line-items/${item.line_item_id}/`, payload);
        } else {
          await api.post(`${apiBase}/line-items/`, payload);
        }
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

<Modal {open} onCancel={onClose}>
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
      <h3>{mode === 'edit' ? 'Edit Line Item' : 'Add Line Item'}</h3>

      {#if mode === 'create'}
        <p>
          <label><input type="radio" bind:group={entryMode} value="manual"> Manual</label>
          <label><input type="radio" bind:group={entryMode} value="pli"> From Inventory</label>
        </p>
      {/if}

      {#if mode === 'create' && entryMode === 'pli'}
        <p>
          <label><strong>Inventory Item *</strong></label><br>
          <InventoryItemPicker
            value={selectedPLI?.inventory_item_id}
            selectedItem={selectedPLI}
            onSelect={handlePLISelect}
            params={{ is_active: true }}
          />
          <FieldError errors={fieldErrs} field="inventory_item" />
        </p>
        <p>
          <label><strong>Quantity *</strong><br>
            <input type="number" step="0.01" min="0" bind:value={qty}>
          </label>
          <FieldError errors={fieldErrs} field="qty" />
        </p>
      {:else}
        <p>
          <label><strong>Description *</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
          <FieldError errors={fieldErrs} field="description" />
        </p>
        <p>
          <label><strong>Quantity</strong><br>
            <input type="number" step="0.01" bind:value={qty}>
          </label>
          <FieldError errors={fieldErrs} field="qty" />
        </p>
        <p>
          <label><strong>Units</strong><br>
            <UnitsSelect bind:value={units} />
          </label>
          <FieldError errors={fieldErrs} field="units" />
        </p>
        <p>
          <label><strong>Price</strong><br>
            <input type="number" step="0.01" bind:value={price}>
          </label>
          <FieldError errors={fieldErrs} field="price" />
        </p>
        <p>
          <label><strong>Accounting Category *</strong><br>
            <select bind:value={accountingCategory}>
              <option value="">-- Select --</option>
              {#each categories as cat}
                <option value={cat.id}>{cat.code} - {cat.name}</option>
              {/each}
            </select>
          </label>
          <FieldError errors={fieldErrs} field="accounting_category" />
        </p>
        {#if showMaterialMarker}
          <p>
            <label>
              <input type="checkbox" bind:checked={isMaterial} onchange={onMaterialToggle}>
              Is this a material?
            </label>
            <FieldError errors={fieldErrs} field="is_material" />
          </p>
        {/if}
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
