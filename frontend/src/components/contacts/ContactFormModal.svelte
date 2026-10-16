<script>
  // Contact create/edit, hosted in Modal (replaces routes/contacts/
  // ContactFormPage.svelte, 2026-10-10). Opens over whatever page the user
  // is on: the contacts list, a contact's own detail page (edit), or a
  // business page (new contact pre-attached to that business).
  //
  // Duplicate detection is a SUB-STATE: on a 409 duplicate_email the form
  // stays mounted but hidden and DuplicateContactNotice renders in its
  // place; Escape / "Go Back and Edit" return to the form with every typed
  // value intact. Escape again closes. (No stacked modal — RM 2026-10-10.)
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import ContactForm from './ContactForm.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';

  let {
    open = false,
    contact = null,            // null → create; detail object → edit
    defaultBusinessId = null,  // create only: pre-attach to this business
    onSaved = () => {},        // edit only: (updatedContact)
    onClose = () => {},
  } = $props();

  const isEdit = $derived(!!contact);

  let formError = $state('');
  let fieldErrs = $state({});
  let duplicateContact = $state(null);

  // Fresh messages on every open. (Modal unmounts its children when closed,
  // so ContactForm's own state re-seeds on the next open by itself.)
  $effect(() => {
    if (open) { formError = ''; fieldErrs = {}; duplicateContact = null; }
  });

  async function handleSubmit(data) {
    formError = '';
    fieldErrs = {};
    duplicateContact = null;
    try {
      if (isEdit) {
        const updated = await api.patch(`/api/contacts/${contact.contact_id}/`, data);
        onSaved(updated);
      } else {
        const created = await api.post('/api/contacts/', data);
        onClose();
        push(`/contacts/${created.contact_id}`);
      }
    } catch (e) {
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_email') {
        duplicateContact = e.data.existing_contact;
        return;
      }
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }

  // Escape backs out one level: notice → form → closed.
  function handleCancel() {
    if (duplicateContact) duplicateContact = null;
    else onClose();
  }

  async function reactivateExisting() {
    const id = duplicateContact.contact_id;
    try {
      await api.post(`/api/contacts/${id}/reactivate/`, {});
      onClose();
      push(`/contacts/${id}`);
    } catch (e) {
      showError(errorMessage(e, 'Could not reactivate the contact.'));
    }
  }

  function viewExisting() {
    const id = duplicateContact.contact_id;
    onClose();
    push(`/contacts/${id}`);
  }
</script>

<!-- Enter is owned by ContactForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={handleCancel} maxWidth="640px" label={isEdit ? 'Edit contact' : 'New contact'}>
  <h3 class="modal-title">{isEdit ? 'Edit Contact' : 'New Contact'}</h3>

  {#if duplicateContact}
    <DuplicateContactNotice
      contact={duplicateContact}
      onViewExisting={viewExisting}
      onReactivate={reactivateExisting}
      onBack={() => { duplicateContact = null; }}
    />
  {/if}

  <!-- hidden, not {#if}: the form must survive the notice round-trip. -->
  <div hidden={!!duplicateContact}>
    <ContactForm
      {contact}
      {defaultBusinessId}
      errors={fieldErrs}
      {formError}
      onSubmit={handleSubmit}
      onCancel={onClose}
    />
  </div>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
