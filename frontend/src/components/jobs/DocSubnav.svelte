<script>
  let { items = [] } = $props();
</script>

<nav class="doc-subnav" aria-label="Documents">
  {#each items as it (it.id)}
    <a href={it.href} class="doc-subnav-link" class:active={it.current}>
      {it.label}
      {#if it.status}<span class="status-badge doc-subnav-pill status-{it.status}">{it.status}</span>{/if}
    </a>
  {/each}
</nav>
