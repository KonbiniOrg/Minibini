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
      } else {
        description = '';
        qty = '';
        units = 'none';
        price = '';
        accountingCategory = '';
      }
      formError = '';
      fieldErrs = {};
      deliverableChoiceOpen = false;
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

  // Make Deliverable edit dialog (RM 2026-08-12): when an edited line has a
  // deliverable made from it AND the edit touches what the deliverable
  // mirrors (description/qty/units — never price), Save first asks whether
  // the deliverable should update too. The choice rides the PATCH as
  // ?update_deliverables=true; onSaved receives {deliverablesUpdated} so the
  // estimate surface can refresh the job-context band.
  let deliverableChoiceOpen = $state(false);

  function deliverableRelevantChange() {
    if (mode !== 'edit' || !item) return false;
    if (!(item.linked_deliverables || []).length) return false;
    return description !== (item.description ?? '')
      || Number(qty || 0) !== Number(item.qty || 0)
      || (units || 'none') !== (item.units || 'none');
  }

  async function save({ updateDeliverables = null } = {}) {
    if (updateDeliverables === null && deliverableRelevantChange()) {
      deliverableChoiceOpen = true;
      return;
    }
    deliverableChoiceOpen = false;
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
        // Every hand line requires an AC — choosing the Materials AC is what
        // makes it a material (is_material derives server-side, RM 2026-08-11;
        // the old "Is this a material?" checkbox is retired).
        if (!accountingCategory) {
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
        if (mode === 'edit' && item) {
          const suffix = updateDeliverables ? '?update_deliverables=true' : '';
          await api.patch(`${apiBase}/line-items/${item.line_item_id}/${suffix}`, payload);
        } else {
          await api.post(`${apiBase}/line-items/`, payload);
        }
      }
      onSaved({ deliverablesUpdated: updateDeliverables === true });
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
              {#each categories.filter((c) => !c.is_fallback) as cat}
                <option value={cat.id}>{cat.code} - {cat.name}</option>
              {/each}
            </select>
          </label>
          <FieldError errors={fieldErrs} field="accounting_category" />
        </p>
      {/if}

      {#if deliverableChoiceOpen}
        <div class="deliverable-choice">
          <p>
            A deliverable was made from this line
            ("{((item?.linked_deliverables || [])[0] || {}).description}").
            Update it to match these changes?
          </p>
          <div class="buttons">
            <button type="button" disabled={busy}
              onclick={() => save({ updateDeliverables: true })}>
              Save and update deliverable
            </button>
            <button type="button" disabled={busy}
              onclick={() => save({ updateDeliverables: false })}>
              Save, keep deliverable as is
            </button>
            <button type="button" disabled={busy}
              onclick={() => { deliverableChoiceOpen = false; }}>Back</button>
          </div>
        </div>
      {/if}

      <div class="buttons" hidden={deliverableChoiceOpen}>
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
