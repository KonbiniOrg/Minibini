<script>
  import { emailApi, resolveSenderToContact } from '../../lib/email.js';
  import SenderResolutionForm from '../../components/email/SenderResolutionForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let loading = $state(true);
  let loadError = $state(null);
  let senderInfo = $state(null);
  let resolutionState = $state(null);

  let jobName = $state('');
  let jobDescription = $state('');

  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      senderInfo = await emailApi.senderInfo(params.id);
      jobName = senderInfo.subject || '';
      jobDescription = senderInfo.suggested_body || '';
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    submitError = null;
    submitting = true;
    try {
      const { contactId } = await resolveSenderToContact(resolutionState);
      const job = await emailApi.createJob(params.id, {
        contact: contactId,
        name: jobName.trim(),
        description: jobDescription.trim(),
      });
      push(`/jobs/${job.job_id}`);
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

<h2>Create Job from Email</h2>

<p><a href="#/email/{params.id}">&larr; Back to Email</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if senderInfo}
  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

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
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create Job'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
