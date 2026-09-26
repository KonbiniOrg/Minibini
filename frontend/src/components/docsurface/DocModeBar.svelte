<script>
  let {
    mode,
    onMode,
    modes = ['edit', 'customer', 'reorder'],
    labels = { edit: 'Edit view', customer: 'Customer view', reorder: 'Reorder view' },
  } = $props();
</script>

<!-- Chrome lives in app.css (.doc-mode-bar family) per the docsurface kit
     convention. The switchers stay <button>s — a mode flip acts, it doesn't
     navigate — but render as text chips in the tinted band. Labels carry
     the " view" suffix themselves (RM 2026-08-14) — the old standalone
     "Views" band label sat too far from the chips to bind to them. -->
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
