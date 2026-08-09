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

  button {
    padding: 6px 12px;
    border: 1px solid #ccc;
    background: #f5f5f5;
    color: #333;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
  }

  button:hover {
    background: #efefef;
  }
</style>
