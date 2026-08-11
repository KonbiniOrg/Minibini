<script>
  // Qty-cell content for document line items (estimate / invoice / CO edit
  // and customer tables): the quantity with its units stacked beneath in
  // muted small text (RM 2026-08-11). Units 'none'/empty are omitted; a
  // missing qty renders '-' — both mirroring lib/format.js formatQtyUnits,
  // which remains the inline (single-string) variant used by the atom
  // child/pool rows.
  let { qty, units } = $props();

  let hasQty = $derived(!(qty === null || qty === undefined || qty === ''));
  let showUnits = $derived(!!units && units !== 'none');
</script>

{#if !hasQty}-{:else}{qty}{#if showUnits}<br><small class="qty-units-under">{units}</small>{/if}{/if}

<style>
  .qty-units-under { color: #6b7280; }
</style>
