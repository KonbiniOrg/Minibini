<script>
  // Dispatcher for the customer-facing token portal. Both documents share the
  // single /portal/ static entry; the `doc` query param selects the surface and
  // is REQUIRED — a link without it (or with an unknown value) is treated as
  // not-found rather than silently assuming a document type:
  //   ?token=…&doc=estimate       → estimate
  //   ?token=…&doc=change_order   → change order
  import EstimatePortal from './EstimatePortal.svelte';
  import ChangeOrderPortal from './ChangeOrderPortal.svelte';

  const doc = new URLSearchParams(window.location.search).get('doc') || '';
</script>

{#if doc === 'estimate'}
  <EstimatePortal />
{:else if doc === 'change_order'}
  <ChangeOrderPortal />
{:else}
  <main class="portal">
    <p class="err">The document you requested could not be found. Please check
      the link, or contact us if you believe this is an error.</p>
  </main>
{/if}

<style>
  .portal { max-width: 720px; margin: 2em auto; font-family: sans-serif; }
  .err { color: #b00; }
</style>
