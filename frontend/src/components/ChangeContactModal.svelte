<script>
  import Modal from './Modal.svelte';
  import ContactPicker from './ContactPicker.svelte';
  import FormMessage from './FormMessage.svelte';
  import { api } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  let { open = false, patchUrl, businessId = null, onSaved = () => {}, onClose = () => {} } = $props();
  let contact = $state(null);
  let formError = $state('');
  let saving = $state(false);
  $effect(() => { if (open) { contact = null; formError = ''; } });
  async function save(e) {
    e?.preventDefault?.();
    if (contact == null) { formError = 'Pick a contact.'; return; }
    saving = true; formError = '';
    try { await api.patch(patchUrl, { contact }); onSaved(); onClose(); }
    catch (err) { const t = triageError(err); if (t.overlay) showError(t.overlay); else formError = t.message; }
    finally { saving = false; }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="520px" label="Change contact">
  <h3 class="modal-title">Change contact</h3>
  <form onsubmit={save}>
    <p><label for="change-contact-picker"><strong>New contact</strong></label><br><ContactPicker bind:value={contact} {businessId} inputId="change-contact-picker" /></p>
    <p>
      <button type="submit" disabled={saving}>Save</button>
      <button type="button" onclick={onClose}>Cancel</button>
    </p>
    <FormMessage error={formError} />
  </form>
</Modal>
