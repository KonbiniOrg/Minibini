<script>
  // Extracted from routes/jobs/DuplicateJobPage.svelte, hosted in Modal.
  // Opens from JobHeader's Duplicate… button, which only renders when
  // job.can_manage — so unlike the old page, no permission-denied branch
  // is needed here.
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import ContactPicker from '../ContactPicker.svelte';
  import Modal from '../Modal.svelte';

  const { job, open = false, onClose = () => {} } = $props();

  let selectedContactId = $state(null);
  let path = $state('approved');
  let submitting = $state(false);

  $effect(() => {
    if (open && job) {
      selectedContactId = job.contact ?? null;
      path = 'approved';
      submitting = false;
    }
  });

  async function submit() {
    submitting = true;
    try {
      const result = await api.post(`/api/jobs/${job.job_id}/duplicate/`, {
        contact_id: selectedContactId,
        path,
      });
      onClose();
      push(`/jobs/${result.job_id}`);
    } catch (e) {
      // api.js renders the error overlay; just re-enable the button.
      submitting = false;
    }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="600px" label="Duplicate job">
  <h3 class="dup-modal-title">Duplicate {job?.job_number}</h3>

  <p><label><strong>Customer *</strong></label><br>
    <ContactPicker bind:value={selectedContactId} />
  </p>

  <fieldset>
    <legend><strong>What kind of copy?</strong></legend>
    <p><label>
      <input type="radio" name="dup-path" value="approved" bind:group={path}>
      Immediately approved — ready to work, reuses the original's pricing as-is.
    </label></p>
    <p><label>
      <input type="radio" name="dup-path" value="estimate" bind:group={path}>
      Requires a new estimate — re-quote before work starts.
    </label></p>
    <p><em>If rates or material prices may have moved since the original, choose
      "Requires a new estimate" to re-quote.</em></p>
  </fieldset>

  <p>
    <button type="button" onclick={submit}
            disabled={submitting || !selectedContactId}>
      {submitting ? 'Duplicating…' : 'Duplicate'}
    </button>
    <button type="button" onclick={onClose} disabled={submitting}>Cancel</button>
  </p>
</Modal>

<style>
  .dup-modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
