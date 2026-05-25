<script>
  import { api } from '../../lib/api.js';
  import { emailApi } from '../../lib/email.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let email = $state(null);
  let jobs = $state([]);
  let selectedJobId = $state('');
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [emailData, jobsData] = await Promise.all([
        emailApi.get(params.id),
        api.get('/api/jobs/?page_size=500'),
      ]);
      email = emailData;
      jobs = jobsData.results || [];
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedJobId) {
      submitError = 'Please select a job.';
      return;
    }
    submitting = true;
    submitError = null;
    try {
      await emailApi.linkToJob(params.id, selectedJobId);
      push(`/email/${params.id}`);
    } catch (err) {
      submitError = err.message;
      submitting = false;
    }
  }

  function truncate(text, words = 10) {
    if (!text) return '';
    const parts = text.split(/\s+/);
    return parts.length <= words ? text : parts.slice(0, words).join(' ') + '…';
  }
</script>

<h2>Associate Email with Existing Job</h2>

<p><a href="#/email/{params.id}">&larr; Back to Email</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else}
  <h3>Email Summary</h3>
  <table class="data-table">
    <tbody>
      <tr><th>From:</th><td>{email.temp_email?.from_email || email.content?.from || ''}</td></tr>
      <tr><th>Subject:</th><td><strong>{email.temp_email?.subject || email.content?.subject || ''}</strong></td></tr>
    </tbody>
  </table>

  <h3>Select Job</h3>

  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

  <form onsubmit={handleSubmit}>
    <p>
      <label for="job_id"><strong>Job *</strong></label><br>
      <select id="job_id" bind:value={selectedJobId} required>
        <option value="">-- Select a Job --</option>
        {#each jobs as job}
          <option value={job.job_id}>
            {job.job_number} - {job.contact_name} - {truncate(job.description || job.name)}
          </option>
        {/each}
      </select>
    </p>

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Associating…' : 'Associate Email with Job'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
