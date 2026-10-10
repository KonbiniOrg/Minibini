<script>
  // Thin wrapper kept for EmailCreatePOPage (PO process is parked). The
  // create modals render DuplicateBusinessNotice directly as a sub-state.
  // Esc-only: both actions are navigation, no single confirm — no onSave.
  import Modal from '../Modal.svelte';
  import DuplicateBusinessNotice from './DuplicateBusinessNotice.svelte';

  const {
    open = false,
    business = null,
    onViewExisting = () => {},
    onClose = () => {},
  } = $props();
</script>

<Modal {open} onCancel={onClose} maxWidth="500px" label="Possible duplicate business">
  <DuplicateBusinessNotice {business} {onViewExisting} onBack={onClose} />
</Modal>
