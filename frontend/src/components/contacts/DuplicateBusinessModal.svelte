<script>
  // Esc-only: "view the existing business" and "go back and edit" are both
  // just navigation, not a single obvious confirm action — so no onSave.
  import Modal from '../Modal.svelte';

  const {
    open = false,
    business = null,
    onViewExisting = () => {},
    onClose = () => {},
  } = $props();
</script>

<Modal {open} onCancel={onClose} maxWidth="500px" label="Possible duplicate business">
  <h3 class="dup-modal-title">This business may already exist</h3>

  {#if business}
    <p>A business with this name is already in the system:</p>
    <p>
      <strong>{business.business_name}</strong><br>
      {#if business.our_reference_code}
        {business.our_reference_code}<br>
      {/if}
      {#if business.business_phone}
        {business.business_phone}<br>
      {/if}
    </p>
  {/if}

  <p>
    <button type="button" onclick={onViewExisting}>View Existing Business</button>
    <button type="button" onclick={onClose}>Go Back and Edit</button>
  </p>
</Modal>

<style>
  .dup-modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
