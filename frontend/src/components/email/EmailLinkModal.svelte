<script>
  // Link an email to an existing Job or Purchase Order (replaces
  // EmailAssociatePage / EmailAssociatePOPage, 2026-10-10). The email stays
  // visible behind the modal, which is the whole point of linking.
  import { emailApi } from '../../lib/email.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import FormMessage from '../FormMessage.svelte';
  import JobPicker from '../JobPicker.svelte';
  import PurchaseOrderPicker from '../PurchaseOrderPicker.svelte';

  let { emailRecordId, kind = 'job', open = false, onLinked = () => {}, onClose = () => {} } = $props();

  // null, never '' — SearchPicker treats '' as a real value and tries to
  // resolve a label for it (the old EmailAssociatePage regression).
  let selectedId = $state(null);
  let submitting = $state(false);
  let submitError = $state('');

  $effect(() => { if (open) { selectedId = null; submitting = false; submitError = ''; } });

  const isJob = $derived(kind === 'job');

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedId) {
      submitError = isJob ? 'Please select a job.' : 'Please select a purchase order.';
      return;
    }
    submitting = true; submitError = '';
    try {
      if (isJob) await emailApi.linkToJob(emailRecordId, selectedId);
      else await emailApi.linkToPo(emailRecordId, selectedId);
      onLinked();
    } catch (err) {
      const t = triageError(err);
      if (t.overlay) showError(t.overlay); else submitError = t.message;
    } finally {
      submitting = false;
    }
  }
</script>

<!-- Enter is owned by the native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="560px" label={isJob ? 'Link to job' : 'Link to purchase order'}>
  <h3 class="modal-title">{isJob ? 'Link to existing job' : 'Link to existing purchase order'}</h3>
  <form onsubmit={handleSubmit}>
    <p>
      <label><strong>{isJob ? 'Job' : 'Purchase Order'} *</strong></label><br>
      {#if isJob}
        <JobPicker bind:value={selectedId} />
      {:else}
        <PurchaseOrderPicker bind:value={selectedId} />
      {/if}
    </p>
    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Linking…' : (isJob ? 'Link to job' : 'Link to purchase order')}
      </button>
      <button type="button" onclick={onClose} disabled={submitting}>Cancel</button>
    </p>
    <FormMessage error={submitError} />
  </form>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
