<script>
  import { modalKeys } from '../../lib/modalKeys.js';

  // Reusable prompt for the worker-entered quantity an ENTERED_QTY task
  // needs before it can be completed. Pure input collector — the caller
  // owns the API call via onSubmit.
  let { unitLabel = '', onSubmit, onClose } = $props();

  let value = $state('');
  let error = $state('');

  function submit() {
    const qty = parseFloat(value);
    if (!(qty > 0)) {
      error = 'Enter a quantity greater than 0.';
      return;
    }
    onSubmit(qty);
  }
</script>

<div class="overlay" use:modalKeys={{ onSave: submit, onCancel: onClose }}>
  <div class="modal" role="dialog" tabindex="-1">
    <h3>Quantity needed</h3>
    <p>
      This task is billed per <strong>{unitLabel || 'unit'}</strong>.
      Enter the quantity worked to complete it:
    </p>
    <p>
      <label>
        <strong>Quantity ({unitLabel || 'units'})</strong><br>
        <input type="number" step="any" min="0" bind:value>
      </label>
    </p>
    {#if error}<p class="error">{error}</p>{/if}
    <div class="buttons">
      <button type="button" onclick={submit}>Complete task</button>
      <button type="button" onclick={onClose}>Cancel</button>
    </div>
  </div>
</div>

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 1100;
  }
  .modal {
    background: white; padding: 16px; max-width: 380px;
    border: 1px solid #ccc;
  }
  .buttons { display: flex; gap: 8px; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
