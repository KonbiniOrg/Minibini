<script>
  // "Create job from email" in Modal over the email detail page (replaces
  // routes/email/EmailCreateJobPage, 2026-10-10 — the email stays visible
  // behind the form, which is the point). Sender resolution is the shared
  // SenderResolutionForm block; duplicate contact/business prompts are
  // in-modal sub-states (form hidden, Escape backs out one level).
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { emailApi, resolveSenderToContact } from '../../lib/email.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import FormMessage from '../FormMessage.svelte';
  import SenderResolutionForm from './SenderResolutionForm.svelte';
  import DuplicateContactNotice from '../contacts/DuplicateContactNotice.svelte';
  import DuplicateBusinessNotice from '../contacts/DuplicateBusinessNotice.svelte';

  let { emailRecordId, open = false, onClose = () => {} } = $props();

  let loading = $state(true);
  let loadError = $state(null);
  let senderInfo = $state(null);
  let resolutionState = $state(null);
  let jobName = $state('');
  let jobDescription = $state('');
  let submitting = $state(false);
  let submitError = $state('');
  let duplicateContact = $state(null);
  let duplicateBusiness = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    senderInfo = null;
    try {
      senderInfo = await emailApi.senderInfo(emailRecordId);
      jobName = senderInfo.subject || '';
      jobDescription = senderInfo.suggested_body || '';
    } catch (e) {
      loadError = errorMessage(e, 'Could not load email.');
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (open && emailRecordId) {
      submitError = ''; submitting = false; duplicateContact = null; duplicateBusiness = null;
      load();
    }
  });

  async function handleSubmit(e) {
    e.preventDefault();
    submitError = ''; duplicateContact = null; duplicateBusiness = null;
    submitting = true;
    try {
      const { contactId } = await resolveSenderToContact(resolutionState);
      const job = await emailApi.createJob(emailRecordId, {
        contact: contactId,
        name: jobName.trim(),
        description: jobDescription.trim(),
      });
      onClose();
      push(`/jobs/${job.job_id}`);
    } catch (err) {
      if (err.status === 409 && err.data?.code === 'duplicate_email') {
        duplicateContact = err.data.existing_contact;
      } else if (err.status === 409 && err.data?.code === 'duplicate_business_name') {
        duplicateBusiness = err.data.existing_business;
      } else {
        const t = triageError(err);
        if (t.overlay) showError(t.overlay); else submitError = t.message;
      }
    } finally {
      submitting = false;
    }
  }

  const noticeShowing = $derived(!!duplicateContact || !!duplicateBusiness);

  function handleCancel() {
    if (noticeShowing) { duplicateContact = null; duplicateBusiness = null; }
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

  function go(path) { onClose(); push(path); }
</script>

<!-- Enter is owned by the native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={handleCancel} maxWidth="720px" label="Create job from email">
  <h3 class="modal-title">Create Job from Email</h3>

  {#if duplicateContact}
    <DuplicateContactNotice contact={duplicateContact}
      onViewExisting={() => go(`/contacts/${duplicateContact.contact_id}`)}
      onReactivate={reactivateExisting}
      onBack={() => { duplicateContact = null; }} />
  {:else if duplicateBusiness}
    <DuplicateBusinessNotice business={duplicateBusiness}
      onViewExisting={() => go(`/businesses/${duplicateBusiness.business_id}`)}
      onBack={() => { duplicateBusiness = null; }} />
  {/if}

  <!-- hidden, not {#if}: the form must survive the notice round-trip. -->
  <div hidden={noticeShowing}>
    <LoadState {loading} error={loadError}>
    {#if senderInfo}
      <form onsubmit={handleSubmit}>
        <SenderResolutionForm {senderInfo} bind:state={resolutionState} />

        <h3>Job</h3>
        <p>
          <label for="job_name"><strong>Job Name *</strong> (max 50 chars)</label><br>
          <input type="text" id="job_name" bind:value={jobName} maxlength="50" required>
        </p>
        <p>
          <label for="job_description"><strong>Description</strong></label><br>
          <textarea id="job_description" bind:value={jobDescription} rows="8" cols="60"></textarea>
        </p>

        <p>
          <button type="submit" disabled={submitting}>{submitting ? 'Creating…' : 'Create Job'}</button>
          <button type="button" onclick={onClose} disabled={submitting}>Cancel</button>
        </p>
        <FormMessage error={submitError} />
      </form>
    {/if}
    </LoadState>
  </div>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
