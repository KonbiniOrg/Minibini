<script>
  // The one pager for every paged list. Both buttons are always rendered —
  // disabled at the ends rather than removed — so Next sits in the same spot
  // on page 1 as on page 2 and the pointer never has to chase it.
  import { PAGE_SIZE } from '../lib/pagination.js';

  let { page, count, pageSize = PAGE_SIZE, label = null, onPage } = $props();

  const totalPages = $derived(Math.max(1, Math.ceil((count || 0) / pageSize)));
</script>

{#if count > pageSize}
  <p class="pager">
    <button type="button" disabled={page <= 1} onclick={() => onPage(page - 1)}>Previous</button>
    <span>{label ?? `Page ${page} of ${totalPages}`}</span>
    <button type="button" disabled={page >= totalPages} onclick={() => onPage(page + 1)}>Next</button>
  </p>
{/if}
