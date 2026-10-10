<script>
  // From-scratch job creation in Modal (replaces routes/jobs/JobFormPage,
  // 2026-10-10). Opens from the board's New Job button, the jobs list, and
  // a contact/business page (which pre-selects the customer). Edit and
  // Duplicate were already JobEditModal / DuplicateJobModal — this closes
  // the gap. Lands on the new job on success.
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import JobForm from './JobForm.svelte';

  let { open = false, defaultContactId = null, onClose = () => {} } = $props();

  let users = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  async function load() {
    loading = true;
    try { users = await api.get('/api/auth/users/'); }
    catch (e) { showError(errorMessage(e, 'Could not load.')); users = []; }
    finally { loading = false; }
  }

  $effect(() => { if (open) { formError = ''; fieldErrs = {}; load(); } });

  async function handleSubmit(data) {
    formError = ''; fieldErrs = {};
    try {
      const created = await api.post('/api/jobs/', data);
      onClose();
      push(`/jobs/${created.job_id}`);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }
</script>

<!-- Enter is owned by JobForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="640px" label="New job">
  <h3 class="modal-title">New Job</h3>
  <LoadState {loading}>
    <JobForm {users} {defaultContactId} errors={fieldErrs} {formError}
      onSubmit={handleSubmit} onCancel={onClose} />
  </LoadState>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
