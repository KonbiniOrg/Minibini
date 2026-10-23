<script>
  // EmptyState — the one empty-state pattern (frontend/README.md → "Job tab
  // structure"): one sentence saying what to do next, plus the action when
  // the action only exists because the list is empty (Start Estimate). A
  // persistent tab action stays in the TabHeader; the sentence points at it
  // instead of repeating the button. A text-only empty list inside a
  // DataTable keeps using its `emptyText` (same muted look, app-wide).
  let { text, action = null, class: className = '' } = $props();
</script>

<div class="empty-state {className}">
  <p class="empty-state-text">{text}</p>
  {#if action}<div class="empty-state-action">{@render action()}</div>{/if}
</div>

<style>
  .empty-state-text { color: var(--text-muted); }
  .empty-state-action {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  }
</style>
