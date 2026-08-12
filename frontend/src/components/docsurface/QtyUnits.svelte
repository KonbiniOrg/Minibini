<script>
  // Qty-cell content for document line items (estimate / invoice / CO edit
  // and customer tables): qty and units inline — the space between them
  // lets a squeezed column wrap the units under the qty naturally
  // (RM 2026-08-11: wrap-when-squeezed, never a forced second line). Units
  // 'none'/empty are omitted; a missing qty renders '-'. Behavior mirrors
  // lib/format.js formatQtyUnits — this component is the single seam for
  // styling the doc tables' qty cells later without another sweep.
  let { qty, units } = $props();

  let hasQty = $derived(!(qty === null || qty === undefined || qty === ''));
  let showUnits = $derived(!!units && units !== 'none');
</script>

{#if !hasQty}-{:else if showUnits}{qty} {units}{:else}{qty}{/if}
