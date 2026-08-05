<script>
  // Post-picker form for adding an estimate line item. The PriceListPicker's
  // choice decides the payload:
  //   service    → line-items-from-service (deferred ServiceItem descriptor)
  //   inventory  → line-items with inventory_item (from-catalog path)
  //   freeform   → a bare hand-line, kind-driven (choice.kind: 'work' |
  //                'material' | 'fee'). freeform_kind is sent directly on
  //                every freeform add — the retired is_material alias is
  //                never sent from this form (task-owned-money Phase 2 Task 7).
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    choice = null,
    estimateId,
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
  let formError = $state('');
  let fieldErrs = $state({});

  // Work-kind preset dropdown: the same task-applicable rate-scheme list +
  // configured default as WorkItemForm's manual-mode create dropdown. Picking
  // a preset here only STAMPS its rate/unit/AC into these editable local
  // fields — no scheme id is ever sent; the submitted line is plain
  // description/qty/units/price/accounting_category + freeform_kind:'work'.
  let schemes = $state([]);
  let defaultSchemeId = $state('');
  let rateSchemeId = $state('');
  let lastFilledSchemeId = $state('');
  // Guards the default-preset preselect effect below to fire at most once per
  // open/choice cycle — schemes/defaultSchemeId resolve asynchronously
  // (onMount), so without this guard every later resolution would rerun the
  // effect. Since that effect ONLY touches rateSchemeId, guarding it (rather
  // than folding the preselect into the general reset effect) keeps the
  // async fetch timing from ever clobbering fields the user already typed
  // into — qty/description/price/etc. reset only on an actual open/choice
  // change, never on a schemes/settings fetch resolving mid-edit.
  let presetApplied = $state(false);

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/?task_applicable=true');
      schemes = resp.results || resp;
      // The shop's configured default preset, read off the `is_default`
      // flag on this (already IsAuthenticated-only) list rather than
      // /api/settings/ (CanManageConfig-gated — a permissionless worker's
      // fetch there 403s silently, so the dropdown never preselected; RM
      // browser-testing note 3).
      const defaultRow = schemes.find((s) => s.is_default);
      defaultSchemeId = defaultRow ? defaultRow.rate_scheme_id : '';
    } catch (e) {
      // Best-effort: a failed scheme fetch shouldn't block manual entry —
      // the preset dropdown just renders empty.
    }
  });

  const isFreeform = $derived(choice?.type === 'freeform');
  const kind = $derived(isFreeform ? choice.kind : null);
  const isWork = $derived(kind === 'work');
  const isMaterial = $derived(kind === 'material');
  const isFee = $derived(kind === 'fee');
  const isFeeCredit = $derived(isFee && price !== '' && !Number.isNaN(Number(price)) && Number(price) < 0);

  const title = $derived(
    choice?.type === 'service' ? `Add: ${choice.serviceItem.template_name}` :
    choice?.type === 'inventory' ? `Add: ${choice.inventoryItem.code}` :
    isWork ? 'Add Work' :
    isMaterial ? 'Add Material' :
    isFee ? 'Add Fee / Credit' :
    'Add line'
  );
  // The base object's unit, shown next to qty for reference (service/inventory
  // picks carry a fixed unit; freeform has its own editable Units select).
  const baseUnits = $derived(
    choice?.type === 'service' ? (choice.serviceItem?.rate_scheme_detail?.unit_label || '') :
    choice?.type === 'inventory' ? (choice.inventoryItem?.units || '') :
    ''
  );

  const selectedScheme = $derived(
    schemes.find((s) => s.rate_scheme_id === Number(rateSchemeId)) || null
  );

  // Reset on an actual open/choice change ONLY — deliberately does not read
  // schemes/defaultSchemeId (see presetApplied above) so the async
  // rate-scheme fetch resolving mid-edit can never wipe user input.
  $effect(() => {
    if (!open || !choice) return;
    qty = '1'; units = 'none'; price = ''; formError = ''; fieldErrs = {};
    description = choice.type === 'freeform' ? (choice.typed || '') : '';
    // Freeform material prefills the AC from the config default (overridable); everything
    // else starts blank. Keep as the raw number so Svelte 5's strict-=== option-matching
    // in the select finds the correct option (String(id) !== id numerically).
    accountingCategory = (choice.type === 'freeform' && choice.kind === 'material' && defaultMaterialCategoryId != null)
      ? defaultMaterialCategoryId : '';
    rateSchemeId = '';
    lastFilledSchemeId = '';
    presetApplied = false;
  });

  // Once the rate-scheme list AND the configured default have both loaded,
  // preselect the default — but only when it's actually offered in the list
  // (task_applicable already excludes percentage/retired schemes; a default
  // naming a retired one would also fail this check). Fires at most once per
  // open/choice cycle (presetApplied), and only for kind='work'.
  $effect(() => {
    if (!open || !choice || choice.type !== 'freeform' || choice.kind !== 'work') return;
    if (presetApplied || !defaultSchemeId || schemes.length === 0) return;
    presetApplied = true;
    const defaultInList = schemes.some((s) => String(s.rate_scheme_id) === String(defaultSchemeId));
    if (defaultInList) rateSchemeId = Number(defaultSchemeId);
  });

  // Picking (or the effect above preselecting) a preset stamps its rate/unit/AC
  // into the editable fields. The user is free to edit any field afterward;
  // switching to a different preset re-stamps and overwrites again.
  $effect(() => {
    if (!isWork || !selectedScheme) return;
    if (rateSchemeId === lastFilledSchemeId) return;
    lastFilledSchemeId = rateSchemeId;
    units = selectedScheme.unit_label || 'none';
    price = selectedScheme.rate != null ? String(selectedScheme.rate) : '';
    accountingCategory = selectedScheme.accounting_category ?? '';
  });

  async function save() {
    formError = ''; fieldErrs = {};
    let url = `/api/estimates/${estimateId}/line-items/`;
    let payload;
    if (choice.type === 'service') {
      url = `/api/estimates/${estimateId}/line-items-from-service/`;
      payload = { service_item: choice.serviceItem.template_id, qty };
    } else if (choice.type === 'inventory') {
      payload = { inventory_item: choice.inventoryItem.inventory_item_id, qty };
    } else {
      // AC is required for fee and work kinds; material defaults it server-side.
      if (!accountingCategory && !isMaterial) {
        fieldErrs = { accounting_category: ['Accounting Category is required.'] };
        return;
      }
      const priceNum = price === '' ? NaN : Number(price);
      if (!Number.isNaN(priceNum) && priceNum < 0 && !isFee) {
        fieldErrs = { price: ['Negative price is only allowed on a Fee/Credit line.'] };
        return;
      }
      // A Fee/Credit line's amount must not be zero — mirrors
      // FeeService._reject_zero_unit_rate's counterpart for hand-line entry
      // (apps/estimates/services.py EstimateService._validate_price) and
      // FeeModal's client-side zero-rate check; caught here too so the user
      // doesn't need a round trip to find out. An empty amount falls back
      // to '0' in the payload below, so it's zero too.
      if (isFee && (price === '' || priceNum === 0)) {
        fieldErrs = { price: ['A Fee/Credit line must not have a zero price.'] };
        return;
      }
      // A Fee/Credit line's quantity must be > 0 — mirrors
      // EstimateService._validate_qty (a blank qty falls back to '0' in the
      // payload below, same as the zero-price case above; a zero or
      // negative qty renders/crystallizes a fee the customer never saw a
      // nonzero amount for).
      const qtyNum = qty === '' ? NaN : Number(qty);
      if (isFee && (qty === '' || Number.isNaN(qtyNum) || qtyNum <= 0)) {
        fieldErrs = { qty: ['A Fee/Credit line must have a quantity greater than zero.'] };
        return;
      }
      payload = {
        description,
        qty: qty || '0',
        units,
        price: price || '0',
        accounting_category: accountingCategory ? Number(accountingCategory) : null,
        freeform_kind: choice.kind,
      };
    }
    busy = true;
    try {
      await api.post(url, payload);
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

<Modal open={open && choice} onCancel={onClose}>
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
      <h3>{title}</h3>

      {#if isWork}
        <p>
          <label><strong>Rate Scheme</strong><br>
            <select bind:value={rateSchemeId}>
              <option value="">-- none (enter manually) --</option>
              {#each schemes as s (s.rate_scheme_id)}
                <option value={s.rate_scheme_id}>{s.name}</option>
              {/each}
            </select>
          </label>
        </p>
      {/if}

      {#if isFreeform}
        <p><label>Description<br><input type="text" bind:value={description} style="width:100%;box-sizing:border-box;"></label></p>
      {/if}
      <p><label>Quantity<br><input type="number" step="0.01" min="0" value={qty} oninput={(e) => qty = e.target.value}>{#if !isFreeform && baseUnits}<span class="qty-units">{baseUnits}</span>{/if}</label></p>
      <FieldError errors={fieldErrs} field="qty" />

      {#if isWork}
        <p><label>Units<br><UnitsSelect bind:value={units} /></label></p>
        <p><label>Rate<br><input type="number" step="0.01" value={price} oninput={(e) => price = e.target.value}></label></p>
        <FieldError errors={fieldErrs} field="price" />
        <p><label>Accounting Category<br>
          <select bind:value={accountingCategory}>
            <option value="">-- Select --</option>
            {#each categories as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
          </select></label></p>
        <FieldError errors={fieldErrs} field="accounting_category" />
      {:else if isMaterial}
        <p><label>Units<br><UnitsSelect bind:value={units} /></label></p>
        <p><label>Price<br><input type="number" step="0.01" value={price} oninput={(e) => price = e.target.value}></label></p>
        <FieldError errors={fieldErrs} field="price" />
        <p><label>Accounting Category<br>
          <select bind:value={accountingCategory}>
            <option value="">-- Select --</option>
            {#each categories as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
          </select></label></p>
        <FieldError errors={fieldErrs} field="accounting_category" />
      {:else if isFee}
        <p><label>Amount (negative for a credit)<br><input type="number" step="0.01" value={price} oninput={(e) => price = e.target.value}></label></p>
        <FieldError errors={fieldErrs} field="price" />
        {#if isFeeCredit}<p class="credit-note">This will appear as a credit.</p>{/if}
        <p><label>Accounting Category<br>
          <select bind:value={accountingCategory}>
            <option value="">-- Select --</option>
            {#each categories as cat}<option value={cat.id}>{cat.code} - {cat.name}</option>{/each}
          </select></label></p>
        <FieldError errors={fieldErrs} field="accounting_category" />
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy}>Add</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
</Modal>


<style>
  .qty-units { margin-left: 8px; color: #666; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .credit-note { color: #9a3412; font-style: italic; }
</style>
