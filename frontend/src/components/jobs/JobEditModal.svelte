<script>
  // Edit form extracted from routes/jobs/JobEditPage.svelte, hosted in Modal.
  // The page is gone (Task 11) — this opens from JobHeader's Edit button on
  // any job page. `job` is the already-loaded detail object the header
  // already holds (full detail fetch, so description/due_date/etc. are all
  // present) — no need to refetch it here.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import Modal from '../Modal.svelte';
  import ContactPicker from '../ContactPicker.svelte';

  const {
    job,
    open = false,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let name = $state('');
  let description = $state('');
  let dueDate = $state('');
  let customerPoNumber = $state('');
  let projectManager = $state('');
  let contact = $state(null);
  let users = $state([]);
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  function toDatetimeLocal(iso) {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  // Prefill (and re-fetch the PM picker's user list) every time the modal
  // opens, from whatever `job` the header is currently holding.
  $effect(() => {
    if (open && job) {
      name = job.name || '';
      description = job.description || '';
      customerPoNumber = job.customer_po_number || '';
      dueDate = job.due_date ? toDatetimeLocal(job.due_date) : '';
      projectManager = job.project_manager != null ? String(job.project_manager) : '';
      contact = job.contact ?? null;
      formError = '';
      fieldErrs = {};
      // Only the PM picker (shown to whoever may manage this job) needs this list.
      if (job.can_manage) {
        api.get('/api/auth/users/')
          .then((u) => { users = u; })
          .catch(() => { users = []; });
      } else {
        users = [];
      }
    }
  });

  async function handleSubmit(e) {
    e.preventDefault();
    saving = true;
    formError = '';
    fieldErrs = {};
    const payload = {
      name,
      description,
      customer_po_number: customerPoNumber,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
      project_manager: projectManager ? Number(projectManager) : null,
      contact,
    };
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, payload);
      onSaved();
    } catch (err) {
      const t = triageError(err);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      saving = false;
    }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="600px" label="Edit job">
  <h3 class="edit-modal-title">Edit Job: {job?.job_number}</h3>

  <form onsubmit={handleSubmit}>
    <p>
      <label for="edit-job-name"><strong>Name</strong></label><br>
      <input id="edit-job-name" type="text" maxlength="50" bind:value={name}>
      <FieldError errors={fieldErrs} field="name" />
    </p>

    <p>
      <strong>Contact</strong><br>
      {#if job?.status === 'draft'}
        <ContactPicker bind:value={contact} />
      {:else}
        {job?.contact_name}
        <br><small>Contact can only be changed while the job is a draft.</small>
      {/if}
      <FieldError errors={fieldErrs} field="contact" />
    </p>

    <p>
      <label for="edit-job-description"><strong>Description</strong></label><br>
      <textarea id="edit-job-description" rows="6" cols="60" bind:value={description}></textarea>
      <FieldError errors={fieldErrs} field="description" />
    </p>

    <p>
      <label for="edit-job-due-date"><strong>Due Date</strong></label><br>
      <input id="edit-job-due-date" type="datetime-local" bind:value={dueDate}>
      <FieldError errors={fieldErrs} field="due_date" />
    </p>

    <p>
      <label for="edit-job-customer-po"><strong>Customer PO Number</strong></label><br>
      <input id="edit-job-customer-po" type="text" maxlength="50" bind:value={customerPoNumber}>
      <FieldError errors={fieldErrs} field="customer_po_number" />
    </p>

    <p>
      <label for="edit-job-project-manager"><strong>Project Manager</strong></label><br>
      <select id="edit-job-project-manager" bind:value={projectManager}>
        <option value="">-- None --</option>
        {#each users as u}
          <option value={String(u.id)}>{u.name}</option>
        {/each}
      </select>
      <FieldError errors={fieldErrs} field="project_manager" />
    </p>

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
      <button type="button" onclick={onClose} disabled={saving}>Cancel</button>
    </p>

    <FormMessage error={formError} />
  </form>
</Modal>

<style>
  .edit-modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
