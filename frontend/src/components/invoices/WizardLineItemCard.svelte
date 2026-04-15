<script>
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';

  let { lineItem, invoiceId, canAddHere = false, onAddHere, onchange } = $props();

  let nameValue = $state(lineItem.description);
  let qtyValue = $state(lineItem.qty);
  let unitsValue = $state(lineItem.units);
  let priceValue = $state(lineItem.price);
  // Tracks whether the user has manually touched the price field this edit session.
  // Reset on save / reset-to-computed.
  let priceManuallyEdited = $state(false);
  let saving = $state(false);

  // Sum of source atom computed amounts (the "computed total")
  const computedSum = $derived(
    lineItem.sources.reduce((sum, s) => sum + parseFloat(s.computed_amount), 0)
  );
  // Per-unit price the wizard would compute from the SAVED qty: round(sum/qty, 2)
  const expectedPerUnit = $derived(
    parseFloat(lineItem.qty) > 0
      ? Math.round((computedSum / parseFloat(lineItem.qty)) * 100) / 100
      : 0
  );
  const isBundled = $derived(lineItem.sources.length > 0);
  // True iff the SAVED line item is overridden (rounding-safe).
  const isOverridden = $derived(
    isBundled && Math.abs(parseFloat(lineItem.price) - expectedPerUnit) > 0.001
  );
  // Live preview total — uses local state so it updates as the user types
  const liveTotal = $derived(
    (parseFloat(qtyValue) || 0) * (parseFloat(priceValue) || 0)
  );
  const isDirty = $derived(
    nameValue !== lineItem.description ||
    parseFloat(qtyValue) !== parseFloat(lineItem.qty) ||
    unitsValue !== lineItem.units ||
    parseFloat(priceValue) !== parseFloat(lineItem.price)
  );

  function onQtyInput() {
    // If the saved line was in sync AND the user hasn't touched price this session,
    // live-recompute the per-unit price as qty changes so the total stays pinned to
    // the sum of atoms.
    if (isBundled && !isOverridden && !priceManuallyEdited) {
      const newQty = parseFloat(qtyValue);
      if (newQty > 0) {
        priceValue = (computedSum / newQty).toFixed(2);
      }
    }
  }

  function onPriceInput() {
    priceManuallyEdited = true;
  }

  async function save() {
    if (!isDirty || saving) return;
    saving = true;
    try {
      const updated = await api.patch(
        `/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`,
        {
          description: nameValue,
          qty: qtyValue,
          units: unitsValue,
          price: priceValue,
        },
      );
      // Re-sync local state from the server's response so any backend
      // normalization (e.g. quantization) is reflected and isDirty becomes false.
      nameValue = updated.description;
      qtyValue = updated.qty;
      unitsValue = updated.units;
      priceValue = updated.price;
      priceManuallyEdited = false;
      onchange?.();
    } catch (e) {
      alert(e.message || 'Save failed');
    } finally {
      saving = false;
    }
  }

  async function removeSource(sourceId) {
    await api.post(
      `/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/remove-atoms/`,
      {source_ids: [sourceId]},
    );
    onchange?.();
  }

  async function deleteLineItem() {
    if (!confirm('Delete this line item?')) return;
    await api.delete(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`);
    onchange?.();
  }

  function resetToComputed() {
    const qty = parseFloat(qtyValue) || 1;
    priceValue = (computedSum / qty).toFixed(2);
    priceManuallyEdited = false;
  }
</script>

<form
  onsubmit={(e) => { e.preventDefault(); save(); }}
  style="border: 1px solid #aaa; padding: 8px; margin-bottom: 8px;"
>
  <div style="display: flex; align-items: center; gap: 6px;">
    <strong>{lineItem.line_number}.</strong>
    <input
      bind:value={nameValue}
      placeholder="Name this line item…"
      style="flex: 1;"
    />
    <button
      type="button"
      onclick={() => onAddHere?.(lineItem.line_item_id)}
      disabled={!canAddHere}
      title={canAddHere ? 'Add selected atoms to this line item' : 'Select atoms first'}
    >Add Here</button>
    <button type="button" onclick={deleteLineItem}>×</button>
  </div>

  <div style="display: flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap;">
    <label>Qty <input bind:value={qtyValue} oninput={onQtyInput} style="width: 5em;"></label>
    <label>Units <UnitsSelect bind:value={unitsValue} /></label>
    <label>Price $<input bind:value={priceValue} oninput={onPriceInput} style="width: 6em;"></label>
    <span style="color: #555;">= ${liveTotal.toFixed(2)}</span>
    <button type="submit" disabled={!isDirty || saving}>
      {saving ? 'Saving…' : 'Save'}
    </button>
    {#if isBundled && isOverridden}
      <span style="color: #a55;">⚠ overridden (computed ${computedSum.toFixed(2)})</span>
      <a href="#" onclick={(e) => { e.preventDefault(); resetToComputed(); }}>reset to computed</a>
    {:else if !isBundled}
      <span style="color: #888;"><em>(manual)</em></span>
    {/if}
  </div>

  {#if lineItem.sources.length > 0}
    <div style="padding-left: 8px; font-size: 11px; color: #555;">
      {#each lineItem.sources as source}
        <div>
          ↳ {source.description}
          <button type="button" onclick={() => removeSource(source.source_id)} style="color: #a00;">✕</button>
        </div>
      {/each}
    </div>
  {/if}
</form>
