<script>
  import { emailApi } from '../../lib/email.js';
  import { push } from 'svelte-spa-router';
  import JobPicker from '../../components/JobPicker.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let selectedJobId = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      email = await emailApi.get(params.id);
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

  $effect(() => {
    void params.id;
    load();
  });
</script>

<div class="page-body">
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
      <label><strong>Job *</strong></label><br>
      <JobPicker bind:value={selectedJobId} />
    </p>

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Associating…' : 'Associate Email with Job'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
</div>
