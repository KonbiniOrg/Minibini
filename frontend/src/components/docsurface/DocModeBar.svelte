<script>
  let {
    mode,
    onMode,
    modes = ['edit', 'customer', 'reorder'],
    labels = { edit: 'Edit', customer: 'Customer', reorder: 'Reorder' },
  } = $props();
</script>

<div class="doc-mode-bar">
  {#each modes as m}
    <button
      type="button"
      aria-pressed={mode === m}
      onclick={() => onMode(m)}
    >
      {labels[m]}
    </button>
  {/each}
</div>

<style>
  .doc-mode-bar {
    display: flex;
    gap: 8px;
  }
</style>
