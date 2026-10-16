<script>
  // Thin wrapper kept for EmailCreatePOPage (PO process is parked). The
  // create modals render DuplicateContactNotice directly as a sub-state.
  // Esc-only: both actions are navigation, no single confirm — no onSave.
  import Modal from '../Modal.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';

  const {
    open = false,
    contact = null,
    onViewExisting = () => {},
    onClose = () => {},
  } = $props();
</script>

<Modal {open} onCancel={onClose} maxWidth="500px" label="Possible duplicate contact">
  <DuplicateContactNotice {contact} {onViewExisting} onBack={onClose} />
</Modal>
