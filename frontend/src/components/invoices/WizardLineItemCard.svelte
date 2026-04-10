<script>
  import { api } from '../../lib/api.js';

  let { lineItem, invoiceId, selected = false, onselect, onchange } = $props();

  let nameValue = $state(lineItem.description);
  let priceValue = $state(lineItem.price);

  // Derived: computed sum of source atoms
  const computedPrice = $derived(
    lineItem.sources.reduce((sum, s) => sum + parseFloat(s.computed_amount), 0)
  );
  const isOverridden = $derived(
    Math.abs(parseFloat(lineItem.price) - computedPrice) > 0.001
  );

  async function saveName() {
    if (nameValue !== lineItem.description) {
      await api.patch(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`, {
        description: nameValue,
      });
      onchange?.();
    }
  }

  async function savePrice() {
    if (parseFloat(priceValue) !== parseFloat(lineItem.price)) {
      await api.patch(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`, {
        price: priceValue,
      });
      onchange?.();
    }
  }

  async function removeSource(sourceId) {
    const response = await api.post(
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

  async function resetToComputed() {
    priceValue = computedPrice.toFixed(2);
    await savePrice();
  }
</script>

<div
  style="border: 1px solid {selected ? '#246' : '#aaa'}; padding: 8px; margin-bottom: 8px;"
  onclick={() => onselect?.(lineItem.line_item_id)}
>
  <div style="display: flex; align-items: center; gap: 6px;">
    <strong>{lineItem.line_number}.</strong>
    <input
      bind:value={nameValue}
      onblur={saveName}
      placeholder="Name this line item…"
      style="flex: 1;"
    />
    <button onclick={deleteLineItem}>×</button>
  </div>

  {#if lineItem.sources.length === 0}
    <!-- Manual line item -->
    <div>
      <label>Price <input bind:value={priceValue} onblur={savePrice} /></label>
      <span><em>(manual)</em></span>
    </div>
  {:else if isOverridden}
    <div>
      <span style="color: #666;">Computed: ${computedPrice.toFixed(2)}</span>
      &nbsp;
      <strong>Billed: $<input bind:value={priceValue} onblur={savePrice} /></strong>
      <span style="color: #a55;"> ⚠ overridden</span>
      <a href="#" onclick={(e) => { e.preventDefault(); resetToComputed(); }}>reset to computed</a>
    </div>
  {:else}
    <div>
      <strong>$<input bind:value={priceValue} onblur={savePrice} /></strong>
    </div>
  {/if}

  {#if lineItem.sources.length > 0}
    <div style="padding-left: 8px; font-size: 11px; color: #555;">
      {#each lineItem.sources as source}
        <div>
          ↳ {source.description}
          <button onclick={() => removeSource(source.source_id)} style="color: #a00;">✕</button>
        </div>
      {/each}
    </div>
  {/if}
</div>
