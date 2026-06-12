<script>
  import { push, link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import JobHeader from '../../components/jobs/JobHeader.svelte';

  const { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let workTemplates = $state([]);
  let loading = $state(true);
  let error = $state('');
  let saving = $state(false);
  let templateId = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      const [jobResp, tmplResp] = await Promise.all([
        api.get(`/api/jobs/${params.id}/`),
        api.get('/api/work-templates/?page_size=100'),
      ]);
      job = jobResp;
      workTemplates = tmplResp.results || tmplResp;
      if (job.contact) {
        try {
          contact = await api.get(`/api/contacts/${job.contact}/`);
        } catch (e) {
          contact = null;
        }
      }
    } catch (e) {
      error = e.message || 'Could not load.';
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    saving = true;
    error = '';
    try {
      const payload = { job: Number(params.id) };
      if (templateId) payload.template = Number(templateId);
      const ws = await api.post('/api/est-worksheets/', payload);
      push(`/worksheets/${ws.est_worksheet_id}`);
    } catch (err) {
      if (err.data && typeof err.data === 'object' && !err.data.detail) {
        error = Object.entries(err.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = err.message || 'Could not create worksheet.';
      }
      saving = false;
    }
  }

  function handleCancel() {
    push(`/jobs/${params.id}`);
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error && !job}
  <p class="error">{error}</p>
{:else if !job?.can_manage}
  <p>You do not have permission to create worksheets.</p>
{:else if job}
  <JobHeader {job} {contact} onStatusChange={load} />

  <div class="toolbar">
    <a href={`/jobs/${job.job_id}`} use:link class="back-link">&laquo; back to overview</a>
    <h2 class="page-title">New Worksheet</h2>
  </div>

  <form onsubmit={handleSubmit} class="form-body">
    <p>
      <label for="template"><strong>Work Template (optional)</strong></label><br>
      <select id="template" bind:value={templateId}>
        <option value="">-- None (empty worksheet) --</option>
        {#each workTemplates as tmpl}
          <option value={tmpl.template_id}>{tmpl.template_name}</option>
        {/each}
      </select>
      <br>
      <small>Selecting a template pre-fills the worksheet with its tasks.</small>
    </p>

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Creating...' : 'Create Worksheet'}</button>
      <button type="button" onclick={handleCancel} disabled={saving}>Cancel</button>
    </p>

    {#if error}<p class="error">{error}</p>{/if}
  </form>
{/if}

<style>
  .error { color: #a8071a; }
  small { color: #666; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; margin: 0; margin-left: auto; }
  .form-body { padding: 0 24px; }
</style>
