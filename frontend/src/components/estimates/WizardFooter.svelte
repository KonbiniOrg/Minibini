<script>
  let {
    selectedCount = 0,
    onCreateNew = () => {},
    canAct = false,
  } = $props();
</script>

<div class="wizard-footer">
  <span>{selectedCount} atom(s) selected</span>
  <button type="button" onclick={onCreateNew} disabled={!canAct}>
    Create new line item from selected
  </button>
</div>

<style>
  .wizard-footer {
    position: sticky; bottom: 0; background: #f0f0f0;
    padding: 0.6rem; border-top: 1px solid #ccc; margin-top: 1rem;
  }
  .wizard-footer button { margin-left: 1rem; }
</style>
