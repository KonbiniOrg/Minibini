<script>
  // Dispatcher for the customer-facing token portal. Both documents share the
  // single /portal/ static entry; the `doc` query param selects the surface:
  //   ?token=…                      → estimate  (default; backward compatible)
  //   ?token=…&doc=change_order     → change order
  import EstimatePortal from './EstimatePortal.svelte';
  import ChangeOrderPortal from './ChangeOrderPortal.svelte';

  const doc = new URLSearchParams(window.location.search).get('doc') || 'estimate';
</script>

{#if doc === 'change_order'}
  <ChangeOrderPortal />
{:else}
  <EstimatePortal />
{/if}
