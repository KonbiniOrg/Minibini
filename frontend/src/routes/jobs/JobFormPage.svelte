<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import JobForm from '../../components/jobs/JobForm.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { push, querystring } from 'svelte-spa-router';

  // Context from query param (?contact=…) — e.g. the "New Job" link on a
  // contact or business detail page.
  const initialParams = new URLSearchParams($querystring);
  const contextContactId = initialParams.get('contact') ? Number(initialParams.get('contact')) : null;

  let users = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  async function load() {
    loading = true;
    try {
      users = await api.get('/api/auth/users/');
    } catch (e) {
      // Load failure has no form to land on — the global overlay is the venue.
      showError(errorMessage(e, 'Could not load.'));
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(data) {
    formError = '';
    fieldErrs = {};
    try {
      const created = await api.post('/api/jobs/', data);
      push(`/jobs/${created.job_id}`);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    }
  }

  function handleCancel() {
    push('/jobs');
  }

  load();
</script>

<div class="page-body">
<h2>New Job</h2>

{#if loading}
  <p>Loading...</p>
{:else if !$canManageJobs}
  <p>You do not have permission to create jobs.</p>
{:else}
  <JobForm
    {users}
    defaultContactId={contextContactId}
    errors={fieldErrs}
    {formError}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
</div>
