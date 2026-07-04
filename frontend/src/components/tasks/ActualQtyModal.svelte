<script>
  import Modal from '../Modal.svelte';

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

<Modal open={true} onSave={submit} onCancel={onClose} maxWidth="570px">
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
</Modal>

<style>
  .buttons { display: flex; gap: 8px; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
