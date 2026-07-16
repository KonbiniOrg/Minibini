<script>
  // Esc-only: "view the existing contact" and "go back and edit" are both
  // just navigation, not a single obvious confirm action — so no onSave.
  import Modal from '../Modal.svelte';

  const {
    open = false,
    contact = null,
    onViewExisting = () => {},
    onClose = () => {},
  } = $props();
</script>

<Modal {open} onCancel={onClose} maxWidth="500px" label="Possible duplicate contact">
  <h3 class="dup-modal-title">This contact may already exist</h3>

  {#if contact}
    <p>A contact with this email address is already in the system:</p>
    <p>
      <strong>{contact.name}</strong><br>
      {contact.email}<br>
      {#if contact.mobile_number || contact.work_number || contact.home_number}
        {contact.mobile_number || contact.work_number || contact.home_number}<br>
      {/if}
      {#if contact.business}
        {contact.business.business_name}
      {/if}
    </p>
  {/if}

  <p>
    <button type="button" onclick={onViewExisting}>View Existing Contact</button>
    <button type="button" onclick={onClose}>Go Back and Edit</button>
  </p>
</Modal>

<style>
  .dup-modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
