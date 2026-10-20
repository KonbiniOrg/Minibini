<script>
  // Row drag handle (issue #513), replacing the up/down reorder arrows.
  // `attach` is the row's dnd-kit sortable handleRef. Keyboard: focus the
  // handle, Space/Enter picks the row up, arrow keys move it, Space/Enter
  // drops, Escape cancels (dnd-kit's default keyboard sensor). The grip is
  // an inline six-dot icon so this needs no icon library.
  let { attach = null, label = 'Drag to reorder' } = $props();
</script>

<button
  {@attach (node) => attach?.(node)}
  type="button"
  class="drag-handle"
  aria-label={label}
  title="Drag to reorder"
>
  <svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true">
    <circle cx="3" cy="3" r="1.4" /><circle cx="7" cy="3" r="1.4" />
    <circle cx="3" cy="8" r="1.4" /><circle cx="7" cy="8" r="1.4" />
    <circle cx="3" cy="13" r="1.4" /><circle cx="7" cy="13" r="1.4" />
  </svg>
</button>

<style>
  .drag-handle {
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 20px; padding: 0; margin: 0 6px 0 -4px;
    vertical-align: middle;
    border: 0; border-radius: 3px; background: none;
    color: #9ca3af; cursor: grab; touch-action: none;
  }
  .drag-handle:hover { color: #4b5563; background: #f0f0f0; }
  .drag-handle:active { cursor: grabbing; }
  .drag-handle:focus-visible { outline: 2px solid var(--doc-accent, #2563eb); outline-offset: 1px; }
  .drag-handle svg { fill: currentColor; }
</style>
