<script>
  let {
    mode,
    onMode,
    modes = ['edit', 'customer', 'reorder'],
    labels = { edit: 'Edit', customer: 'Customer', reorder: 'Reorder' },
  } = $props();
</script>

<!-- Chrome lives in app.css (.doc-mode-bar family) per the docsurface kit
     convention. The switchers stay <button>s — a mode flip acts, it doesn't
     navigate — but render as text chips in the labeled band. -->
<div class="doc-mode-bar">
  <span class="doc-mode-bar-label">Views</span>
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
