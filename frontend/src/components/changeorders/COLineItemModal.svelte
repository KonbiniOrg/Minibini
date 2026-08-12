<!-- Gesture-driven Change Order line item modal (CO amend-in-place, Task 8).
     No action/target selects — the calling gesture (COEditView) presets
     everything via props. Three variants:
       - 'edit-fields'    description/qty/units/price; PATCHes an existing
                           CO line (lineItemId set). AC only when
                           needsAccountingCategory (editing an 'add' line).
       - 'replace-prefill' same fields as edit-fields, prefilled from the
                           agreement line being replaced; POSTs
                           {action:'replace', target_line_item, ...}
                           (lineItemId unset, targetLineItem set).
       - 'adjustment'      description + percent only — the server computes
                           price against the amended-agreement basis
                           (ChangeOrderService.recompute_adjustment_replaces).
                           POSTs (create, targetLineItem set) or PATCHes
                           (edit, lineItemId set) adjustment_percent, then
                           shows the computed amount as a readback before
                           closing (explicit "Done", never auto-closed).
     create vs edit is derived from lineItemId (PATCH target) being set —
     never a separate mode prop, matching "gestures preset everything". -->
<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    variant = 'edit-fields',   // 'edit-fields' | 'replace-prefill' | 'adjustment'
    coId = null,
    lineItemId = null,         // set => PATCH this CO line (Edit gestures)
    targetLineItem = null,     // set => POST a replace against this estimate line (Replace… gestures)
    needsAccountingCategory = false,  // edit-fields on an 'add' line
    initialDescription = '',
    initialQty = '',
    initialUnits = 'none',
    initialPrice = '',
    initialPercent = '',
    initialAccountingCategory = '',
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let percent = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});
  // Adjustment readback: the computed price the server returns after a
  // save — shown before the modal closes, via an explicit "Done" (never
  // auto-closed — saves stay explicit).
  let savedAmount = $state(null);

  let isEdit = $derived(lineItemId != null);
  let title = $derived.by(() => {
    if (variant === 'adjustment') return isEdit ? 'Edit Replacement Percentage' : 'Replace Adjustment';
    if (variant === 'replace-prefill') return 'Replace Line';
    return 'Edit Line';
  });

  $effect(() => {
    if (open) {
      description = initialDescription ?? '';
      qty = initialQty ?? '';
      units = initialUnits ?? 'none';
      price = initialPrice ?? '';
      percent = initialPercent ?? '';
      // Raw value so Svelte 5's strict-=== select matching finds the option.
      accountingCategory = initialAccountingCategory ?? '';
      formError = '';
      fieldErrs = {};
      savedAmount = null;
    }
  });

  async function save() {
    busy = true;
    formError = '';
    fieldErrs = {};
    const payload = { description };
    if (variant === 'adjustment') {
      if (percent !== '' && percent !== null && percent !== undefined) {
        payload.adjustment_percent = percent;
      }
    } else {
      payload.qty = qty || '0';
      payload.units = units;
      payload.price = price || '0';
      if (needsAccountingCategory) {
        if (!accountingCategory) {
          fieldErrs = { accounting_category: ['Accounting Category is required.'] };
          busy = false;
          return;
        }
        payload.accounting_category = Number(accountingCategory);
      }
    }
    if (!isEdit) {
      payload.action = 'replace';
      payload.target_line_item = targetLineItem;
    }
    try {
      let resp;
      if (isEdit) {
        resp = await api.patch(`/api/change-orders/${coId}/line-items/${lineItemId}/`, payload);
      } else {
        resp = await api.post(`/api/change-orders/${coId}/line-items/`, payload);
      }
      if (variant === 'adjustment') {
        // Show the amended-basis computed amount before closing.
        savedAmount = resp?.price ?? null;
      } else {
        onSaved();
      }
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

  function finishAdjustment() {
    savedAmount = null;
    onSaved();
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="620px">
{#if variant === 'adjustment' && savedAmount !== null}
  <h3>{title}</h3>
  <p>This line now computes to <strong>${Number(savedAmount).toFixed(2)}</strong>.</p>
  <div class="buttons">
    <button type="button" onclick={finishAdjustment}>Done</button>
  </div>
{:else}
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
      <h3>{title}</h3>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
        <FieldError errors={fieldErrs} field="description" />
      </p>

      {#if variant === 'adjustment'}
        <p>
          <label><strong>Percent</strong><br>
            <input type="number" step="0.01" bind:value={percent}>
          </label>
          <FieldError errors={fieldErrs} field="adjustment_percent" />
        </p>
      {:else}
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

        {#if needsAccountingCategory}
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
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
{/if}
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
